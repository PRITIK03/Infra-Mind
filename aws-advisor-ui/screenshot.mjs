/**
 * Puppeteer screenshot script.
 * Navigates to localhost:3000, injects the completed job result
 * (so we don't need to re-run the agent), forces the UI into the
 * "done" state, then captures three viewport shots of the results page.
 *
 * Usage:  node screenshot.mjs
 */
import puppeteer from "puppeteer";
import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ── Real result from job ad1e2e53 (B2B SaaS API, c6g.medium, grounding_passed=true) ──
const RESULT = {
  system_design_recommendation: {
    compute: {
      recommended_instance: "c6g.medium",
      why: "Smallest EC2 instance that handles the CPU-bound API workload at 80 RPS steady traffic. 1 vCPU and 2.0 GiB RAM covers the ~8 concurrent requests under Little's law. Fixed-size vertical deployment, no over-provisioning.",
      assumptions: [
        "Workload is CPU-bound as indicated by technical needs",
        "Traffic remains steady at 80 RPS with no significant bursts",
        "min_instances == max_instances == 1 (single fixed-size deployment)",
      ],
      confidence: "medium",
      alternative_instance: "c6g.large",
      trade_off: "c6g.large offers higher CPU and memory but increases cost unnecessarily for this stable low-concurrency workload.",
    },
    database: {
      needed: true,
      recommended_instance: "db.t1.micro",
      engine_suggestion: "PostgreSQL",
      why: "Relational database required. db.t1.micro is the smallest RDS instance supporting relational engines and handles modest throughput for 500 users at 80 RPS.",
      assumptions: [
        "Relational database mandatory for data persistence",
        "No multi-AZ HA requirement specified",
        "80 RPS well within t1.micro capacity",
      ],
      confidence: "high",
      alternative_instance: "db.m1.small",
    },
    cache: {
      needed: false,
      why: "Steady 80 RPS with ~8 concurrent requests (Little's law) does not justify a dedicated cache layer. No cache requirement specified.",
      assumptions: [],
      confidence: "high",
    },
    load_balancer: {
      needed: false,
      why: "Single fixed-size EC2 instance serving steady 80 RPS. No load distribution needed — a load balancer adds cost and complexity without benefit.",
    },
    architecture_summary:
      "Single c6g.medium EC2 instance running the API service, backed by a db.t1.micro RDS PostgreSQL database. No cache or load balancer — steady 80 RPS with ~8 concurrent requests does not justify either. Vertical scaling with a fixed-size deployment sized for steady load: simple, cost-efficient, meets all requirements.",
    estimated_cost: {
      compute_monthly_low: 24.82,
      compute_monthly_high: 24.82,
      database_monthly: 18.98,
      cache_monthly: null,
      total_monthly_low: 43.8,
      total_monthly_high: 43.8,
    },
    grounding_passed: true,
    grounding_notes: [],
  },
  technical_needs: {
    estimated_concurrency: 8,
    min_instances: 1,
    max_instances: 1,
    scaling_recommendation: "vertical / fixed-size deployment sized for steady load",
    needs_database: true,
    needs_cache: false,
    load_balancer_needed: false,
    resource_profile: "cpu_bound",
    traffic_pattern: "steady",
    requires_gpu: false,
    reasoning: "500 B2B customers at 80 req/s steady — ~8 concurrent requests, no cache, no GPU, single instance sufficient.",
  },
  terraform_files: {
    "main.tf": Array.from(
      { length: 220 },
      (_, index) => `# Terraform review fixture line ${index + 1}\n`,
    ).join(""),
  },
  instance_candidates: [
    { instance_type: "c6g.medium", vcpu: 1, memory_gib: 2.0, gpu_count: 0 },
    { instance_type: "c6g.large", vcpu: 2, memory_gib: 4.0, gpu_count: 0 },
    { instance_type: "c6g.xlarge", vcpu: 4, memory_gib: 8.0, gpu_count: 0 },
    { instance_type: "t3.micro", vcpu: 2, memory_gib: 1.0, gpu_count: 0 },
    { instance_type: "t3.small", vcpu: 2, memory_gib: 2.0, gpu_count: 0 },
    { instance_type: "t3.medium", vcpu: 2, memory_gib: 4.0, gpu_count: 0 },
    { instance_type: "m5.large", vcpu: 2, memory_gib: 8.0, gpu_count: 0 },
    { instance_type: "m5.xlarge", vcpu: 4, memory_gib: 16.0, gpu_count: 0 },
    { instance_type: "m6g.medium", vcpu: 1, memory_gib: 4.0, gpu_count: 0 },
    { instance_type: "m6g.large", vcpu: 2, memory_gib: 8.0, gpu_count: 0 },
  ],
};

const OUT_DIR = path.join(__dirname, "results-screenshots");

