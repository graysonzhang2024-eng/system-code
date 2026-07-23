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

// —— mock 假数据(下一步换成真实 vault 数据)——
// children 可无限嵌套
const MOCK_TASKS = {
  career: [
    { id: "c1", title: "周报提交", done: true, children: [] },
    {
      id: "c2",
      title: "小说创作",
      done: false,
      sensitive: true, // 敏感:折叠时只显示中性三角
      children: [
        { id: "c2-1", title: "写第 12 章大纲", done: false, children: [] },
        {
          id: "c2-2",
          title: "修订第 11 章",
          done: false,
          children: [
            { id: "c2-2-1", title: "改开头对话", done: true, children: [] },
            { id: "c2-2-2", title: "调整节奏", done: false, children: [] },
          ],
        },
      ],
    },
  ],
  study: [
    {
      id: "s1",
      title: "完成 Monarch-MoE 论文 §4 实验章节",
      done: false,
      children: [
        { id: "s1-1", title: "整理 DISCO+Monarch 的收敛曲线数据", done: true, children: [] },
        { id: "s1-2", title: "画 §4.2 的主结果对比图", done: false, children: [] },
        { id: "s1-3", title: "写 §4.3 消融实验分析", done: false, children: [] },
      ],
    },
  ],
  system: [
    {
      id: "y1",
      title: "开发 agent 管家系统",
      done: false,
      children: [
        { id: "y1-1", title: "搭浮窗三层 todo 界面", done: false, children: [] },
        { id: "y1-2", title: "接真实 vault 数据", done: false, children: [] },
      ],
    },
  ],
  social: [],
  life: [],
};

const machineId = window.steward.machineId;

// 折叠状态:记录被折叠的节点/分类 key(内存态)
const collapsed = new Set();
// 敏感项已解锁显示的 key(重启复位=回到隐身)
const revealed = new Set();

// —— 渲染 ——
function render() {
  const content = document.getElementById("content");
  content.innerHTML = "";

  const visibleCats = CATEGORIES.filter((c) => c.machines.includes(machineId));

  for (const cat of visibleCats) {
    const tasks = MOCK_TASKS[cat.key] || [];
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
        for (const node of tasks) {
          list.appendChild(renderNode(cat.key, node, 0));
        }
      }
      catEl.appendChild(list);
    }
    content.appendChild(catEl);
  }
}

// 递归渲染一个节点(任意层级)
function renderNode(catKey, node, depth) {
  const el = document.createElement("div");
  el.className = "node";

  // 敏感节点未解锁:只显示中性三角,不暴露标题
  const revealKey = `reveal:node:${node.id}`;
  if (node.sensitive && !revealed.has(revealKey)) {
    el.innerHTML = `<div class="masked-row" data-reveal="${revealKey}"><span class="tri">▸</span></div>`;
    return el;
  }

  const hasChildren = node.children && node.children.length > 0;
  const nodeCollapsed = collapsed.has(node.id);

  const row = document.createElement("div");
  row.className = "task-row" + (node.done ? " done" : "");
  // 折叠三角(有子节点才显示,否则占位对齐)
  const tri = hasChildren
    ? `<span class="tri small" data-collapse="${node.id}">${nodeCollapsed ? "▸" : "▾"}</span>`
    : `<span class="tri-placeholder"></span>`;
  // 敏感节点已解锁时,行尾给一个"收回隐身"按钮
  const hideBtn = node.sensitive
    ? `<span class="hide-btn" data-hide="${revealKey}" title="收回隐身">⤺</span>`
    : "";
  row.innerHTML = `
    ${tri}
    <span class="checkbox ${node.done ? "checked" : ""}" data-cat="${catKey}" data-id="${node.id}"></span>
    <span class="task-title">${node.title}</span>
    ${hideBtn}
  `;
  el.appendChild(row);

  // 递归渲染子节点(未折叠时)
  if (hasChildren && !nodeCollapsed) {
    const childList = document.createElement("div");
    childList.className = "child-list";
    for (const child of node.children) {
      childList.appendChild(renderNode(catKey, child, depth + 1));
    }
    el.appendChild(childList);
  }

  return el;
}

// 统计(递归):完成数 / 总数
function countAll(nodes) {
  let n = 0;
  for (const x of nodes) {
    n += 1 + countAll(x.children || []);
  }
  return n;
}
function countDone(nodes) {
  let n = 0;
  for (const x of nodes) {
    n += (x.done ? 1 : 0) + countDone(x.children || []);
  }
  return n;
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
  // 1. 展开敏感项
  const revealEl = e.target.closest("[data-reveal]");
  if (revealEl) {
    revealed.add(revealEl.dataset.reveal);
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
  // 3. 勾选框
  const box = e.target.closest(".checkbox");
  if (box) {
    toggle(box.dataset.cat, box.dataset.id);
    render();
  }
});

// 递归查找节点并切换完成态
function toggle(catKey, nodeId) {
  const found = findNode(MOCK_TASKS[catKey] || [], nodeId);
  if (found) found.done = !found.done;
}
function findNode(nodes, id) {
  for (const n of nodes) {
    if (n.id === id) return n;
    const deep = findNode(n.children || [], id);
    if (deep) return deep;
  }
  return null;
}

// —— 窗口按钮 ——
document.getElementById("btn-close").addEventListener("click", () => {
  window.steward.closeWindow();
});
document.getElementById("btn-min").addEventListener("click", () => {
  window.steward.minimizeWindow();
});

render();
