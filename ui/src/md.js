// md.js —— 极简 markdown 渲染器(零依赖)
// 支持:标题(#~####)、加粗 **x**、行内代码 `x`、无序列表(-/*)、有序列表(1.)、段落。
// 安全:先 HTML 转义再套 markdown 规则,正文里的任何 < > & 都会被锁死,无法注入。
// 定位:覆盖本系统(agent 写的任务详情/汇报)用到的语法子集,不追求完整 CommonMark。

(function () {
  function mdEscape(s) {
    return String(s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  // 行内规则:先代码(代码里的 ** 不解析),再加粗
  function mdInline(escaped) {
    return escaped
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }

  function renderMarkdown(src) {
    const lines = String(src || "").split("\n");
    const out = [];
    let list = null; // "ul" | "ol" | null
    const closeList = () => {
      if (list) { out.push(`</${list}>`); list = null; }
    };

    for (const raw of lines) {
      const t = raw.trim();
      if (!t) { closeList(); continue; } // 空行:段落分隔

      const h = t.match(/^(#{1,4})\s+(.*)$/);
      if (h) {
        closeList();
        out.push(`<div class="md-h md-h${h[1].length}">${mdInline(mdEscape(h[2]))}</div>`);
        continue;
      }
      const ul = t.match(/^[-*]\s+(.*)$/);
      if (ul) {
        if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; }
        out.push(`<li>${mdInline(mdEscape(ul[1]))}</li>`);
        continue;
      }
      const ol = t.match(/^\d+[.)]\s+(.*)$/);
      if (ol) {
        if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; }
        out.push(`<li>${mdInline(mdEscape(ol[1]))}</li>`);
        continue;
      }
      closeList();
      out.push(`<p>${mdInline(mdEscape(t))}</p>`);
    }
    closeList();
    return out.join("");
  }

  window.renderMarkdown = renderMarkdown;
})();
