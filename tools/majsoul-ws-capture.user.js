// ==UserScript==
// @name         majsoul-ws-capture
// @namespace    dareda
// @version      0.3.0
// @description  录下雀魂客户端的 WebSocket 原始帧,用于离线提取牌谱牌山
// @match        https://game.maj-soul.com/*
// @match        https://www.maj-soul.com/*
// @match        https://game.mahjongsoul.com/*
// @match        https://mahjongsoul.game.yo-star.com/*
// @match        https://majsoul.union-game.com/*
// @run-at       document-start
// @grant        none
// ==/UserScript==

// 为什么需要这个:国服客户端已经是 Unity WebGL(canvas id=unity-canvas),
// 游戏逻辑编译进 WASM,GameMgr / app.NetAgent / net.MessageWrapper 这些
// JS 全局不复存在 —— 所有基于"调用页面全局"的导出脚本(downloadlogs 及其衍生)
// 在这个客户端上都失效。
//
// 但 Unity WebGL 开不了原始 socket,网络必须借道浏览器 API。所以游戏的
// WebSocket 仍然是 JS 层的 new WebSocket(...),在它建连之前把构造函数换掉,
// 就能把收发的原始字节全录下来。解码不在这里做,存盘后交给 Python。
//
// 两个硬性要求,缺一不可:
//   @run-at document-start —— 必须早于游戏建连
//   @grant none            —— 必须跑在页面上下文,否则改的是隔离世界里的 WebSocket
//
// 用法:
//   1. 装进 Tampermonkey,确认已启用
//   2. 刷新雀魂页面(必须刷新!脚本要在建连前生效)
//   3. 登录 → 点开要导出的牌谱 → 等回放界面出来
//   4. 点右下角的「⬇ 导出牌谱」按钮下载 majsoul-ws-<时间戳>.json(远小于 1 MB)
//   5. dareda decode-capture --capture majsoul-ws-*.json --out record.json
//   6. dareda verify --record record.json
//
// 只在雀魂域名生效(@match 精确匹配),不会碰别的网站。导出用悬浮按钮,不再绑热键
// —— 避免在输入框打字或随手按键时误触下载(0.2.0 用裸 D 键会误触)。

