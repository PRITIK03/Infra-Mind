import { defineConfig, devices } from "@playwright/test";

/**
 * E2E smoke suite (Part G): real browser coverage over the seeded stack.
 *
 * Both servers are started by Playwright itself:
 *   1. the FastAPI backend running scripts/dev_seed_and_serve.py — the same
 *      fixture factory the OG verification used (no LLM/AWS calls), and
 *   2. the production frontend build (`next start`) pointed at it.
 *
 * The stable seeded job ids live in scripts/dev_seed_and_serve.py
 * (aws-instance-advisor) and are imported here — one source of truth.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  workers: 1, // one shared seeded backend; keep test order deterministic
  reporter: process.env.CI ? "list" : [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "python scripts/dev_seed_and_serve.py",
      cwd: "../aws-instance-advisor",
      url: "http://localhost:8000/api/health",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        API_KEY: "dummy-key",
        BASE_URL: "https://example.com/v1",
        MODEL_NAME: "dummy-model",
        VANTAGE_API_KEY: "dummy-vantage-key",
        CORS_ALLOWED_ORIGIN: "http://localhost:3000",
        PORT: "8000",
        LOG_FORMAT: "text",
        PYTHONPATH: ".",
      },
    },
    {
      command: "npx next start --port 3000",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        NEXT_PUBLIC_API_URL: "http://localhost:8000",
        NEXT_PUBLIC_SITE_URL: "http://localhost:3000",
      },
    },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
