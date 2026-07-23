//! 单局 replay —— mortal-replay 的注入入口。
//!
//! 为什么不能用 `BatchGame`:它自带连庄判定、本场累加和终局条件(西入、30000 点
//! 检查等)。而 mortal-replay 要的是 spec §1.1 的"序列外生钉死" —— 局次、本场、
//! 何时结束全部由人类牌谱给定,replay 里庄家和了也不额外插连庄局。两套规则直接
//! 冲突,所以这里只做**一局**:塞一个 `Board` 进去,打完返回,序列推进和终止判定
//! 留给调用方(Python 侧的 driver)。
//!
//! `Board` 的字段本来就是 pub 的(上游注释:"The fields are all pub on purpose so
//! the caller will be able to set the yama, doras, scores directly"),所以牌山注入
//! 不需要改动任何既有代码,本文件是纯新增。
//!
//! 方向约定照抄 `Board` 的文档,调用方必须按同样的方向摆好数组:
//!   yama / rinshan / dora_indicators —— goes backward,即 `pop()` 取下一张
//!   ura_indicators                   —— goes forward

use super::board::{Board, Poll};
use crate::agent::new_py_agent;
use crate::tile::Tile;

use anyhow::{Context, Result, ensure};
use pyo3::prelude::*;
use serde_json as json;

/// 一局打完的结果。字段与 `KyokuResult` 对齐,外加 mjai 日志。
#[pyclass]
#[derive(Debug, Clone)]
pub struct KyokuOutcome {
    /// 本局结束后的四家点数(含立直棒扣分,不含未回收的供托)
    #[pyo3(get)]
    pub scores: [i32; 4],
    /// 相对入局点数的增减
    #[pyo3(get)]
    pub deltas: [i32; 4],
    #[pyo3(get)]
    pub has_hora: bool,
    #[pyo3(get)]
    pub has_abortive_ryukyoku: bool,
    /// 庄家是否具备连庄条件。**replay 不据此推进序列**,仅供对照分析。
    #[pyo3(get)]
    pub can_renchan: bool,
    /// 本局结束时场上剩余的立直棒
    #[pyo3(get)]
    pub kyotaku_left: u8,
    /// mjai 事件流,每行一个 JSON
    #[pyo3(get)]
    pub mjai_log: Vec<String>,
}

/// 用四个 Python 引擎在**指定牌山**上打一局。
///
/// ```python
/// runner = libriichi.arena.KyokuReplay(engine)          # 一个引擎带四家
/// runner = libriichi.arena.KyokuReplay([e0, e1, e2, e3]) # 或各家独立
/// outcome = runner.run(haipai=..., yama=..., ...)
/// ```
#[pyclass]
pub struct KyokuReplay {
    engines: Vec<PyObject>,
    /// engines 索引 → 座次;len 为 1 时四家共用同一个引擎
    shared: bool,
}

/// 调用方的 0–135 → libriichi 的 0–36。
///
/// 两套编码不一样,这是接口上最容易错的一处:
///   0–135  每种牌 4 枚各占一个 id,赤 5 固定占该 kind 的 copy 0(16 / 52 / 88)
///   0–36   0–33 是牌种,34/35/36 才是三张赤 5
///
/// 转换是多对一的(4 枚 → 1 个 kind),所以"136 张不重不漏"的校验必须在转换**之前**
/// 做,否则四枚同种牌会被误判成重复。
fn tile136_to_tile(t: u8) -> Result<Tile> {
    let id: u8 = match t {
        16 => 34, // 5mr
        52 => 35, // 5pr
        88 => 36, // 5sr
        _ => {
            ensure!(t < 136, "牌 id 越界: {t}");
            t / 4
        }
    };
    Tile::try_from(id).with_context(|| format!("0-135 的 {t} 转出非法 Tile {id}"))
}

fn to_tiles(v: &[u8], what: &str) -> Result<Vec<Tile>> {
    v.iter()
        .map(|&t| tile136_to_tile(t).with_context(|| format!("{what}: 牌 id {t}")))
        .collect()
}

#[pymethods]
impl KyokuReplay {
    #[new]
    fn new(engines: &Bound<'_, PyAny>) -> PyResult<Self> {
        let (engines, shared) = if let Ok(list) = engines.extract::<Vec<PyObject>>() {
            (list, false)
        } else {
            (vec![engines.clone().unbind()], true)
        };
        Ok(Self { engines, shared })
    }