async function main() {
  const browser = await puppeteer.launch({
    headless: "shell",
    executablePath: "C:\\Users\\priti\\.cache\\puppeteer\\chrome-headless-shell\\win64-152.0.7977.75\\chrome-headless-shell-win64\\chrome-headless-shell.exe",
    args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
  });
  const page = await browser.newPage();
  await fs.mkdir(OUT_DIR, { recursive: true });

  // Inject the completed job result into React state via the useJobPoller hook.
  //    The hook stores state in a React ref — easiest way is to POST to the API
  //    which we already did.  Instead we navigate to a URL that the app can
  //    read, but the app doesn't have URL-based state.  Simplest: simulate the
  //    full flow by intercepting the /api/recommend POST response.
  await page.setRequestInterception(true);

  let jobId = null;

  page.on("request", (req) => {
    if (req.method() === "OPTIONS" && req.url().includes("localhost:8000/api/")) {
      req.respond({
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "http://localhost:3000",
          "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    } else if (req.url().includes("/api/recommend") && req.method() === "POST" && !req.url().includes("/answer")) {
      jobId = "mock-job-screenshot";
      req.respond({
        status: 200,
        contentType: "application/json",
        headers: { "Access-Control-Allow-Origin": "http://localhost:3000" },
        body: JSON.stringify({ job_id: jobId }),
      });
    } else if (req.url().includes(`/api/recommend/${jobId}`) && req.method() === "GET") {
      req.respond({
        status: 200,
        contentType: "application/json",
        headers: { "Access-Control-Allow-Origin": "http://localhost:3000" },
        body: JSON.stringify({
          job_id: jobId,
          status: "done",
          current_stage: "Generating Terraform",
          created_at: Date.now() / 1000,
          result: RESULT,
        }),
      });
    } else if (req.url().includes("/api/stats")) {
      req.respond({
        status: 200,
        contentType: "application/json",
        headers: { "Access-Control-Allow-Origin": "http://localhost:3000" },
        body: JSON.stringify({ ec2: 738, rds: 381, cache: 68 }),
      });
    } else {
      req.continue();
    }
  });

  // Load after interception is active so the mocked API is deterministic.
  await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 1 });
  await page.goto("http://localhost:3000", { waitUntil: "networkidle2", timeout: 15000 });

  // 4. Fill the textarea and submit
  await page.waitForSelector("textarea", { timeout: 10000 });
  await page.focus("textarea");
  await page.keyboard.type("B2B SaaS REST API 500 customers 80 req/s database");
  // Click run button
  await page.click('button[type="submit"]');

  // 5. Wait for results to render — look for the topology SVG
  await page.waitForSelector('svg[aria-label="Architecture topology diagram"]', { timeout: 15000 });
  await page.waitForFunction(
    () => !document.querySelector(".typewriter-cursor"),
    { timeout: 15000 },
  );

  await page.evaluate(async () => {
    const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
    for (const ratio of [0, 0.25, 0.5, 0.75, 1]) {
      window.scrollTo(0, maxScroll * ratio);
      await new Promise((resolve) => setTimeout(resolve, 50));
      const summary = document.querySelector("[aria-label='request summary']");
      const trace = document.querySelector("[aria-label='pipeline execution trace']");
      if (!summary || !trace) throw new Error("Right-column layout elements not found");
      const summaryBox = summary.getBoundingClientRect();
      const traceBox = trace.getBoundingClientRect();
      if (summaryBox.bottom > traceBox.top) {
        throw new Error(`RequestSummary overlaps PipelineTrace at scroll ratio ${ratio}`);
      }
    }
  });

  for (const width of [1280, 768, 375]) {
    await page.setViewport({ width, height: 900, deviceScaleFactor: 1 });
    await page.evaluate(async () => {
      const summary = document.querySelector("[aria-label='request summary']");
      const trace = document.querySelector("[aria-label='pipeline execution trace']");
      const wrapper = summary?.parentElement;
      if (!summary || !trace || !wrapper) throw new Error("Responsive layout elements not found");
      if (window.innerWidth < 1280 && getComputedStyle(wrapper).position !== "static") {
        throw new Error("Right-column sticky positioning was not disabled below xl");
      }
      const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
      for (const ratio of [0, 0.5, 1]) {
        window.scrollTo(0, maxScroll * ratio);
        await new Promise((resolve) => setTimeout(resolve, 50));
        const summaryBox = summary.getBoundingClientRect();
        const traceBox = trace.getBoundingClientRect();
        if (summaryBox.bottom > traceBox.top) {
          throw new Error(`Responsive overlap at width ${window.innerWidth}, scroll ratio ${ratio}`);
        }
      }
    });
    const shot = path.join(OUT_DIR, `results-${width}.png`);
    await page.screenshot({ path: shot, fullPage: true });
    console.log("Saved:", shot);
  }

  await browser.close();
  console.log("Done.");
}

main().catch((e) => { console.error(e); process.exit(1); });
