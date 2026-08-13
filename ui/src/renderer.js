// ============================================================
// 界面逻辑(渲染进程)—— 递归无限层级 todo 树
// 结构:分类(category) 下是任务节点(node),节点可无限嵌套 children
// 每个节点:{ id, title, done, sensitive?, collapsed?, children: [] }
// ============================================================

const CATEGORIES = [
  { key: "career", label: "事业", machines: ["work", "personal"] },
  { key: "study", label: "学业", machines: ["work", "personal"] },
  { key: "system", label: "系统", machines: ["work", "personal"] },
  { key: "social", label: "人际", machines: ["personal"], sensitive: true },
  { key: "life", label: "生活", machines: ["personal"] },
];

const AGENT_LABELS = {
  dev_agent: "系统开发",
  internship_agent: "实习攻略",
};

function isAgentExecutor(executor) {
  return !!executor && executor !== "user";
}

function agentLabel(node) {
  return node.agent_label || AGENT_LABELS[node.executor] || node.executor || "Agent";
}

function findTask(taskId) {
  function walk(nodes) {
    for (const node of nodes) {
      if (node.id === taskId) return node;
      const child = walk(node.children || []);
      if (child) return child;
    }
    return null;
  }
  for (const nodes of Object.values(taskData)) {
    const found = walk(nodes || []);
    if (found) return found;
  }
  return null;
}


const machineId = window.steward.machineId;

// —— 北京时间日期工具(过滤已完成任务的显示范围)——
function bjDate(offsetDays = 0) {
  const now = new Date();
  // 转到 UTC+8
  const bj = new Date(now.getTime() + (now.getTimezoneOffset() + 480) * 60000);
  bj.setDate(bj.getDate() + offsetDays);
  return bj.toISOString().slice(0, 10);
}
// 跨天时需重算,故用 let(见底部 0 点检查)
let TODAY = bjDate(0);
let YESTERDAY = bjDate(-1);
function refreshDates() {
  TODAY = bjDate(0);
  YESTERDAY = bjDate(-1);
}

// 折叠状态:记录被折叠的节点/分类 key(内存态)
const collapsed = new Set();
// 敏感项已解锁显示的 key(重启复位=回到隐身)
const revealed = new Set();

// 真实任务数据(从 Python 桥拿),形如 {分类: [任务树]}
let taskData = {};
// 日常任务(打卡制,每天刷新),形如 [{id,title,done_today,...}]
let routineData = [];

// 从桥加载真实数据并重绘。失败时在浮窗顶部提示。
async function loadData() {
  const res = await window.steward.api("tree", { include_done: true });
  if (res && res.ok) {
    taskData = res.data || {};
  } else {
    taskData = {};
    console.error("加载任务失败:", res && res.error);
  }
  const rres = await window.steward.api("routines", {});
  if (rres && rres.ok) {
    routineData = rres.data || [];
  } else {
    routineData = [];
    console.error("加载日常任务失败:", rres && rres.error);
  }
  render();
  updateReviewBadge();
}

// 更新标题栏"待处理"红点(所有已注册 Agent 的三类待处理总数)
async function updateReviewBadge() {
  const badge = document.getElementById("review-badge");
  if (!badge) return;
  const res = await window.steward.api("review_queue", {});
  if (res && res.ok) {
    const q = res.data || {};
    const n = (q.pending_review||[]).length + (q.pending_start||[]).length + (q.pending_decision||[]).length;
    if (n > 0) { badge.textContent = n; badge.style.display = "inline-block"; }
    else { badge.style.display = "none"; }
  }
}

