/* eslint-disable userscripts/no-invalid-metadata */
// ↑ 本文件不是 Tampermonkey 用户脚本,是控制台粘贴片段,没有 ==UserScript== 元数据块是正常的。
//   eslint-plugin-userscripts 会把本目录下所有 .js 都当用户脚本查(因为旁边有个真的),这里关掉。

// 雀魂原始牌谱导出 —— 控制台直接粘贴运行,不需要 Tampermonkey。
//
// 用法:
//   1. 登录雀魂,点开要导出的牌谱,等回放界面加载出来
//   2. F12 打开开发者工具 → Console
//   3. 把本文件全文粘进去,回车
//   4. 浏览器会下载 <uuid>.json
//   5. dareda verify --record <uuid>.json
//
// 相比 downloadlogs 脚本的好处:只做"拉原始 record + 存文件"两件事,
// 不碰 cfg.fan / cfg.level_definition / cfg.item_definition 那些客户端配置表 ——
// 那里是 downloadlogs 在非日服客户端上最容易静默抛异常的地方。
//
// 输出格式与 downloadlogs(VERBOSELOG=true)一致,dareda 的解析器直接认。

(async () => {
    // 0. 找到游戏所在的 frame。
    //    DevTools 的 Console 默认停在最外层 top 页面,而游戏常常跑在 iframe 里,
    //    直接引用 GameMgr 会 ReferenceError。这里从 top 开始广度优先扫一遍同源 frame。
    function findGameContext() {
        const queue = [window];
        for (let i = 0; i < queue.length; i++) {
            const w = queue[i];
            try {
                if (w.GameMgr && w.GameMgr.Inst) return w;
                for (let j = 0; j < w.frames.length; j++) queue.push(w.frames[j]);
            } catch (e) {
                // 跨域 frame,碰不了,跳过
            }
        }
        return null;
    }

    const ctx = findGameContext();
    if (!ctx) {
        console.error("[dump] 所有能访问的 frame 里都没有 GameMgr。可能原因:");
        console.error("  a) 游戏还没加载完 —— 等回放界面真正出来再跑");
        console.error("  b) 游戏在跨域 iframe 里 —— 用 Console 左上角的上下文下拉框");
        console.error("     (默认显示 'top')切到游戏那个 frame,再重新粘贴运行");
        console.error("  c) 跑错标签页了");
        try {
            console.log("[dump] 当前页面:", location.href, "| frame 数:", window.frames.length);
            for (let i = 0; i < window.frames.length; i++) {
                let info;
                try {
                    info = window.frames[i].location.href + " | GameMgr: " +
                        (window.frames[i].GameMgr ? "有" : "无");
                } catch (e) {
                    info = "跨域,无法访问";
                }
                console.log(`  frame[${i}]:`, info);
            }
        } catch (e) { /* ignore */ }
        return;
    }
    if (ctx !== window) console.log("[dump] 游戏在 iframe 里,已自动切过去:", ctx.location.href);

    const GameMgr = ctx.GameMgr;
    const app = ctx.app;
    const net = ctx.net;
    if (!app || !app.NetAgent || !net || !net.MessageWrapper) {
        console.error("[dump] 找到 GameMgr 了,但 app.NetAgent / net.MessageWrapper 缺失,客户端结构对不上");
        return;
    }

    try {
        const uuid = GameMgr.Inst.record_uuid;
        if (!uuid) {
            console.error("[dump] 没有 record_uuid —— 请先点开一个牌谱再运行");
            return;
        }
        console.log("[dump] uuid =", uuid);

        // 1. 向大厅请求牌谱
        const record = await new Promise((resolve, reject) => {
            app.NetAgent.sendReq2Lobby(
                "Lobby",
                "fetchGameRecord",
                {
                    game_uuid: uuid,
                    client_version_string: GameMgr.Inst.getClientVersion(),
                },
                (err, res) => (res ? resolve(res) : reject(err || "no response"))
            );
        });
        console.log("[dump] fetchGameRecord 返回,head.uuid =", record.head && record.head.uuid);

        // 2. 取出动作流本体。长牌谱不走 data,而是甩一个 data_url 出来单独下载。
        let raw = record.data;
        if ((!raw || !raw.length) && record.data_url) {
            console.log("[dump] data 为空,改从 data_url 拉:", record.data_url);
            const buf = await (await fetch(record.data_url)).arrayBuffer();
            raw = new Uint8Array(buf);
        }
        if (!raw || !raw.length) {
            console.error("[dump] data 和 data_url 都没有,拿不到动作流");
            return;
        }

        // 3. 解 wrapper。新版客户端用 actions,老版用 records,两个都试。
        const detail = net.MessageWrapper.decodeMessage(raw);
        const mjslog = [];
        for (const a of detail.actions || []) {
            if (a.result && a.result.length) {
                mjslog.push(net.MessageWrapper.decodeMessage(a.result));
            }
        }
        if (!mjslog.length) {
            for (const r of detail.records || []) {
                mjslog.push(net.MessageWrapper.decodeMessage(r));
            }
        }
        if (!mjslog.length) {
            console.error("[dump] 动作流解出来是空的。detail 的字段:", Object.keys(detail));
            window.__mjs_detail = detail;   // 留给人工排查
            return;
        }

        const out = {
            mjshead: record.head,
            mjslog: mjslog,
            mjsrecordtypes: mjslog.map((e) => e.constructor.name),
        };

        const rounds = mjslog.filter((e) => e && e.paishan).length;
        console.log(`[dump] 动作 ${mjslog.length} 条,其中带 paishan 的小局 ${rounds} 个`);
        if (!rounds) {
            console.warn("[dump] 一个 paishan 都没有 —— 这份数据对 dareda 没用,请把上面的日志发出来");
        }

        // 4. 存文件。用 Blob 而不是 data: URI,后者在大牌谱上会超长度限制。
        const text = JSON.stringify(out);
        const blob = new Blob([text], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = uuid + ".json";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 10000);

        window.__mjs_dump = out;  // 下载被拦时的后备:控制台执行 copy(JSON.stringify(__mjs_dump))
        console.log(`[dump] 完成,已下载 ${uuid}.json(${(text.length / 1024 / 1024).toFixed(2)} MB)`);
    } catch (err) {
        console.error("[dump] 失败:", err);
    }
})();
