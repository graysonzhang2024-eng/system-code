// 安全桥:只把明确允许的能力暴露给界面(渲染进程)
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("steward", {
  closeWindow: () => ipcRenderer.send("window:close"),
  minimizeWindow: () => ipcRenderer.send("window:minimize"),
  machineId: process.env.MACHINE_ID || "work",
  // 调用 Python 桥(os_api.py):读任务树 / 勾选 / 加任务 / 加子任务
  // 返回 Promise<{ok, data|error}>
  api: (cmd, arg) => ipcRenderer.invoke("os:api", cmd, arg || {}),
  openReview: () => ipcRenderer.send("review:open"),
  closeReview: () => ipcRenderer.send("review:close"),
  openKnowledge: () => ipcRenderer.send("knowledge:open"),
  closeKnowledge: () => ipcRenderer.send("knowledge:close"),
});