// —— 渲染 ——
function render() {
  const content = document.getElementById("content");
  content.innerHTML = "";

  const visibleCats = CATEGORIES.filter((c) => c.machines.includes(machineId));

  // —— 专注区:跨分类汇总所有 in_progress 任务,置顶显示 ——
  renderFocusZone(content, visibleCats);

  // —— 今日待办:总待办与专注之间的当日缓存层 ——
  renderTodayZone(content, visibleCats);

  // —— 日常任务区:今日待办和总待办之间,默认折叠(点三角展开)——
  renderRoutineZone(content);

  for (const cat of visibleCats) {
    const tasks = taskData[cat.label] || [];
    const catEl = document.createElement("section");
    catEl.className = "category";

    // 敏感整栏:未解锁时只显示一个中性三角(不暴露栏名)
    const catRevealKey = `reveal:cat:${cat.key}`;
    if (cat.sensitive && !revealed.has(catRevealKey)) {
      catEl.innerHTML = `<div class="masked-row" data-reveal="${catRevealKey}"><span class="tri">▸</span></div>`;
      content.appendChild(catEl);
      continue;
    }

    const catCollapseKey = `cat:${cat.key}`;
    const isCollapsed = collapsed.has(catCollapseKey);
    const doneCount = countDone(tasks);
    const total = countAll(tasks);

    const catHideBtn = cat.sensitive
      ? `<span class="hide-btn" data-hide="${catRevealKey}" title="收回隐身">⤺</span>`
      : "";
    const head = document.createElement("h2");
    head.className = "cat-title";
    head.innerHTML = `<span class="tri" data-collapse="${catCollapseKey}">${isCollapsed ? "▸" : "▾"}</span>${cat.label} <span class="cat-count">${doneCount}/${total}</span>${catHideBtn}`;
    catEl.appendChild(head);

    if (!isCollapsed) {
      const list = document.createElement("div");
      list.className = "task-list";
      if (tasks.length === 0) {
        list.innerHTML = `<p class="empty">暂无任务</p>`;
      } else {
        renderChildren(list, cat.key, tasks, -1);
      }
      catEl.appendChild(list);
    }
    content.appendChild(catEl);
  }

  // 待办最底部:全局"昨日完成"大列表(汇总所有分类、所有层级)
  renderYesterdayZone(content, visibleCats);
}

// 收集所有昨天完成的任务(跨分类、递归所有层级),返回 {id -> {catKey, node}}
// —— 日常任务区:打卡制,每天一样、自动刷新 ——
// 默认折叠(用 revealed 语义:每次启动都是收起的,点三角展开本轮);
// 今日已打卡的折叠进栏内"已完成"。打卡历史在记录里,日志会总结。
const ROUTINE_OPEN_KEY = "routine:open";
const ROUTINE_DONE_KEY = "routine:donefold";

function renderRoutineZone(content) {
  const items = routineData || [];
  const zone = document.createElement("section");
  zone.className = "category";

  const open = revealed.has(ROUTINE_OPEN_KEY);
  const undone = items.filter((i) => !i.done_today);
  const doneToday = items.filter((i) => i.done_today);

  const head = document.createElement("h2");
  head.className = "cat-title";
  head.innerHTML = `<span class="tri" data-reveal="${ROUTINE_OPEN_KEY}">${open ? "▾" : "▸"}</span>🔁 日常 <span class="cat-count">${doneToday.length}/${items.length}</span>`;
  zone.appendChild(head);

  if (open) {
    if (items.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "暂无日常任务,跟管家说『记个日常:每天XX』即可";
      zone.appendChild(empty);
    } else {
      for (const i of undone) zone.appendChild(renderRoutineRow(i));
      // 今日已打卡:折叠进栏内"已完成"
      if (doneToday.length > 0) {
        const isOpen = revealed.has(ROUTINE_DONE_KEY);
        const fold = document.createElement("div");
        fold.className = "done-fold";
        fold.dataset.reveal = ROUTINE_DONE_KEY;
        fold.innerHTML = `<span class="tri small">${isOpen ? "▾" : "▸"}</span><span class="done-fold-label">✓ 已完成 ${doneToday.length}</span>`;
        zone.appendChild(fold);
        if (isOpen) {
          for (const i of doneToday) zone.appendChild(renderRoutineRow(i));
        }
      }
    }
  }
  content.appendChild(zone);
}

function renderRoutineRow(item) {
  const row = document.createElement("div");
  row.className = "task-row" + (item.done_today ? " done" : "");
  // 勾选框:0=空 / 中间进度=蓝点 / 打满=绿勾
  const boxCls = item.done_today ? " checked" : (item.today_count > 0 ? " partial" : "");
  // 进度型(target>1)显示 N/M 小标;次数>0 显示 − 精确减一按钮
  const prog = item.target > 1
    ? `<span class="routine-prog">${item.today_count}/${item.target}</span>` : "";
  const minus = item.today_count > 0
    ? `<span class="routine-minus" data-rminus="${item.id}" title="减一次">−</span>` : "";
  row.innerHTML = `<span class="checkbox${boxCls}" data-routine="${item.id}"></span><span class="task-title">${item.title}</span>${prog}${minus}`;
  return row;
}

