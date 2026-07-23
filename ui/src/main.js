// Electron 主进程:创建常驻桌面角落的半透明浮窗
const { app, BrowserWindow, screen, ipcMain, Tray, Menu, nativeImage, globalShortcut } = require("electron");
const path = require("path");
const fs = require("fs");

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
  app.on("activate", () => showWindow());
});

app.on("will-quit", () => globalShortcut.unregisterAll());

// Mac 上关掉窗口不退出 app(留在后台,符合浮窗常驻的预期)
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