    /// 打完一局。
    ///
    /// 牌山四件套的方向必须与 `Board` 一致,见本模块文档。
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (
        haipai, yama, rinshan, dora_indicators, ura_indicators,
        kyoku, honba, kyotaku, scores,
    ))]
    fn run(
        &mut self,
        py: Python<'_>,
        haipai: [[u8; 13]; 4],
        yama: Vec<u8>,
        rinshan: Vec<u8>,
        dora_indicators: Vec<u8>,
        ura_indicators: Vec<u8>,
        kyoku: u8,
        honba: u8,
        kyotaku: u8,
        scores: [i32; 4],
    ) -> Result<KyokuOutcome> {
        ensure!(yama.len() == 70, "yama 应为 70 张,实得 {}", yama.len());
        ensure!(rinshan.len() == 4, "rinshan 应为 4 张,实得 {}", rinshan.len());
        ensure!(
            dora_indicators.len() == 5,
            "dora_indicators 应为 5 张,实得 {}",
            dora_indicators.len()
        );
        ensure!(
            ura_indicators.len() == 5,
            "ura_indicators 应为 5 张,实得 {}",
            ura_indicators.len()
        );
        ensure!(kyoku < 8, "kyoku 越界: {kyoku}(0..7 = 东一..南四)");

        // 不重不漏检查 —— 牌山切错了在这里就炸,别等到牌局中途出怪事
        let mut seen = [0u8; 136];
        let mut count = |ids: &[u8]| -> Result<()> {
            for &t in ids {
                let slot = seen
                    .get_mut(t as usize)
                    .with_context(|| format!("牌 id 越界: {t}"))?;
                ensure!(*slot == 0, "牌 id {t} 出现了不止一次");
                *slot = 1;
            }
            Ok(())
        };
        for h in &haipai {
            count(h)?;
        }
        count(&yama)?;
        count(&rinshan)?;
        count(&dora_indicators)?;
        count(&ura_indicators)?;
        ensure!(
            seen.iter().all(|&x| x == 1),
            "牌山不完整:136 张里有缺失"
        );

        let board = Board {
            kyoku,
            honba,
            kyotaku,
            scores,
            haipai: [
                to_tiles(&haipai[0], "haipai[0]")?.try_into().unwrap(),
                to_tiles(&haipai[1], "haipai[1]")?.try_into().unwrap(),
                to_tiles(&haipai[2], "haipai[2]")?.try_into().unwrap(),
                to_tiles(&haipai[3], "haipai[3]")?.try_into().unwrap(),
            ],
            yama: to_tiles(&yama, "yama")?,
            rinshan: to_tiles(&rinshan, "rinshan")?,
            dora_indicators: to_tiles(&dora_indicators, "dora_indicators")?,
            ura_indicators: to_tiles(&ura_indicators, "ura_indicators")?,
        };

        let mut agents = if self.shared {
            vec![new_py_agent(
                self.engines[0].clone_ref(py),
                &[0, 1, 2, 3],
            )?]
        } else {
            ensure!(
                self.engines.len() == 4,
                "engines 应为 1 个(四家共用)或 4 个,实得 {}",
                self.engines.len()
            );
            self.engines
                .iter()
                .enumerate()
                .map(|(i, e)| new_py_agent(e.clone_ref(py), &[i as u8]))
                .collect::<Result<Vec<_>>>()?
        };
        // 座次 → (agent 下标, 该 agent 内部的 player_id 下标)
        let route: [(usize, usize); 4] =
            std::array::from_fn(|seat| if self.shared { (0, seat) } else { (seat, 0) });

        for (agent_idx, player_idx) in route {
            agents[agent_idx].start_game(player_idx)?;
        }

        let mut state = board.into_state();
        let mut reactions: [crate::mjai::EventExt; 4] = Default::default();

        loop {
            match state.poll(std::mem::take(&mut reactions))? {
                Poll::InGame => {
                    let ctx = state.agent_context();
                    for (seat, ps) in ctx.player_states.iter().enumerate() {
                        if !ps.last_cans().can_act() {
                            continue;
                        }
                        let (agent_idx, player_idx) = route[seat];
                        agents[agent_idx].set_scene(player_idx, ctx.log, ps, None)?;
                    }
                    let ctx = state.agent_context();
                    for (seat, ps) in ctx.player_states.iter().enumerate() {
                        if !ps.last_cans().can_act() {
                            continue;
                        }
                        let (agent_idx, player_idx) = route[seat];
                        reactions[seat] =
                            agents[agent_idx].get_reaction(player_idx, ctx.log, ps, None)?;
                    }
                }
                Poll::End => break,
            }
        }

        for (agent_idx, player_idx) in route {
            agents[agent_idx].end_kyoku(player_idx)?;
        }

        let result = state.end();
        let mjai_log = state
            .take_log()
            .iter()
            .map(|ev| json::to_string(ev).unwrap_or_default())
            .collect();

        Ok(KyokuOutcome {
            scores: result.scores,
            deltas: std::array::from_fn(|i| result.scores[i] - scores[i]),
            has_hora: result.has_hora,
            has_abortive_ryukyoku: result.has_abortive_ryukyoku,
            can_renchan: result.can_renchan,
            kyotaku_left: result.kyotaku_left,
            mjai_log,
        })
    }
}
