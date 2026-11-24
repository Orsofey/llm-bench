// Диагностика адаптивности через Chrome DevTools Protocol, без npm-зависимостей.
import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";

const [widthArg, heightArg, output] = process.argv.slice(2);
const width = Number(widthArg || 390), height = Number(heightArg || 844);
const chromePath = process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const port = 9333 + Math.floor(Math.random() * 200);
const chrome = spawn(chromePath, [
  "--headless=new", "--disable-gpu", "--hide-scrollbars", `--remote-debugging-port=${port}`,
  `--user-data-dir=${process.env.TEMP || "C:/Windows/Temp"}/llmbench-cdp-${port}`, "about:blank",
], { stdio: "ignore" });

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
let socketUrl;
for (let i = 0; i < 40; i++) {
  try {
    const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
    socketUrl = pages.find(p => p.type === "page")?.webSocketDebuggerUrl;
    if (socketUrl) break;
  } catch {}
  await pause(100);
}
if (!socketUrl) {
  chrome.kill();
  throw new Error("Chrome DevTools не запустился");
}
const ws = new WebSocket(socketUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let nextId = 0;
const pending = new Map();
ws.onmessage = event => {
  const msg = JSON.parse(event.data);
  if (!msg.id || !pending.has(msg.id)) return;
  const { resolve, reject } = pending.get(msg.id);
  pending.delete(msg.id);
  msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
};
const cdp = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++nextId;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params }));
});
try {
  await cdp("Page.enable");
  await cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
  await cdp("Page.navigate", { url: process.env.LLM_BENCH_PREVIEW_URL || "http://127.0.0.1:8787/" });
  await pause(2200);
  if (process.env.LLM_BENCH_TAB) {
    await cdp("Runtime.evaluate", { expression: `document.querySelector('[data-tab="${process.env.LLM_BENCH_TAB}"]').click()` });
    await pause(800);
  }
  const result = await cdp("Runtime.evaluate", {
    expression: `JSON.stringify({viewport:[innerWidth,innerHeight],scroll:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],overflow:document.documentElement.scrollWidth>innerWidth,wide:[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(e=>({tag:e.tagName,id:e.id,cls:e.className,right:Math.round(e.getBoundingClientRect().right)}))})`,
    returnByValue: true,
  });
  console.log(result.result.value);
  if (output) {
    const shot = await cdp("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    writeFileSync(output, Buffer.from(shot.data, "base64"));
  }
} finally {
  ws.close();
  chrome.kill();
}