function collectYesterday(visibleCats) {
  const map = new Map();
  function walk(catKey, nodes) {
    for (const n of nodes) {
      // 常驻容器永远显示在原位,不进昨日完成区(其子任务照常进)
      if (n.done && n.done_date === YESTERDAY && !n.standing) map.set(n.id, { catKey, node: n });
      walk(catKey, n.children || []);
    }
  }
  for (const cat of visibleCats) {
    if (cat.sensitive && !revealed.has(`reveal:cat:${cat.key}`)) continue;
    walk(cat.key, taskData[cat.label] || []);
  }
  return map;
}

// 渲染全局"昨日完成"区(默认折叠,放最底部)——保留父子树结构
function renderYesterdayZone(content, visibleCats) {
  const map = collectYesterday(visibleCats);
  if (map.size === 0) return;

  // 重建剪枝树:昨日完成节点若其父也在集合里 → 挂父下;否则提为顶层
  const shadow = new Map(); // id -> {catKey, node, kids:[]}
  for (const [id, { catKey, node }] of map) {
    shadow.set(id, { catKey, node, kids: [] });
  }
  const roots = [];
  for (const [id, s] of shadow) {
    const pid = s.node.parent;
    if (pid && shadow.has(pid)) shadow.get(pid).kids.push(s);
    else roots.push(s);
  }

  const key = "done:yesterday:global";
  const isOpen = revealed.has(key);
  const zone = document.createElement("section");
  zone.className = "yesterday-zone";
  const head = document.createElement("div");
  head.className = "done-fold";
  head.dataset.reveal = key;
  head.innerHTML = `<span class="tri small">${isOpen ? "▾" : "▸"}</span><span class="done-fold-label">🕐 昨日完成 ${map.size}</span>`;
  zone.appendChild(head);

  if (isOpen) {
    const renderYNode = (s, container) => {
      const el = document.createElement("div");
      el.className = "node";
      const row = document.createElement("div");
      row.className = "task-row done";
      row.innerHTML = `
        <span class="checkbox checked" data-cat="${s.catKey}" data-id="${s.node.id}"></span>
        <span class="task-title">${s.node.title}</span>
      `;
      el.appendChild(row);
      if (s.kids.length > 0) {
        const childList = document.createElement("div");
        childList.className = "child-list";
        for (const k of s.kids) renderYNode(k, childList);
        el.appendChild(childList);
      }
      container.appendChild(el);
    };
    // 按分类(事业/学业/系统…)分组,每组一个小标题,组内再是父子树
    for (const cat of visibleCats) {
      const catRoots = roots.filter((r) => r.catKey === cat.key);
      if (catRoots.length === 0) continue;
      const catHead = document.createElement("div");
      catHead.className = "yest-cat";
      catHead.textContent = cat.label;
      zone.appendChild(catHead);
      for (const r of catRoots) renderYNode(r, zone);
    }
  }
  content.appendChild(zone);
}

// 收集专注区任务(跨分类,递归)。
//   你的任务:in_progress 叶子 → "我在推进"
//   Agent任务:in_progress / pending_review / pending_decision 全程 → 各自专项栏
//   pending_start(待开始)不进专注区,留在待办区等你批准。
function collectFocus(visibleCats) {
  const out = [];
  function walk(catKey, nodes) {
    for (const n of nodes) {
      const isLeaf = !n.children || n.children.length === 0;
      const isAgent = isAgentExecutor(n.executor || "user");
      if (isAgent) {
        // Agent 负责的任务:整个生命周期(执行中/待验收/待决策)都留在专注区
        if (["in_progress", "pending_review", "pending_decision"].includes(n.status)) {
          out.push({ catKey, node: n });
        }
      } else {
        // 你自己的任务:只有 in_progress 叶子进专注区
        if (n.status === "in_progress" && !n.done && isLeaf) {
          out.push({ catKey, node: n });
        }
      }
      walk(catKey, n.children || []);
    }
  }
  for (const cat of visibleCats) {
    // 敏感栏未解锁时不纳入专注区,避免泄露
    if (cat.sensitive && !revealed.has(`reveal:cat:${cat.key}`)) continue;
    walk(cat.key, taskData[cat.label] || []);
  }
  return out;
}

