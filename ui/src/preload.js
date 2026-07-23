// 安全桥:只把明确允许的能力暴露给界面(渲染进程)
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("steward", {
  closeWindow: () => ipcRenderer.send("window:close"),
  minimizeWindow: () => ipcRenderer.send("window:minimize"),
  // 机器身份:work=工作机(只显示"事业") / personal=个人机(显示全部五项)
  // 来自环境变量 MACHINE_ID,下一步接真实数据时由主进程读 .env 注入,现在先默认 work
  machineId: process.env.MACHINE_ID || "work",
  // 后续步骤会在此加:读取任务、勾选写回、调 agent 拆解等
});
