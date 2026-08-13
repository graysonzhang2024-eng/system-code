// Electron 主进程:创建常驻桌面角落的半透明浮窗
const { app, BrowserWindow, screen, ipcMain, Tray, Menu, nativeImage, globalShortcut } = require("electron");
const path = require("path");
const fs = require("fs");
const { execFile } = require("child_process");

// 框架仓根目录(ui/ 的上一级)
const REPO_ROOT = path.join(__dirname, "..", "..");

// 调用 Python 桥 os_api.py,返回解析后的 JSON
// timeoutMs:sync 等网络操作给 30s,普通命令默认 10s
function callPythonApi(cmd, arg, timeoutMs) {
  return new Promise((resolve) => {
    execFile(
      "python3",
      ["-m", "system_os.os_api", cmd, JSON.stringify(arg || {})],
      { cwd: REPO_ROOT, timeout: timeoutMs || 10000 },
      (err, stdout, stderr) => {
        if (err) {
          resolve({ ok: false, error: String(stderr || err.message) });
          return;
        }
        try {
          resolve(JSON.parse(stdout.trim()));
        } catch (e) {
          resolve({ ok: false, error: "解析返回失败: " + stdout });
        }
      }
    );
  });
}

let win = null;
let tray = null;

// 从框架仓根目录的 .env 读取 MACHINE_ID(work / personal)
function readMachineId() {
  try {
    const envPath = path.join(__dirname, "..", "..", ".env");
    const text = fs.readFileSync(envPath, "utf-8");
    const m = text.match(/^MACHINE_ID=(.+)$/m);
    if (m) return m[1].trim();
  } catch (_) {}
  return "work";
}
process.env.MACHINE_ID = readMachineId();