(function () {
    "use strict";

    const MAX_TOTAL_BYTES = 128 * 1024 * 1024;

    // HTTP 侧的过滤。
    //
    // 实测(260723 那份抓包):牌谱走 WebSocket,126 KB;WS 全部加起来 0.18 MB。
    // 而 HTTP 有 71.36 MB,全是游戏资源 —— 光 wasm.gz 和 data.gz 就 69 MB。
    // 不过滤的话文件 95 MB,任何编辑器一打开就崩。
    //
    // 之所以还留着 HTTP 钩子:长牌谱的动作流可能不内嵌,而是甩一个 data_url
    // 让客户端单独下载。那条路目前没实际遇到过,属于兜底。
    //
    // 按扩展名过滤有个坑:资源 URL 是 `...release-4.0.45(45).wasm.gz`,
    // 结尾是 .gz 不是 .wasm,只匹配 `\.wasm(\?|$)` 会漏掉最大的那两个文件。
    // 所以扩展名后面要允许 .gz/.br/.zst,并且再加一层按路径过滤。
    const HTTP_MAX_BYTES = 4 * 1024 * 1024;
    const HTTP_SKIP_PATH = /\/(assetbundles|Build|res|audio|scene)\//i;
    const HTTP_SKIP_EXT =
        /\.(unity3d|wasm|data|js|css|png|jpe?g|webp|gif|svg|mp3|ogg|wav|ttf|woff2?|atlas|lh|mp4|majset|bin)(\.(gz|br|zst))?(\?|#|$)/i;
    const skipUrl = (u) => HTTP_SKIP_PATH.test(String(u || "")) || HTTP_SKIP_EXT.test(String(u || ""));
    const frames = [];
    let totalBytes = 0;
    let seq = 0;
    let dropped = 0;

    const t0 = Date.now();
    const log = (...a) => console.log("%c[ws-capture]", "color:#0a0", ...a);

    function toB64(buf) {
        const bytes = new Uint8Array(buf);
        let s = "";
        const CHUNK = 0x8000;             // 分块,避免 apply 参数过多爆栈
        for (let i = 0; i < bytes.length; i += CHUNK) {
            s += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
        }
        return btoa(s);
    }

    function record(dir, buf, meta) {
        if (!buf || !buf.byteLength) return;
        if (totalBytes + buf.byteLength > MAX_TOTAL_BYTES) {
            dropped++;
            if (dropped === 1) log("已达内存上限,后续帧丢弃。请先点「导出牌谱」存盘");
            return;
        }
        totalBytes += buf.byteLength;
        frames.push({
            seq: seq++,
            dir: dir,
            t: Date.now() - t0,
            size: buf.byteLength,
            b64: toB64(buf),
            ...(meta || {}),
        });
        if (frames.length % 50 === 0) {
            log(`已录 ${frames.length} 帧 / ${(totalBytes / 1024 / 1024).toFixed(2)} MB`);
        }
    }

    function absorb(dir, data, meta) {
        if (data instanceof ArrayBuffer) {
            record(dir, data, meta);
        } else if (ArrayBuffer.isView(data)) {
            record(dir, data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength), meta);
        } else if (typeof Blob !== "undefined" && data instanceof Blob) {
            // Blob 要异步取字节;seq 在 record 里才分配,顺序可能与到达顺序略有出入,
            // 影响不大 —— Python 侧靠内容识别,不靠顺序。
            data.arrayBuffer().then((buf) => record(dir, buf, meta)).catch(() => {});
        }
        // 文本帧不要(雀魂走二进制)
    }

    // ---------------------------------------------------------------- WebSocket
    const OrigWS = window.WebSocket;
    class HookedWS extends OrigWS {
        constructor(url, protocols) {
            protocols === undefined ? super(url) : super(url, protocols);
            log("WebSocket 建连:", url);
            this.addEventListener("message", (ev) => absorb("in", ev.data, { url: String(url) }));
        }
        send(data) {
            absorb("out", data, { url: String(this.url) });
            return super.send(data);
        }
    }
    HookedWS.prototype.constructor = HookedWS;
    window.WebSocket = HookedWS;

    // ------------------------------------------------- fetch / XHR(data_url 兜底)
    // 长牌谱的动作流不走 WS,而是甩一个 data_url 让客户端单独下载。
    function wantHttp(url, byteLength) {
        if (byteLength <= 1024 || byteLength > HTTP_MAX_BYTES) return false;
        return !skipUrl(url);
    }

    const origFetch = window.fetch;
    if (origFetch) {
        window.fetch = function (input, init) {
            const url = typeof input === "string" ? input : (input && input.url) || "";
            if (skipUrl(url)) return origFetch.call(this, input, init);
            return origFetch.call(this, input, init).then((res) => {
                try {
                    res.clone().arrayBuffer()
                        .then((buf) => {
                            if (wantHttp(url, buf.byteLength)) absorb("http", buf, { url: url });
                        })
                        .catch(() => {});
                } catch (e) { /* ignore */ }
                return res;
            });
        };
    }

    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) {
        this.__cap_url = url;
        return origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function () {
        this.addEventListener("load", () => {
            try {
                const r = this.response;
                if (r && (r instanceof ArrayBuffer) && wantHttp(this.__cap_url, r.byteLength)) {
                    absorb("http", r, { url: this.__cap_url });
                }
            } catch (e) { /* ignore */ }
        });
        return origSend.apply(this, arguments);
    };

    // ---------------------------------------------------------------- 下载
    function dump() {
        if (!frames.length) {
            log("一帧都没录到 —— 脚本可能是在建连之后才生效的,请刷新页面重来");
            return;
        }
        const out = {
            captured_at: new Date(t0).toISOString(),
            page: location.href,
            frame_count: frames.length,
            total_bytes: totalBytes,
            dropped: dropped,
            frames: frames,
        };
        const text = JSON.stringify(out);
        const blob = new Blob([text], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "majsoul-ws-" + t0 + ".json";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        log(`已存盘:${frames.length} 帧 / ${(text.length / 1024 / 1024).toFixed(2)} MB`);
    }

    window.__mjsCapture = { frames: frames, dump: dump };

    // 悬浮按钮:点了才下载,永远不会误触(不再绑热键)。
    // 脚本在 document-start 跑,body 可能还没有,等 DOM 就绪再插按钮。
    function addButton() {
        if (document.getElementById("mjs-cap-btn")) return;
        const btn = document.createElement("button");
        btn.id = "mjs-cap-btn";
        btn.textContent = "⬇ 导出牌谱";
        btn.style.cssText = [
            "position:fixed", "right:14px", "bottom:14px", "z-index:2147483647",
            "padding:8px 14px", "font:14px/1.2 sans-serif", "color:#fff",
            "background:#3987e5", "border:none", "border-radius:8px",
            "cursor:pointer", "opacity:0.55", "box-shadow:0 2px 8px rgba(0,0,0,.4)",
            "transition:opacity .15s",
        ].join(";");
        btn.addEventListener("mouseenter", () => (btn.style.opacity = "1"));
        btn.addEventListener("mouseleave", () => (btn.style.opacity = "0.55"));
        btn.addEventListener("click", dump);
        document.body.appendChild(btn);
    }
    if (document.body) addButton();
    else document.addEventListener("DOMContentLoaded", addButton);

    log("已挂钩 WebSocket / fetch / XHR。点开牌谱后点右下角「导出牌谱」按钮(或控制台执行 __mjsCapture.dump())");
})();
