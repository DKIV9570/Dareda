/* eslint-disable userscripts/no-invalid-metadata */
// 控制台上下文诊断 —— 搞清楚 GameMgr 到底在哪。
//
// 用法:在雀魂页面 F12 → Console → 粘贴全文 → 回车 → 把输出全部发出来。
//
// 所有输出都走 console.error,这样即使 Console 的级别过滤设成了 "Errors only"
// 也不会被藏起来(console.log 会被藏,这是常见的排错盲区)。

(() => {
    const L = (...a) => console.error("[diag]", ...a);

    L("=========== 基本信息 ===========");
    L("location :", location.href);
    L("readyState:", document.readyState);
    L("title    :", document.title);

    L("=========== 目标全局是否存在 ===========");
    for (const name of ["GameMgr", "app", "net", "cfg", "uiscript", "Laya", "GameConfig"]) {
        L(`  window.${name} :`, typeof window[name]);
    }
    if (typeof window.GameMgr !== "undefined") {
        try {
            L("  GameMgr.Inst  :", typeof window.GameMgr.Inst);
            L("  record_uuid   :", window.GameMgr.Inst && window.GameMgr.Inst.record_uuid);
        } catch (e) {
            L("  读 GameMgr.Inst 出错:", e.message);
        }
    }

    L("=========== 是否在扩展沙箱里 ===========");
    // Tampermonkey 等扩展会把脚本放进 isolated world,那里看不到页面的全局,
    // 得通过 unsafeWindow 才能碰到。如果这一项不是 undefined,说明当前不是页面上下文。
    L("  typeof unsafeWindow:", typeof unsafeWindow);
    try {
        if (typeof unsafeWindow !== "undefined") {
            L("  unsafeWindow.GameMgr:", typeof unsafeWindow.GameMgr);
        }
    } catch (e) {
        L("  读 unsafeWindow 出错:", e.message);
    }

    L("=========== 全局名字里的线索 ===========");
    let keys = [];
    try {
        keys = Object.keys(window);
    } catch (e) {
        L("  枚举 window 失败:", e.message);
    }
    L("  window 上全局总数:", keys.length);
    const hits = keys.filter((k) => /game|mgr|mjs|majsoul|maj_soul|uiscript|laya|net$|^net/i.test(k));
    L("  疑似相关全局:", hits.length ? hits.slice(0, 80).join(", ") : "(一个都没有)");

    L("=========== frame 结构 ===========");
    L("  window === top :", window === window.top);
    L("  window.frames.length:", window.frames.length);
    for (let i = 0; i < window.frames.length; i++) {
        try {
            L(`  frame[${i}] href=`, window.frames[i].location.href,
              "| GameMgr:", typeof window.frames[i].GameMgr);
        } catch (e) {
            L(`  frame[${i}] : 跨域,无法访问`);
        }
    }
    const iframes = document.querySelectorAll("iframe");
    L("  <iframe> 标签数:", iframes.length);
    iframes.forEach((f, i) => L(`    iframe[${i}] src=`, f.src || "(空)"));

    L("=========== canvas(判断游戏是否真的在本页渲染)===========");
    const canvases = document.querySelectorAll("canvas");
    L("  <canvas> 标签数:", canvases.length);
    canvases.forEach((c, i) => L(`    canvas[${i}] ${c.width}x${c.height} id=${c.id || "(无)"}`));

    L("=========== 诊断结束,请把以上全部内容发出来 ===========");
})();