function createWindow() {
  const { workArea } = screen.getPrimaryDisplay();
  const winWidth = 340;
  const winHeight = 520;
  const margin = 16;

  win = new BrowserWindow({
    width: winWidth,
    height: winHeight,
    // 停靠在屏幕右上角
    x: workArea.x + workArea.width - winWidth - margin,
    y: workArea.y + margin,
    frame: false, // 无系统边框,自己画
    transparent: true, // 背景透明,做浮窗质感
    alwaysOnTop: true, // 常驻置顶
    resizable: true,
    skipTaskbar: false, // 在程序坞显示图标,方便点击唤回(Mac 用户习惯的位置)
    hasShadow: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadFile(path.join(__dirname, "index.html"));

  // 让浮窗浮在所有普通窗口之上(含全屏应用之上一层)
  win.setAlwaysOnTop(true, "floating");
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
}

// 显示/唤出浮窗(不存在则重建,存在则显示并聚焦)
function showWindow() {
  if (!win || win.isDestroyed()) {
    createWindow();
  } else {
    win.show();
    win.focus();
  }
}

// 验收弹窗(独立窗口,不绑任何模型;复用同一个 os:api 桥)
let reviewWin = null;
function openReviewWindow() {
  if (reviewWin && !reviewWin.isDestroyed()) {
    reviewWin.show();
    reviewWin.focus();
    return;
  }
  const { workArea } = screen.getPrimaryDisplay();
  const w = 420, h = 520;
  reviewWin = new BrowserWindow({
    width: w,
    height: h,
    x: workArea.x + Math.floor((workArea.width - w) / 2),
    y: workArea.y + Math.floor((workArea.height - h) / 2),
    frame: false,
    transparent: true,
    resizable: true,
    skipTaskbar: true,
    hasShadow: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  reviewWin.loadFile(path.join(__dirname, "review.html"));
  reviewWin.setAlwaysOnTop(true, "floating");
}

// 浮窗请求打开验收弹窗
ipcMain.on("review:open", () => openReviewWindow());
// 验收弹窗请求关闭自己
ipcMain.on("review:close", () => {
  if (reviewWin && !reviewWin.isDestroyed()) reviewWin.close();
});

// 知识库窗口：学习队列、成长统计和具体笔记独立于任务浮窗。
let knowledgeWin = null;
function openKnowledgeWindow() {
  if (knowledgeWin && !knowledgeWin.isDestroyed()) {
    knowledgeWin.show();
    knowledgeWin.focus();
    return;
  }
  const { workArea } = screen.getPrimaryDisplay();
  const w = 680, h = 720;
  knowledgeWin = new BrowserWindow({
    width: w,
    height: h,
    // 普通功能窗口靠右打开且不强制置顶，避免遮挡用户正在看的视频/主工作区。
    x: workArea.x + workArea.width - w - 24,
    y: workArea.y + 24,
    frame: false,
    transparent: true,
    resizable: true,
    skipTaskbar: false,
    hasShadow: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  knowledgeWin.loadFile(path.join(__dirname, "knowledge.html"));
}
ipcMain.on("knowledge:open", () => openKnowledgeWindow());
ipcMain.on("knowledge:close", () => {
  if (knowledgeWin && !knowledgeWin.isDestroyed()) knowledgeWin.close();
});

// 生成一个简单的菜单栏图标(纯代码,避免依赖图片文件)
function buildTrayIcon() {
  // 彩色实心圆点(非 template),保证在深浅色菜单栏都清晰可见
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22">
    <circle cx="11" cy="11" r="8" fill="#4a9eff"/>
    <circle cx="11" cy="11" r="3" fill="white"/>
  </svg>`;
  const img = nativeImage.createFromDataURL(
    "data:image/svg+xml;base64," + Buffer.from(svg).toString("base64")
  );
  return img;
}

function createTray() {
  tray = new Tray(buildTrayIcon());
  tray.setToolTip("Steward 管家");
  const menu = Menu.buildFromTemplate([
    { label: "显示浮窗", click: () => showWindow() },
    { type: "separator" },
    { label: "退出", click: () => app.quit() },
  ]);
  tray.setContextMenu(menu);
  // 左键点击图标直接唤出浮窗
  tray.on("click", () => showWindow());
}

// 渲染进程请求关闭窗口 —— 隐藏而非销毁,方便从菜单栏重新唤出
ipcMain.on("window:close", () => {
  if (win) win.hide();
});

// 渲染进程请求最小化 —— 用真正的 minimize(缩进程序坞,有动画看得见去向)
ipcMain.on("window:minimize", () => {
  if (win) win.minimize();
});

// 前端调用 Python 桥
ipcMain.handle("os:api", (_evt, cmd, arg) => callPythonApi(cmd, arg));

app.whenReady().then(() => {
  createWindow();
  try {
    createTray();
    console.log("[tray] 托盘图标已创建");
  } catch (err) {
    console.error("[tray] 托盘创建失败:", err);
  }
  // 全局快捷键:无论托盘/dock 图标是否可见,一定能唤回浮窗
  const ok = globalShortcut.register("CommandOrControl+Shift+S", () => showWindow());
  console.log(ok ? "[hotkey] Cmd+Shift+S 已注册" : "[hotkey] 注册失败");

  // 双机同步:启动 8 秒后先同步一轮(拉对方机的改动),
  // 之后每 2 分钟自动同步一轮(commit 本地 + merge 远端 + push)。
  // 写操作本身的即时同步由 Python 端"写入即同步"负责,这里是兜底+下拉。
  const syncOnce = () => {
    callPythonApi("sync", {}, 30000).then((res) => {
      if (res && res.ok && res.data && res.data.conflicts && res.data.conflicts.length) {
        console.log("[sync] 发现冲突副本:", res.data.conflicts);
      } else if (res && res.data && res.data.error && res.data.error !== "not-a-git-repo") {
        console.log("[sync]", res.data.error);
      }
    });
  };
  setTimeout(syncOnce, 8000);
  setInterval(syncOnce, 120000);

  // 框架仓(system-code)自动更新:启动 5 秒首查,之后每 30 分钟一轮。
  // 生效方式:python 改动即时生效(每次调用都起新进程);
  // 渲染层改动 reload 窗口;main.js 改动整个 app 重启。
  const codeSync = () => {
    callPythonApi("code_sync", {}, 60000).then((res) => {
      if (!res || !res.ok || !res.data) return;
      const d = res.data;
      if (!d.updated) {
        if (d.error) console.log("[code-sync]", d.error);
        return;
      }
      const changed = d.changed || [];
      console.log("[code-sync] 框架已更新:", changed.join(", "));
      if (changed.some((f) => f === "ui/src/main.js" || f === "ui/package.json")) {
        console.log("[code-sync] main.js 变更,重启 app 生效");
        app.relaunch();
        app.exit(0);
      } else if (changed.some((f) => f.startsWith("ui/src/"))) {
        console.log("[code-sync] 界面变更,重载窗口生效");
        if (win && !win.isDestroyed()) win.webContents.reload();
        if (reviewWin && !reviewWin.isDestroyed()) reviewWin.webContents.reload();
        if (knowledgeWin && !knowledgeWin.isDestroyed()) knowledgeWin.webContents.reload();
      }
      // 纯 python 改动:无需任何动作,下一次调用即新代码
    });
  };
  setTimeout(codeSync, 5000);
  setInterval(codeSync, 1800000);

  // 开机自启:开发模式用 launchd 配置(见 ui/autostart/),不用 setLoginItemSettings
  // (后者只对打包后的正式 app 可靠;开发模式 npm start 会注册成无效的 Electron 空壳)

  app.on("activate", () => showWindow());
});

app.on("will-quit", () => globalShortcut.unregisterAll());

// Mac 上关掉窗口不退出 app(留在后台,符合浮窗常驻的预期)
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
