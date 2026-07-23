# mortal-replay

**在你那局的原牌山上重打一遍,回答"这把到底是我打得烂,还是运气差"。**

雀魂的牌谱里存着**完整牌山**。把它取出来注入麻将引擎,就能在**一模一样的发牌**下
反复重放 —— 于是"牌"和"打法"这两个混在一起的东西,可以被分开量化。

```
座1 同水平自打分布  n=30  平均顺位 2.00
    1位  46.7%  ████████████████
    2位  23.3%  ████████
    3位  13.3%  ████
    4位  16.7%  ██████

实际 4 位;同水平自打期望 2.00 位。
  判断:偏背 —— 你的同水平只有 17% 会打到 4 位或更差
```

---

## ⚠ 先读这个

1. **只做赛后复盘。** 本项目不提供、也不应被用于对局进行中的任何辅助。
2. **取牌谱要在浏览器里改雀魂客户端的行为 —— 这很可能违反雀魂用户协议,有封号风险。**
   用不用你自己定,风险自负。建议用小号、单独环境。
3. **不分发模型权重。** Mortal 作者出于**防作弊**考虑刻意不公开权重
   ([他的说明](https://gist.github.com/Equim-chan/cf3f01735d5d98f1e7be02e94b288c56)),
   改以受控在线服务提供。你若选用第三方 checkpoint,请自行获取、自负其责。
4. 许可证 **AGPL-3.0-or-later**。**架成网络服务的话,AGPL 第 13 条要求你向所有用户
   提供完整源码。** 详见 [NOTICE](NOTICE)。

## 它能回答什么

| 命令 | 问题 |
|---|---|
| `self-luck` | **以我现有的水平**,这副牌重打很多次,我这个名次算运气好还是差? |
| `replay` | 四家都换成顶尖 AI,这副牌能打成什么样? |
| `counterfactual` | 对手照原样打,只有我换成 AI,会怎样?(带保真度) |
| `montecarlo` | 上面那个跑成**分布**,并做对手强度敏感性分析 |

`self-luck` 是最推荐的一个 —— 它把四家都设成各自的真实水平重打,不拿你跟超人比,
而是问"**同样水平的我**,这局通常会是什么结果"。

## 安装

需要 Python 3.11+、Rust 工具链、约 130 MB 磁盘放权重。

```bash
# 1. 本项目
git clone <this-repo> mortal-replay && cd mortal-replay
pip install -e .

# 2. Mortal / libriichi(上游,AGPL-3.0)+ 本项目的补丁
git clone --depth 1 https://github.com/Equim-chan/Mortal.git vendor/Mortal
cp patches/replay.rs vendor/Mortal/libriichi/src/arena/replay.rs
git -C vendor/Mortal apply ../../patches/arena-mod.patch

# 3. 编译扩展
cd vendor/Mortal/libriichi && cargo build --release && cd ../../..

# 4. 放到 Python 能 import 的地方。注意改名!
#    模块入口是 PyInit_libriichi,但 crate 产物叫 riichi —— 不改名会报
#    "dynamic module does not define module export function"
cp vendor/Mortal/target/release/riichi.dll  libriichi.pyd   # Windows
# cp vendor/Mortal/target/release/libriichi.so libriichi.so # Linux/macOS

# 5. 权重(本项目不分发,自行获取)
mkdir -p models && curl -L -o models/mortal_298k.pth \
  https://huggingface.co/VoidShine/mortal-298k/resolve/main/mortal_298k.pth
```

跑之前确认 `libriichi` 和 `vendor/Mortal/mortal` 都在 `PYTHONPATH` 里:

```bash
export PYTHONPATH="src:vendor/Mortal/mortal:."     # Windows 用 ; 分隔
python -c "import libriichi; print(libriichi.__profile__)"   # 应输出 release
```

## 取牌谱

国服客户端是 Unity WebGL,游戏逻辑在 WASM 里,老一辈"调页面 JS 全局"的导出脚本
(downloadlogs 那类)在上面**结构性失效**。本项目改成录 WebSocket 原始帧再离线解码。

1. 装 [Tampermonkey](https://www.tampermonkey.net/),把
   [tools/majsoul-ws-capture.user.js](tools/majsoul-ws-capture.user.js) 全文粘进去并启用
2. **刷新雀魂页面**(必须 —— 脚本要赶在 WebSocket 建连之前生效)
3. 登录 → 点开要分析的牌谱 → 等回放界面出来 → 按 <kbd>D</kbd>,浏览器下载 `majsoul-ws-*.json`
4. 解码:

```bash
mortal-replay decode-capture --capture majsoul-ws-*.json --out record.json
mortal-replay verify --record record.json      # 自检:配牌恒等断言,必须全过
```

`verify` 全过才说明牌山取对了,后面的分析才有意义。排错见 [tools/README.md](tools/README.md)。

> 抓包脚本只读不改流量,但这终究是在动客户端。风险见文首第 2 条。

## 用

先看 `inspect` 找出你是几号座(按昵称认;牌谱链接里 `_a` 后面那串是混淆过的分享码,
**不是** account_id,认不出座位):

```bash
mortal-replay inspect --record record.json
```

然后:

```bash
# 推荐:以你自己的水平重打 30 次,看你这个名次是运气好还是差
mortal-replay self-luck --record record.json --hero 1 --trials 30

# 四家全换顶尖 AI
mortal-replay replay --record record.json

# 对手照原样打,只有你换 AI(输出带保真度,低保真度的局别当真)
mortal-replay counterfactual --record record.json --hero 1

# 分布 + 对手强度敏感性
mortal-replay montecarlo --record record.json --hero 1 --trials 20 --sensitivity
```

CPU 上一条轨迹约 7 秒,所以 `--trials 30` 要跑 3-4 分钟。有 CUDA 的话加 `--device cuda:0`。

## 怎么读结果(重要)

这类工具最容易被过度解读,几条边界请务必记住:

**单次 replay 不能下结论。** 麻将单局方差极大,一次重放的名次差里,信号被噪声盖住。
要看就看 `self-luck` / `montecarlo` 的**分布**,不要看单次的名次。

**`counterfactual` 的保真度通常很低。** 你一旦打出和原局不同的牌,turn order 就错位,
对手的日志失去对齐,只能回落到 AI —— 实测忠实比例中位数只有 ~12%。输出里每局都标了
保真度,**低保真度的局基本等于 AI 互打,别当成"如果我那样打就会怎样"**。

**"同水平"是拿这一局测出来的。** `self-luck` 用你在**这局**的决策质量(EV loss)标定,
样本只有一场约 200 个决策,而且是在你面对真人时测的、却用在 AI 牌桌上。所以它给的是
**运气的大致方向**,不是精确概率。

**它证伪不了"恶调"。** 验平台公平性需要几万局尺度的统计量。本工具只帮你理解自己这一局。

## 许可证

AGPL-3.0-or-later,见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。

本项目**不含** Mortal 的任何代码(只提供补丁),也**不分发**任何模型权重。
上游 Mortal 由 [Equim-chan](https://github.com/Equim-chan/Mortal) 开发,AGPL-3.0。
