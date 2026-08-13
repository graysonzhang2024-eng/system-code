const KIND = {
  paper: ["📄", "论文"], podcast: ["🎧", "播客"], book: ["📖", "书籍"],
  course: ["🎓", "课程"], article: ["📰", "文章"], video: ["🎬", "视频"],
  other: ["💡", "其他"],
};
const NOTE = {
  summary: "摘要", insight: "思考", question: "疑问", connection: "联想",
  action: "行动", quote: "摘录",
};
let data = { items: [], stats: {} };
let kindFilter = "all";
const expanded = new Set();

function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function loadKnowledge() {
  const res = await window.steward.api("knowledge_list", {});
  if (!res || !res.ok) {
    document.getElementById("knowledge-content").innerHTML =
      `<p class="empty">知识库加载失败：${esc(res && res.error)}</p>`;
    return;
  }
  data = res.data || { items: [], stats: {} };
  render();
}

function renderStats() {
  const s = data.stats || {};
  const values = [
    [s.want || 0, "想学"], [s.learning || 0, "学习中"], [s.learned || 0, "已学"],
    [s.papers || 0, "论文"], [s.podcasts || 0, "播客"],
  ];
  document.getElementById("stats").innerHTML = values.map(([value, label]) =>
    `<div class="stat"><span class="stat-value">${value}</span><span class="stat-label">${label}</span></div>`
  ).join("");
}

function renderFilters() {
  const filters = [["all", "全部"], ...Object.entries(KIND).map(([key, val]) => [key, val[1]])];
  document.getElementById("filters").innerHTML = filters.map(([key, label]) =>
    `<button class="filter ${kindFilter === key ? "active" : ""}" data-filter="${key}">${label}</button>`
  ).join("");
}

function noteHtml(note) {
  return `<div class="note">
    <div class="note-head">${esc(NOTE[note.note_type] || note.note_type)} · ${esc(note.captured_on)}${note.title ? ` · ${esc(note.title)}` : ""}</div>
    <div class="note-body">${window.renderMarkdown(note.body || "")}</div>
  </div>`;
}

function prioritySelect(item) {
  return `<select class="priority" data-priority="${esc(item.id)}" title="学习优先级">
    ${["P0", "P1", "P2", "P3"].map((p) => `<option ${p === item.priority ? "selected" : ""}>${p}</option>`).join("")}
  </select>`;
}

function cardHtml(item) {
  const [icon, kindLabel] = KIND[item.kind] || KIND.other;
  const open = expanded.has(item.id);
  const statusButton = item.status === "want"
    ? `<button class="state-btn" data-status="learning" data-id="${esc(item.id)}">开始</button>`
    : item.status === "learning"
      ? `<button class="state-btn done" data-status="learned" data-id="${esc(item.id)}">学完</button>`
      : item.status === "learned"
        ? `<button class="state-btn" data-status="learning" data-id="${esc(item.id)}">重学</button>` : "";
  const meta = [kindLabel, item.creator, item.learned_on ? `学于 ${item.learned_on}` : "",
    item.duration_minutes ? `${item.duration_minutes} 分钟` : "", item.source_url || ""].filter(Boolean).join(" · ");
  const detail = open ? `<div class="detail">
    <div class="overview">${window.renderMarkdown(item.body || "")}</div>
    <div class="notes-title">具体笔记 ${item.notes.length}</div>
    ${item.notes.length ? item.notes.map(noteHtml).join("") : `<div class="empty">还没有笔记</div>`}
    <div class="note-form">
      <select class="note-type" data-note-type="${esc(item.id)}">
        ${Object.entries(NOTE).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}
      </select>
      <textarea class="note-input" data-note-input="${esc(item.id)}" rows="2" placeholder="追加你的理解、思考或疑问…"></textarea>
      <button class="note-save" data-note-save="${esc(item.id)}">保存</button>
    </div>
  </div>` : "";
  return `<article class="card ${esc(item.status)}">
    <div class="card-main" data-expand="${esc(item.id)}">
      <span class="kind">${icon}</span>
      <div class="card-copy"><div class="card-title">${esc(item.title)}</div><div class="card-meta source">${esc(meta)}</div></div>
      ${prioritySelect(item)}${statusButton}
    </div>${detail}
  </article>`;
}

function sectionHtml(title, items) {
  if (!items.length) return "";
  return `<section class="section"><h2 class="section-title">${title} <span class="section-count">${items.length}</span></h2>${items.map(cardHtml).join("")}</section>`;
}

function render() {
  renderStats(); renderFilters();
  const items = (data.items || []).filter((i) => kindFilter === "all" || i.kind === kindFilter);
  const groups = {
    learning: items.filter((i) => i.status === "learning"),
    want: items.filter((i) => i.status === "want"),
    learned: items.filter((i) => i.status === "learned"),
    archived: items.filter((i) => i.status === "archived"),
  };
  const html = sectionHtml("🌱 正在学习", groups.learning) +
    sectionHtml("🧭 想学队列（按优先级）", groups.want) +
    sectionHtml("✨ 已学习", groups.learned) + sectionHtml("归档", groups.archived);
  document.getElementById("knowledge-content").innerHTML = html ||
    `<p class="empty">知识库还是空的。跟管家说“我想看/我刚学完……”即可建立第一条记录。</p>`;
}

document.getElementById("filters").addEventListener("click", (event) => {
  const el = event.target.closest("[data-filter]");
  if (!el) return;
  kindFilter = el.dataset.filter; render();
});

document.getElementById("knowledge-content").addEventListener("click", async (event) => {
  const save = event.target.closest("[data-note-save]");
  if (save) {
    const id = save.dataset.noteSave;
    const input = document.querySelector(`[data-note-input="${id}"]`);
    const type = document.querySelector(`[data-note-type="${id}"]`);
    if (!input.value.trim()) return;
    const res = await window.steward.api("knowledge_add_note", {
      id, content: input.value.trim(), note_type: type.value,
    });
    if (res && res.ok) await loadKnowledge();
    else window.alert("保存笔记失败：" + ((res && res.error) || "未知错误"));
    return;
  }
  const status = event.target.closest("[data-status]");
  if (status) {
    const res = await window.steward.api("knowledge_update", {
      id: status.dataset.id, status: status.dataset.status,
    });
    if (res && res.ok) await loadKnowledge();
    else window.alert("更新学习状态失败：" + ((res && res.error) || "未知错误"));
    return;
  }
  if (event.target.closest("select, textarea, button")) return;
  const expander = event.target.closest("[data-expand]");
  if (expander) {
    const id = expander.dataset.expand;
    expanded.has(id) ? expanded.delete(id) : expanded.add(id);
    render();
  }
});

document.getElementById("knowledge-content").addEventListener("change", async (event) => {
  const select = event.target.closest("[data-priority]");
  if (!select) return;
  const res = await window.steward.api("knowledge_update", {
    id: select.dataset.priority, priority: select.value,
  });
  if (res && res.ok) await loadKnowledge();
  else window.alert("更新优先级失败：" + ((res && res.error) || "未知错误"));
});

document.getElementById("btn-close").addEventListener("click", () => window.steward.closeKnowledge());
loadKnowledge();
