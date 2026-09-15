/**
 * Full UI audit: loads both pages in a real browser, collects console
 * errors/warnings, page exceptions, failed network requests, and verifies
 * key UI elements + live backend connections.
 */
import puppeteer from "puppeteer";

const results = { pages: {}, consoleIssues: [], failedRequests: [], checks: {} };

const browser = await puppeteer.launch({
  headless: true,
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });

page.on("console", (msg) => {
  if (msg.type() === "error" || msg.type() === "warning") {
    results.consoleIssues.push(`[${msg.type()}] ${msg.text()}`);
  }
});
page.on("pageerror", (err) => {
  results.consoleIssues.push(`[pageerror] ${err.message}`);
});
page.on("requestfailed", (req) => {
  results.failedRequests.push(`${req.method()} ${req.url()} — ${req.failure()?.errorText}`);
});
page.on("response", (res) => {
  if (res.status() >= 400) {
    results.failedRequests.push(`HTTP ${res.status()} ${res.url()}`);
  }
});

// ── Page 1: landing ──────────────────────────────────────────────
await page.goto("http://localhost:3000", { waitUntil: "networkidle2", timeout: 60000 });
await new Promise((r) => setTimeout(r, 2500)); // allow health/stats fetches to settle

results.pages.landing = {
  title: await page.title(),
  url: page.url(),
};

// key elements
const landingChecks = await page.evaluate(() => {
  const q = (sel) => document.querySelector(sel);
  const body = document.body.innerText;
  return {
    wordmark: body.includes("aws-instance-advisor"),
    navHistory: body.includes("run history"),
    h1: body.includes("AWS Instance Advisor"),
    textarea: !!q("textarea[aria-label]"),
    exampleChips: document.querySelectorAll("button").length,
    examplesLabel: body.includes("examples"),
    runButton: body.includes("run"),
    keyboardHint: body.includes("quick actions"),
    favicon: !!q('link[rel="icon"]'),
    themeColor: q('meta[name="theme-color"]')?.getAttribute("content") ?? null,
    bodyBg: getComputedStyle(document.body).backgroundColor,
    colorScheme: getComputedStyle(document.documentElement).colorScheme,
    noNaN: !body.includes("NaN"),
    statsReadout: body.includes("EC2") && body.includes("RDS"),
  };
});
results.checks.landing = landingChecks;

// screenshot
await page.screenshot({ path: "audit-landing.png", fullPage: false });

// ── Interactions: example chip fills textarea, focus-within works ──
const chipTest = await page.evaluate(() => {
  const chips = [...document.querySelectorAll("button")].filter(
    (b) => b.textContent.includes("flash-sale") || b.textContent.includes("SaaS") || b.textContent.includes("batch") || b.textContent.includes("ML")
  );
  if (!chips.length) return { chipFound: false };
  chips[0].click();
  return { chipFound: true, chipLabel: chips[0].textContent.trim() };
});
await new Promise((r) => setTimeout(r, 300));
chipTest.textareaFilled = await page.evaluate(
  () => document.querySelector("textarea")?.value.length > 50
);
results.checks.chipInteraction = chipTest;

// command palette
await page.keyboard.down("Control");
await page.keyboard.press("k");
await page.keyboard.up("Control");
await new Promise((r) => setTimeout(r, 500));
results.checks.commandPalette = await page.evaluate(() => {
  const dlg = document.querySelector("[cmdk-root]");
  return { opens: !!dlg, hasInput: !!dlg?.querySelector("input") };
});
await page.keyboard.press("Escape");
await new Promise((r) => setTimeout(r, 300));

// ── Page 2: history ──────────────────────────────────────────────
await page.goto("http://localhost:3000/history", { waitUntil: "networkidle2", timeout: 60000 });
await new Promise((r) => setTimeout(r, 2500));

results.pages.history = { url: page.url() };
results.checks.history = await page.evaluate(() => {
  const body = document.body.innerText;
  return {
    wordmark: body.includes("aws-instance-advisor"),
    loaded: body.includes("timestamp") || body.includes("No runs yet") || body.includes("isn"),
    noNaN: !body.includes("NaN"),
    tableOrEmpty: body.includes("latency") || body.includes("No runs yet"),
    costTrend: body.includes("cost over time") || body.includes("No runs yet"),
  };
});
await page.screenshot({ path: "audit-history.png", fullPage: true });

await browser.close();
console.log(JSON.stringify(results, null, 2));