// 收集今日缓存中的用户叶子任务。过期 today_date 不改文件，次日自动回到总待办。
function collectToday(visibleCats) {
  const out = [];
  function walk(catKey, nodes) {
    for (const n of nodes) {
      const isLeaf = !n.children || n.children.length === 0;
      if (!isAgentExecutor(n.executor || "user") && n.status === "todo" &&
          !n.done && isLeaf && n.today_date === TODAY) {
        out.push({ catKey, node: n });
      }
      walk(catKey, n.children || []);
    }
  }
  for (const cat of visibleCats) {
    if (cat.sensitive && !revealed.has(`reveal:cat:${cat.key}`)) continue;
    walk(cat.key, taskData[cat.label] || []);
  }
  out.sort((a, b) => (a.node.priority || "P9").localeCompare(b.node.priority || "P9"));
  return out;
}

function renderTodayZone(content, visibleCats) {
  const items = collectToday(visibleCats);
  const zone = document.createElement("section");
  zone.className = "today-zone";
  const head = document.createElement("h2");
  head.className = "today-title";
  head.innerHTML = `📌 今日待办 <span class="cat-count">${items.length}</span>`;
  zone.appendChild(head);

  if (items.length === 0) {
    const tip = document.createElement("p");
    tip.className = "today-empty";
    tip.textContent = "点普通待办右侧 ☆ 加入今天";
    zone.appendChild(tip);
  } else {
    for (const { catKey, node } of items) {
      const row = document.createElement("div");
      row.className = "task-row today-row";
      const prio = node.priority || "P2";
      row.innerHTML = `
        <span class="checkbox" data-cat="${catKey}" data-id="${node.id}"></span>
        <span class="prio prio-${prio}">${prio}</span>
        <span class="task-title">${node.title}</span>
        <span class="layer-action promote" data-layer="focus" data-id="${node.id}" title="进入专注">▶</span>
        <span class="layer-action remove" data-layer="backlog" data-id="${node.id}" title="移出今日待办">×</span>
      `;
      zone.appendChild(row);
    }
  }
  content.appendChild(zone);
}

// 渲染专注区(置顶)—— 用户一栏 + 每种 Agent 各自一栏
function renderFocusZone(content, visibleCats) {
  const focus = collectFocus(visibleCats);
  const mine = focus.filter((f) => !isAgentExecutor(f.node.executor || "user"));
  const agentGroups = new Map();
  for (const item of focus.filter((f) => isAgentExecutor(f.node.executor || "user"))) {
    const executor = item.node.executor;
    if (!agentGroups.has(executor)) agentGroups.set(executor, []);
    agentGroups.get(executor).push(item);
  }

  const zone = document.createElement("section");
  zone.className = "focus-zone";
  const head = document.createElement("h2");
  head.className = "focus-title";
  head.innerHTML = `🎯 专注中 <span class="cat-count">${focus.length}</span>`;
  zone.appendChild(head);

  if (focus.length === 0) {
    const tip = document.createElement("p");
    tip.className = "focus-empty";
    tip.textContent = "从今日待办点 ▶ 进入专注";
    zone.appendChild(tip);
    content.appendChild(zone);
    return;
  }

  // 我的栏
  const mineHead = document.createElement("div");
  mineHead.className = "focus-sub";
  mineHead.textContent = `我在推进 ${mine.length}`;
  zone.appendChild(mineHead);
  for (const { catKey, node } of mine) zone.appendChild(renderFocusRow(catKey, node));

  // 每个 Agent 独立成栏,避免把专项任务误标成系统开发
  for (const [executor, items] of agentGroups) {
    const agentHead = document.createElement("div");
    agentHead.className = "focus-sub agent";
    const icon = executor === "internship_agent" ? "🎓" : "🤖";
    agentHead.textContent = `${icon} ${agentLabel(items[0].node)} ${items.length}`;
    zone.appendChild(agentHead);
    for (const { catKey, node } of items) zone.appendChild(renderFocusRow(catKey, node));
  }
  content.appendChild(zone);
}

