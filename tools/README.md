# tools/

## 先看这里:该用哪个

| 客户端 | 用哪个 |
|---|---|
| **国服 `game.maj-soul.com`(Unity WebGL)** | **`majsoul-ws-capture.user.js`** —— 唯一可行 |
| 老的 Laya/JS 客户端 | `dump-raw-record.js` |
| 不确定 | 先跑 `diagnose-context.js` |

判据:控制台里 `document.querySelector('canvas').id` —— 是 `unity-canvas` 就是
Unity 版,`GameMgr` / `app.NetAgent` / `net.MessageWrapper` 全部不存在,
下面那两个基于页面 JS 全局的脚本一律失效(**症状是脚本在跑但按键毫无反应**:
处理函数第一行就 ReferenceError,静默死掉)。

## majsoul-ws-capture.user.js(国服用这个)

Unity WebGL 开不了原始 socket,网络必须借道浏览器 API。所以在 JS 层把
`WebSocket` 构造函数换掉,录下原始帧,离线在 Python 里解。

1. 装 [Tampermonkey](https://www.tampermonkey.net/),把本文件粘进去,确认已启用
2. **刷新雀魂页面** —— 必须刷新,`@run-at document-start` 要早于游戏建连
3. 登录 → 点开牌谱 → 等回放界面出来 → 按 <kbd>D</kbd>
4. `mortal-replay decode-capture --capture majsoul-ws-*.json --out record.json`

控制台会实时打印录到多少帧。按 D 没动静的话,在控制台执行 `__mjsCapture.dump()`。

**排错**

- *"一帧都没录到"* —— 脚本是在建连之后才生效的。刷新页面重来。
- *decode 报"没找到 fetchGameRecord 的响应"* —— 抓包时没真正点开牌谱,
  或者是刷新前就已经打开的牌谱(那次请求发生在开始录之前)。回大厅重新点进去。
- 文件很大 —— 脚本已经过滤掉游戏资源(`.unity3d`/`.wasm` 等),正常几百 KB 到几 MB。
  早期版本没过滤会产出 ~95 MB 的文件,**别用编辑器打开**,超长单行会让 VSCode/Word 卡死;
  直接喂给 `decode-capture` 就行。

## dump-raw-record.js(老客户端)

控制台直接粘贴运行,不需要 Tampermonkey。

1. 登录雀魂,点开牌谱,等回放界面加载出来
2. <kbd>F12</kbd> → Console
3. 把 [dump-raw-record.js](dump-raw-record.js) 全文粘进去,回车
4. 下载 `<uuid>.json` → `mortal-replay verify --record <uuid>.json`

它只做两件事:调 `fetchGameRecord` 拿原始 record、存成文件。**不碰**
`cfg.fan` / `cfg.level_definition` / `cfg.item_definition` 那些客户端配置表 ——
那是 downloadlogs 在非日服客户端上最容易静默抛异常的地方(表现就是"按 S 没反应")。

额外处理了两种 downloadlogs 没管的情况:

- 长牌谱的动作流不在 `record.data` 里,而是甩一个 `record.data_url` 出来单独下载
- 新版客户端用 `detail.actions`,老版用 `detail.records`,两个都试

每一步都往控制台打日志,失败时能直接看出卡在哪。

**`GameMgr is not defined`**:控制台的执行上下文不对 —— 游戏跑在 iframe 里,而
Console 默认停在最外层 `top` 页面。脚本会自动扫同源 frame 找过去;要是那个 iframe
跨域,自动找不到,就手动切:Console 面板左上角有个上下文下拉框(默认显示 `top`),
换成游戏那个 frame,再重新粘贴运行。
