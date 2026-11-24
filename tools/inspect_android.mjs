// Проверка WebView в уже запущенном APK через adb forward tcp:8793 localabstract:...
import { writeFileSync } from "node:fs";

const port = process.env.ANDROID_DEVTOOLS_PORT || 8793;
const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const page = pages.find(p => p.type === "page" && p.url.includes("127.0.0.1"));
if (!page) throw new Error("LLM Bench WebView не найден");
const ws = new WebSocket(page.webSocketDebuggerUrl);
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
  if (process.env.ANDROID_TAB) {
    await cdp("Runtime.evaluate", { expression: `document.querySelector('[data-tab="${process.env.ANDROID_TAB}"]').click()` });
    await new Promise(resolve => setTimeout(resolve, 1200));
  }
  const result = await cdp("Runtime.evaluate", {
    expression: `JSON.stringify({title:document.title,text:document.body.innerText.slice(0,500),viewport:[innerWidth,innerHeight],scroll:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],overflow:document.documentElement.scrollWidth>innerWidth,androidNote:!document.querySelector('#androidNote')?.classList.contains('hide'),subDisabled:document.querySelector('[data-mode="sub"]')?.disabled,estimate:document.querySelector('#publicEstimate')?.textContent,estimateWidth:document.querySelector('#publicEstimate')?.getBoundingClientRect().width,estimateScroll:document.querySelector('#publicEstimate')?.scrollWidth})`,
    returnByValue: true,
  });
  console.log(result.result.value);
  if (process.argv[2]) {
    const shot = await cdp("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    writeFileSync(process.argv[2], Buffer.from(shot.data, "base64"));
  }
} finally {
  ws.close();
}