// 专注区里的单行(镜像,精简版)
function renderFocusRow(catKey, node) {
  const el = document.createElement("div");
  const st = node.status;
  const agentTask = isAgentExecutor(node.executor || "user");
  const stClass = st === "pending_review" ? "st-review-row" : st === "pending_decision" ? "st-decision-row" : "in-progress";
  el.className = "task-row focus-row " + stClass;
  const prio = node.priority || "P2";
  const tail = st === "pending_review"
    ? `<span class="st-badge st-review" title="做完了,等你验收">待验收</span>`
    : st === "pending_decision"
    ? `<span class="st-badge st-decision" title="等你决策">待决策</span>`
    : agentTask
    ? `<span class="st-badge st-start" title="由 ${agentLabel(node)} 通过审核流程推进">执行中</span>`
    : `<span class="star on" data-layer="today" data-id="${node.id}" title="退回今日待办">★</span>`;
  const checkbox = agentTask && !node.done
    ? `<span class="checkbox agent-takeover" role="button" tabindex="0" aria-label="接管并完成 Agent 任务" data-agent-complete="${node.id}" title="点击后确认由你接管并完成"></span>`
    : agentTask
    ? `<span class="checkbox checked" title="已验收的 Agent 任务不能用普通勾选撤销"></span>`
    : `<span class="checkbox ${node.done ? "checked" : ""}" data-cat="${catKey}" data-id="${node.id}"></span>`;
  el.innerHTML = `
    ${checkbox}
    <span class="prio prio-${prio}">${prio}</span>
    <span class="task-title">${node.title}</span>
    ${tail}
  `;
  return el;
}

// 递归渲染一个节点(任意层级)
// inSensitive:祖先里有敏感节点 —— 遮罩继承规则:最外层敏感节点遮住整棵子树,
// 展开它后子树正常显示,子孙不再各自加遮罩(避免"连点三层三角"套娃)
function renderNode(catKey, node, depth, inSensitive) {
  const el = document.createElement("div");
  el.className = "node";

  // 敏感节点未解锁:只显示中性三角,不暴露标题
  const revealKey = `reveal:node:${node.id}`;
  if (node.sensitive && !inSensitive && !revealed.has(revealKey)) {
    el.innerHTML = `<div class="masked-row" data-reveal="${revealKey}"><span class="tri">▸</span></div>`;
    return el;
  }

  const hasChildren = node.children && node.children.length > 0;
  const nodeCollapsed = collapsed.has(node.id);

  // 依赖是否满足:有未完成的依赖 → 阻塞(不可执行,但仍可勾选)
  const deps = node.depends_on || [];
  const blocked = deps.some((id) => !isDone(id));

  const row = document.createElement("div");
  const statusCls = node.status === "in_progress" ? " in-progress" : "";
  const blockedCls = blocked ? " blocked-task" : "";
  row.className = "task-row" + (node.done ? " done" : "") + statusCls + blockedCls;
  // 折叠三角(有子节点才显示,否则占位对齐)
  const tri = hasChildren
    ? `<span class="tri small" data-collapse="${node.id}">${nodeCollapsed ? "▸" : "▾"}</span>`
    : `<span class="tri-placeholder"></span>`;
  // 敏感节点已解锁时,行尾给一个"收回隐身"按钮(子孙不重复给)
  const hideBtn = node.sensitive && !inSensitive
    ? `<span class="hide-btn" data-hide="${revealKey}" title="收回隐身">⤺</span>`
    : "";

  // 优先级徽章(P0 最高)
  const prio = node.priority || "P2";
  const prioBadge = `<span class="prio prio-${prio}">${prio}</span>`;

  // 进度:有子任务时显示 已完成/总数
  let progress = "";
  if (hasChildren) {
    const done = countDone(node.children);
    const total = countAll(node.children);
    progress = `<span class="progress" title="子任务进度">${done}/${total}</span>`;
  }

  // 阻塞任务:显示小锁,悬停可看依赖谁(不占大空间)
  const blockBadge = blocked
    ? `<span class="dep-lock" title="等待依赖完成:${deps.join(", ")}">🔒排队</span>`
    : "";

  // 开发协作流程状态徽章
  const STATUS_BADGE = {
    pending_start: { cls: "st-start", txt: "待开始", tip: "agent 提议做这个,等你批准" },
    pending_decision: { cls: "st-decide", txt: "待决策", tip: node.decision_needed || "等你决策" },
    pending_review: { cls: "st-review", txt: "待验收", tip: node.review_note || "agent 做完了,等你验收" },
  };
  const sb = STATUS_BADGE[node.status];
  const statusBadge = sb ? `<span class="st-badge ${sb.cls}" title="${sb.tip}">${sb.txt}</span>` : "";

  // 星标把普通叶子任务加入今日待办；再由今日待办显式进入专注。
  // 只有叶子任务显示——工作记忆层只放具体在干的最小任务。
  // Agent 不能自行绕过状态机；用户可点击勾选框，经二次确认后中途接管并完成。
  const agentTask = isAgentExecutor(node.executor || "user");
  const starBtn = (node.done || hasChildren || agentTask)
    ? ""
    : `<span class="star" data-layer="today" data-id="${node.id}" title="加入今日待办">☆</span>`;
  const checkbox = agentTask && !node.done
    ? `<span class="checkbox agent-takeover" role="button" tabindex="0" aria-label="接管并完成 Agent 任务" data-agent-complete="${node.id}" title="点击后确认由你接管并完成"></span>`
    : agentTask
    ? `<span class="checkbox checked" title="已验收的 Agent 任务不能用普通勾选撤销"></span>`
    : `<span class="checkbox ${node.done ? "checked" : ""}" data-cat="${catKey}" data-id="${node.id}"></span>`;

  row.innerHTML = `
    ${tri}
    ${checkbox}
    ${prioBadge}
    <span class="task-title">${node.title}</span>
    ${statusBadge}
    ${progress}
    ${blockBadge}
    ${starBtn}
    ${hideBtn}
  `;
  el.appendChild(row);

  // 递归渲染子节点(未折叠时);敏感状态向子孙传递
  if (hasChildren && !nodeCollapsed) {
    const childList = document.createElement("div");
    childList.className = "child-list";
    renderChildren(childList, catKey, node.children, depth, inSensitive || !!node.sensitive);
    el.appendChild(childList);
  }

  return el;
}

