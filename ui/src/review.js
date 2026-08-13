// 验收弹窗逻辑:汇总所有 Agent,渲染三类待处理任务,点按处理(可选输入原因)
// 复用同一个 os:api 桥(不绑任何模型,可移植)

document.getElementById("btn-close").addEventListener("click", () => {
  window.steward.closeReview();
});

async function load() {
  const content = document.getElementById("content");
  const res = await window.steward.api("review_queue", {});
  if (!res || !res.ok) {
    content.innerHTML = `<p class="empty">读取失败:${res && res.error}</p>`;
    return;
  }
  const q = res.data || {};
  const review = q.pending_review || [];
  const start = q.pending_start || [];
  const decide = q.pending_decision || [];

  if (review.length + start.length + decide.length === 0) {
    content.innerHTML = `<p class="empty">✓ 没有待处理的任务</p>`;
    return;
  }
  content.innerHTML = "";

  // 待验收:通过 / 打回
  if (review.length) {
    content.appendChild(groupTitle("g-review", `待验收 ${review.length}`));
    for (const t of review) content.appendChild(card(t, "review"));
  }
  // 待开始:批准 / 拒绝
  if (start.length) {
    content.appendChild(groupTitle("g-start", `待批准开始 ${start.length}`));
    for (const t of start) content.appendChild(card(t, "start"));
  }
  // 待决策:提交答复
  if (decide.length) {
    content.appendChild(groupTitle("g-decide", `待决策 ${decide.length}`));
    for (const t of decide) content.appendChild(card(t, "decide"));
  }
}

function groupTitle(cls, text) {
  const el = document.createElement("div");
  el.className = "group-title " + cls;
  el.textContent = text;
  return el;
}

// 一个任务卡片。kind: review / start / decide
function card(task, kind) {
  const el = document.createElement("div");
  el.className = "card";

  const cfg = {
    review: { ok: "通过", no: "打回", placeholder: "打回原因(可选)" },
    start:  { ok: "批准", no: "拒绝", placeholder: "拒绝/调整说明(可选)" },
    decide: { ok: "提交", no: null,   placeholder: "你的答复…" },
  }[kind];

  const prog = task.progress ? `<span class="card-prog">${task.progress}</span>` : "";
  const note = task.note ? `<div class="card-note">📝 ${escapeHtml(task.note)}</div>` : "";
  const detail = task.detail
    ? `<div class="card-detail">${renderMarkdown(task.detail)}</div>` : "";
  const agent = task.agent_label ? `<span class="card-agent">${escapeHtml(task.agent_label)}</span>` : "";
  el.innerHTML = `
    <div class="card-title">${agent}${escapeHtml(task.title)} ${prog}</div>
    ${note}
    ${detail}
    <textarea class="card-input" placeholder="${cfg.placeholder}"></textarea>
    <div class="btns">
      <button class="btn btn-ok">${cfg.ok}</button>
      ${cfg.no ? `<button class="btn btn-no">${cfg.no}</button>` : ""}
    </div>
  `;

  const input = el.querySelector(".card-input");
  const okBtn = el.querySelector(".btn-ok");
  const noBtn = el.querySelector(".btn-no");

  okBtn.addEventListener("click", () => act(kind, "ok", task.id, task.executor, input.value.trim()));
  if (noBtn) noBtn.addEventListener("click", () => act(kind, "no", task.id, task.executor, input.value.trim()));

  return el;
}

// 执行处理:映射到桥命令
async function act(kind, choice, id, executor, text) {
  let cmd, arg = { id, executor };
  if (kind === "review") {
    if (choice === "ok") { cmd = "agent_accept"; }
    else { cmd = "agent_reject_review"; arg.reason = text; }
  } else if (kind === "start") {
    if (choice === "ok") { cmd = "agent_approve"; }
    else { cmd = "agent_reject_start"; arg.reason = text; }
  } else if (kind === "decide") {
    cmd = "agent_answer_decision"; arg.answer = text;
  }
  const res = await window.steward.api(cmd, arg);
  if (res && res.ok) {
    load(); // 处理完刷新列表
  } else {
    alert("操作失败:" + (res && res.error));
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

load();
