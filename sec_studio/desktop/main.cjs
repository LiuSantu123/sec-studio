const { app, BrowserWindow, dialog } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");

let engine = null;
let serverUrl = null;

function freeLoopbackPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(error => error ? reject(error) : resolve(port));
    });
  });
}

function engineCommand() {
  if (app.isPackaged) {
    const exe = process.platform === "win32" ? "sec-studio-engine.exe" : "sec-studio-engine";
    return { command: path.join(process.resourcesPath, "sec-studio-engine", exe), args: [] };
  }
  const python = process.env.SEC_STUDIO_PYTHON || (process.platform === "win32" ? "python" : "python3");
  const backend = path.resolve(__dirname, "..");
  return { command: python, args: [path.join(backend, "app.py")], cwd: backend };
}

function waitForServer(url, child, timeoutMs = 30000) {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    child.once("error", reject);
    const poll = async () => {
      if (child.exitCode !== null) return reject(new Error("SEC Studio 引擎提前退出"));
      try {
        const response = await fetch(url, { signal: AbortSignal.timeout(800) });
        if (response.ok) return resolve();
      } catch (_) {}
      if (Date.now() - startedAt > timeoutMs) return reject(new Error("SEC Studio 引擎启动超时"));
      setTimeout(poll, 200);
    };
    poll();
  });
}

async function startEngine() {
  const port = await freeLoopbackPort();
  const dataDir = path.join(app.getPath("documents"), "SEC Studio");
  fs.mkdirSync(dataDir, { recursive: true });
  const target = engineCommand();
  const args = [...target.args, "--host", "127.0.0.1", "--port", String(port),
    "--data-dir", dataDir, "--no-browser"];
  engine = spawn(target.command, args, {
    cwd: target.cwd || dataDir,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, PYTHONUNBUFFERED: "1" }
  });
  const logPath = path.join(app.getPath("logs"), "sec-studio-engine.log");
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  const log = fs.createWriteStream(logPath, { flags: "a" });
  engine.stdout.pipe(log);
  engine.stderr.pipe(log);
  engine.once("error", error => console.error("Engine launch failed:", error));
  await waitForServer(`http://127.0.0.1:${port}/`, engine);
  return `http://127.0.0.1:${port}/`;
}

async function createWindow() {
  if (!serverUrl) {
    try {
      serverUrl = await startEngine();
    } catch (error) {
      dialog.showErrorBox("SEC Studio 启动失败", `${error.message}\n\n日志：${path.join(app.getPath("logs"), "sec-studio-engine.log")}`);
      app.quit();
      return;
    }
  }
  const window = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 980,
    minHeight: 680,
    title: "SEC Studio",
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true }
  });
  window.loadURL(serverUrl);
}

app.whenReady().then(createWindow);
app.on("session-created", downloadSession => {
  downloadSession.on("will-download", (_event, item, contents) => {
    item.pause();
    const owner = BrowserWindow.fromWebContents(contents);
    const suggestedPath = path.join(app.getPath("downloads"), item.getFilename());
    dialog.showSaveDialog(owner, { defaultPath: suggestedPath }).then(result => {
      if (result.canceled || !result.filePath) {
        item.cancel();
        return;
      }
      item.setSavePath(result.filePath);
      item.resume();
    }).catch(error => {
      console.error("Save dialog failed:", error);
      item.cancel();
    });
  });
});
app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
app.on("before-quit", () => {
  if (engine && engine.exitCode === null) {
    engine.kill();
    engine = null;
  }
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