// 专注中的任务只在专注栏显示，避免与总待办重复。
function isInFocusZone(c) {
  if (isAgentExecutor(c.executor || "user")) {
    return ["in_progress", "pending_review", "pending_decision"].includes(c.status);
  }
  return c.status === "in_progress" && !c.done &&
    (!c.children || c.children.length === 0);
}

function isInTodayZone(c) {
  return !isAgentExecutor(c.executor || "user") && c.status === "todo" &&
    !c.done && c.today_date === TODAY && (!c.children || c.children.length === 0);
}

// 渲染一组子节点:未完成在前(可执行优先、阻塞排队),已完成折叠到底部
function renderChildren(container, catKey, children, depth, inSensitive = false) {
  // 常驻任务(standing):容器/固定分区性质,永远显示在原位置,
  // 不参与"已完成折叠/昨日完成区/按日期隐藏"——子任务全完成它也在。
  const standing = children.filter((c) => c.standing);
  const undone = children.filter((c) => !c.standing && !c.done &&
    !isInFocusZone(c) && !isInTodayZone(c));
  const done = children.filter((c) => !c.standing && c.done);

  // 常驻置顶,按优先级
  standing.sort((a, b) => (a.priority || "P9").localeCompare(b.priority || "P9"));
  for (const s of standing) {
    container.appendChild(renderNode(catKey, s, depth + 1, inSensitive));
  }

  // 未完成排序:可执行(依赖满足)在前,阻塞排队在后;同组按优先级
  undone.sort((a, b) => {
    const ba = (a.depends_on || []).some((id) => !isDone(id)) ? 1 : 0;
    const bb = (b.depends_on || []).some((id) => !isDone(id)) ? 1 : 0;
    if (ba !== bb) return ba - bb; // 不阻塞的在前
    return (a.priority || "P9").localeCompare(b.priority || "P9");
  });

  for (const child of undone) {
    container.appendChild(renderNode(catKey, child, depth + 1, inSensitive));
  }

  // 已完成:只处理"今天完成"(就地折叠在父任务下)。
  //   昨天完成 → 汇总到全局大列表(见 renderYesterdayZone),放待办最底部;
  //   前天及更早 → 不显示(文件仍保留)。
  const doneToday = done.filter((c) => c.done_date === TODAY);
  if (doneToday.length > 0) {
    appendFoldGroup(container, catKey, depth, children[0].id, "today",
      `✓ 已完成 ${doneToday.length}`, doneToday, inSensitive);
  }
}

