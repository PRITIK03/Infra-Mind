/**
 * Capture landing + history pages at 1280 for the final polish screenshot.
 * Usage: node shots.mjs final  -> shots/final/landing.png, history.png
 */
import puppeteer from "puppeteer";
import fs from "fs/promises";

const label = process.argv[2] ?? "after";
const width = 1280;

await fs.mkdir(`shots/${label}`, { recursive: true });

const browser = await puppeteer.launch({
  headless: true,
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
});
const page = await browser.newPage();

await page.setViewport({ width, height: 900 });
await page.goto("http://localhost:3000", { waitUntil: "networkidle2", timeout: 60000 });
await new Promise((r) => setTimeout(r, 2500));
await page.screenshot({ path: `shots/${label}/landing.png`, fullPage: false });

await page.goto("http://localhost:3000/history", { waitUntil: "networkidle2", timeout: 60000 });
await new Promise((r) => setTimeout(r, 2000));
await page.screenshot({ path: `shots/${label}/history.png`, fullPage: false });

await browser.close();
console.log(`captured ${label} @ ${width}`);
