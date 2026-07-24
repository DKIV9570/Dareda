# 誰だ / dareda

### 这把怪谁?

摔完牌之后的那句吐槽,现在能算了。

雀魂的牌谱里存着**完整牌山**。把它取出来注入麻将引擎,就能在**一模一样的发牌**下
反复重放几十遍 —— 于是"牌"和"打法"这两个搅在一起的东西,可以被分开量化。

**它不告诉你"是恶调",它告诉你一个分布。**

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

> ### ⚠ 请务必装在虚拟环境里
>
> **本项目会动 `protobuf` 的版本。** 依赖声明是 `protobuf>=4.25`,所以在一个已有的
> 环境里 `pip install` 时,如果你原本的 protobuf 低于 4.25,pip 会**把它升上去** ——
> 这可能弄坏你环境里依赖老 protobuf 的其它包(常见的有 `googleapis-common-protos`、
> `google-api-core`、`proto-plus`、`wandb`、`paddlepaddle`,它们不少要求 `protobuf<7`)。
>
> 装进 venv 就完全不会波及你的其它项目:
>
> ```bash
> python -m venv .venv
> .venv/Scripts/activate      # Windows
> # source .venv/bin/activate # Linux/macOS
> ```
>
> 关于 protobuf 兼容性,本项目已在 **4.25.9 和 7.35.1 上实测通过**。之所以能跨这么大
> 版本,是因为 liqi schema 用的是**描述符集**(`liqi.desc`)而不是 `protoc` 生成的
> `*_pb2.py` —— 后者带运行时版本断言,会把你钉死在某个 protobuf 大版本上。
>
> **另外:不要装 `pip install -e ".[proto]"`,除非你要重新编译 schema。** 那个 extra
> 会拉 `grpcio-tools`,它会把 protobuf 顶到 7.x —— 正是上面说的破坏来源。日常使用
> 完全用不到它(`liqi.desc` 已随包提供)。

```bash
# 1. 本项目
git clone https://github.com/DKIV9570/Dareda.git dareda && cd dareda
python -m venv .venv && .venv/Scripts/activate    # ← 见上面的警告
pip install -e .

# 2. 分析功能需要 PyTorch + numpy(本项目**不**自动装 —— torch 要按你的
#    CUDA/CPU 情况选对应版本,装错了跑不动)。去 https://pytorch.org 拿命令,
#    或者只用 CPU 的话:
pip install numpy torch --index-url https://download.pytorch.org/whl/cpu

# 3. Mortal / libriichi(上游,AGPL-3.0)+ 本项目的补丁
git clone --depth 1 https://github.com/Equim-chan/Mortal.git vendor/Mortal
cp patches/replay.rs vendor/Mortal/libriichi/src/arena/replay.rs
git -C vendor/Mortal apply ../../patches/arena-mod.patch
#    补丁只是往 arena/mod.rs 加 4 行注册。上游哪天改了那个文件导致 apply 失败,
#    手动加也一样(见 patches/arena-mod.patch 的内容):
#      mod replay;
#      pub use replay::{KyokuOutcome, KyokuReplay};
#      m.add_class::<KyokuReplay>()?;
#      m.add_class::<KyokuOutcome>()?;

# 4. 编译扩展
cd vendor/Mortal/libriichi && cargo build --release && cd ../../..

# 5. 放到 Python 能 import 的地方。注意改名!
#    模块入口是 PyInit_libriichi,但 crate 产物叫 riichi —— 不改名会报
#    "dynamic module does not define module export function"
cp vendor/Mortal/target/release/riichi.dll  libriichi.pyd   # Windows
# cp vendor/Mortal/target/release/libriichi.so libriichi.so # Linux/macOS

# 6. 权重(本项目不分发,自行获取)
mkdir -p models && curl -L -o models/mortal_298k.pth \
  https://huggingface.co/VoidShine/mortal-298k/resolve/main/mortal_298k.pth
```

### Windows 用户:请把项目放在**短路径**下

比如 `C:\dev\dareda`,不要放在很深的目录里。

Windows 默认有 260 字符的路径上限,而 **torch 的 wheel 里带了极深的第三方许可证目录**
(`torch-*.dist-info/licenses/third_party/flash-attention/third_party/aiter/3rdparty/...`)。
实测这部分**光它自己就占 138 字符** —— 也就是说你的项目路径超过约 120 字符就会炸:

```
ERROR: Could not install packages due to an OSError:
[WinError 206] 文件名或扩展名太长
```

**更坑的是它装到一半就停了**,留下一个残缺的 torch,之后 `import torch` 报的却是
莫名其妙的 `ModuleNotFoundError: No module named 'torchgen'` —— 和真正的原因毫无关系,
而且这个残骸连 `pip uninstall` 都卸不掉(没有 RECORD 文件)。

实测对照:同一条命令、同一个 `torch 2.13.0+cpu`,在 113 字符的深目录下安装失败,
换到 `C:\t_dv`(6 字符)后一次装成。**所以这不是 torch 或命令的问题,就是路径长度。**

遇到这个情况:**删掉整个 `.venv` 重来**,并换到短路径。或者开启 Windows 长路径支持:

```powershell
# 管理员 PowerShell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
  -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
git config --system core.longpaths true
```

### 设置 PYTHONPATH

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
dareda decode-capture --capture majsoul-ws-*.json --out record.json
dareda verify --record record.json      # 自检:配牌恒等断言,必须全过
```

`verify` 全过才说明牌山取对了,后面的分析才有意义。排错见 [tools/README.md](tools/README.md)。

> 抓包脚本只读不改流量,但这终究是在动客户端。风险见文首第 2 条。

## 用

先看 `inspect` 找出你是几号座(按昵称认;牌谱链接里 `_a` 后面那串是混淆过的分享码,
**不是** account_id,认不出座位):

```bash
dareda inspect --record record.json
```

然后:

```bash
# 推荐:以你自己的水平重打 30 次,看你这个名次是运气好还是差
dareda self-luck --record record.json --hero 1 --trials 30

# 四家全换顶尖 AI
dareda replay --record record.json

# 对手照原样打,只有你换 AI(输出带保真度,低保真度的局别当真)
dareda counterfactual --record record.json --hero 1

# 分布 + 对手强度敏感性
dareda montecarlo --record record.json --hero 1 --trials 20 --sensitivity
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