// 渲染一个可折叠的已完成分组
function appendFoldGroup(container, catKey, depth, anchorId, tag, label, items, inSensitive = false) {
  const key = `done:${tag}:${catKey}:${depth}:${anchorId}`;
  const isOpen = revealed.has(key);
  const foldHead = document.createElement("div");
  foldHead.className = "done-fold";
  foldHead.dataset.reveal = key;
  foldHead.innerHTML = `<span class="tri small">${isOpen ? "▾" : "▸"}</span><span class="done-fold-label">${label}</span>`;
  container.appendChild(foldHead);
  if (isOpen) {
    for (const child of items) {
      container.appendChild(renderNode(catKey, child, depth + 1, inSensitive));
    }
  }
}

// 统计(递归)—— 进度只算"今日"口径:
//   历史完成(昨天及更早完成)既不进分母也不进分子;
//   分母 = 未完成 + 今天完成的;分子 = 今天完成的。
function isHistoryDone(x) {
  return x.done && x.done_date !== TODAY; // 已完成且不是今天完成 = 历史完成
}
function countAll(nodes) {
  let n = 0;
  for (const x of nodes) {
    n += (isHistoryDone(x) ? 0 : 1) + countAll(x.children || []);
  }
  return n;
}
function countDone(nodes) {
  let n = 0;
  for (const x of nodes) {
    n += (x.done && x.done_date === TODAY ? 1 : 0) + countDone(x.children || []);
  }
  return n;
}

// 按 id 在整棵树里查任务是否已完成(供依赖阻塞判断)
function isDone(taskId) {
  function walk(nodes) {
    for (const n of nodes) {
      if (n.id === taskId) return n.done;
      const r = walk(n.children || []);
      if (r !== null) return r;
    }
    return null;
  }
  for (const cat of Object.keys(taskData)) {
    const r = walk(taskData[cat] || []);
    if (r !== null) return r;
  }
  return true; // 找不到依赖任务时,默认视为已就绪(不误报阻塞)
}

// —— 点击交互 ——
document.getElementById("content").addEventListener("click", (e) => {
  // 0. 收回隐身(敏感项已解锁 → 点按钮变回中性三角)
  const hideEl = e.target.closest("[data-hide]");
  if (hideEl) {
    revealed.delete(hideEl.dataset.hide);
    render();
    return;
  }
  // 1. 展开/收起(敏感项和已完成折叠都走这个)
  const revealEl = e.target.closest("[data-reveal]");
  if (revealEl) {
    const key = revealEl.dataset.reveal;
    revealed.has(key) ? revealed.delete(key) : revealed.add(key);
    render();
    return;
  }
  // 2. 折叠/展开三角
  const collapseEl = e.target.closest("[data-collapse]");
  if (collapseEl) {
    const key = collapseEl.dataset.collapse;
    collapsed.has(key) ? collapsed.delete(key) : collapsed.add(key);
    render();
    return;
  }
  // 3. 用户任务三层流转:总待办 / 今日待办 / 专注中
  const layerEl = e.target.closest("[data-layer]");
  if (layerEl) {
    setTaskLayer(layerEl.dataset.id, layerEl.dataset.layer);
    return;
  }
  // 3.4 日常任务 − 按钮:精确减一次打卡
  const rminusEl = e.target.closest("[data-rminus]");
  if (rminusEl) {
    punchRoutine(rminusEl.dataset.rminus, -1);
    return;
  }
  // 3.5 日常任务打卡 —— 循环:+1,满了再点清零
  const routineEl = e.target.closest("[data-routine]");
  if (routineEl) {
    toggleRoutine(routineEl.dataset.routine);
    return;
  }
  // 3.8 用户接管 Agent 任务：必须二次确认，不能走普通 toggle 绕过。
  const agentCompleteEl = e.target.closest("[data-agent-complete]");
  if (agentCompleteEl) {
    takeOverAgentTask(agentCompleteEl.dataset.agentComplete);
    return;
  }
  // 4. 勾选框 —— 调桥写回文件,再重新加载
  const box = e.target.closest(".checkbox");
  if (box) {
    toggleDone(box.dataset.id);
  }
});

document.getElementById("content").addEventListener("keydown", (e) => {
  const takeover = e.target.closest("[data-agent-complete]");
  if (takeover && (e.key === "Enter" || e.key === " ")) {
    e.preventDefault();
    takeover.click();
  }
});

// 显式调整用户任务层级，写回后刷新
async function setTaskLayer(nodeId, layer) {
  const res = await window.steward.api("set_layer", { id: nodeId, layer });
  if (res && res.ok) {
    await loadData();
  } else {
    console.error("任务层级切换失败:", res && res.error);
    window.alert("调整任务位置失败：" + ((res && res.error) || "未知错误"));
  }
}

async function takeOverAgentTask(nodeId) {
  const node = findTask(nodeId);
  if (!node) {
    window.alert("找不到这条任务，请刷新浮窗后重试。");
    return;
  }
  const ok = window.confirm(
    `确认由你接管并完成「${node.title}」吗？\n\n` +
    `原执行者：${agentLabel(node)}。确认后会生成完成记录，并从 Agent 专注区移出。`
  );
  if (!ok) return;
  const res = await window.steward.api("agent_takeover_complete", {
    id: nodeId, confirmed_by_user: true,
  });
  if (res && res.ok) {
    await loadData();
  } else {
    window.alert("接管完成失败：" + ((res && res.error) || "未知错误"));
  }
}

// 勾选:通过桥切换完成状态(写回 .md 文件),成功后刷新
async function toggleDone(nodeId) {
  const res = await window.steward.api("toggle", { id: nodeId });
  if (res && res.ok) {
    await loadData();
  } else {
    console.error("勾选失败:", res && res.error);
    window.alert("完成任务失败：" + ((res && res.error) || "未知错误"));
  }
}

// 日常任务:循环打卡(没满+1,满了清零),写回 done_log 后刷新
async function toggleRoutine(routineId) {
  const res = await window.steward.api("routine_toggle", { id: routineId });
  if (res && res.ok) {
    await loadData();
  } else {
    console.error("打卡失败:", res && res.error);
  }
}

// 日常任务:精确加减一次(− 按钮),刷新
async function punchRoutine(routineId, delta) {
  const res = await window.steward.api("routine_punch", { id: routineId, delta });
  if (res && res.ok) {
    await loadData();
  } else {
    console.error("打卡调整失败:", res && res.error);
  }
}

// —— 窗口按钮 ——
document.getElementById("btn-knowledge").addEventListener("click", () => {
  window.steward.openKnowledge();
});
document.getElementById("btn-review").addEventListener("click", () => {
  window.steward.openReview();
});
document.getElementById("btn-close").addEventListener("click", () => {
  window.steward.closeWindow();
});
document.getElementById("btn-min").addEventListener("click", () => {
  window.steward.minimizeWindow();
});

// 启动:先补偿遗漏的每日日志(兼容关机跨天),再加载数据
async function boot() {
  try {
    await window.steward.api("catchup", {});
  } catch (e) {
    console.error("补偿日志失败:", e);
  }
  await loadData();
  updateSyncBanner();
}

// 同步冲突红条:另一台机改了同一条记录(merge 保双份),提醒人工合并
async function updateSyncBanner() {
  const el = document.getElementById("sync-banner");
  if (!el) return;
  try {
    const res = await window.steward.api("list_conflicts", {});
    const files = (res && res.ok && res.data) || [];
    if (files.length > 0) {
      el.textContent = `⚠️ ${files.length} 个同步冲突待合并:另一台机改动了同一条记录,已保双份(见 .conflict- 副本)`;
      el.style.display = "block";
    } else {
      el.style.display = "none";
    }
  } catch (e) {
    console.error("冲突检查失败:", e);
  }
}

boot();
setInterval(loadData, 5000);
setInterval(updateSyncBanner, 30000); // 冲突检查不用太勤,30秒一次

// 每天北京时间 0 点:生成昨天的日志 + 刷新(浮窗开着时即时生成)
let lastDay = TODAY;
setInterval(async () => {
  const now = bjDate(0);
  if (now !== lastDay) {
    lastDay = now;
    refreshDates(); // 跨天:重算 TODAY/YESTERDAY,昨日完成区随之滚动
    try {
      await window.steward.api("catchup", {});
    } catch (e) {
      console.error("0点补偿失败:", e);
    }
    await loadData();
  }
}, 60000); // 每分钟检查一次是否跨天
