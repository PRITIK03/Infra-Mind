import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

/**
 * E2E smoke suite (Part G) — real browser coverage over the seeded stack.
 *
 * The seeded backend (fixture factory in
 * aws-instance-advisor/scripts/dev_seed_and_serve.py, started by
 * playwright.config.ts) exposes stable job ids; they are read from the
 * script itself so the fixtures have exactly one source of truth.
 */

function seedId(name: string): string {
  const source = readFileSync(
    "../aws-instance-advisor/scripts/dev_seed_and_serve.py",
    "utf-8",
  );
  const match = source.match(new RegExp(`${name} = "([^"]+)"`));
  if (!match) throw new Error(`seed id ${name} not found in fixture factory`);
  return match[1];
}

let FULL_STACK: string;
let NO_DB: string;
let COMPUTE_ONLY: string;

test.beforeAll(() => {
  FULL_STACK = seedId("FULL_STACK_ID");
  NO_DB = seedId("NO_DB_ID");
  COMPUTE_ONLY = seedId("COMPUTE_ONLY_ID");
});

test.describe("landing page", () => {
  test("loads with headline, example chips, and working composer", async ({
    page,
  }, testInfo) => {
    testInfo.setTimeout(45_000);
    await page.goto("/", { waitUntil: "domcontentloaded" });

    await expect(page).toHaveTitle(/AWS Instance Advisor/i);
    // Example chips render from the validated scenarios.
    const chip = page.getByRole("button", { name: /flash-sale e-commerce/i });
    await expect(chip).toBeVisible();

    // Clicking an example fills the composer textarea (landing → input works).
    await chip.click();
    const composer = page.getByRole("textbox");
    await expect(composer).toHaveValue(/flash-sale/i);
  });
});

test.describe("seeded results view", () => {
  test("full-stack job renders summary, cost, review, and terraform tabs", async ({
    page,
  }, testInfo) => {
    testInfo.setTimeout(60_000);
    await page.goto(`/share/${FULL_STACK}`, { waitUntil: "domcontentloaded" });

    await expect(
      page.getByText("Viewing a shared recommendation"),
    ).toBeVisible({ timeout: 20_000 });

    // Summary strip + report body render the seeded compute instance.
    await expect(page.getByText("m5.large").first()).toBeVisible();
    // Cost section from the seeded estimate.
    await expect(page.getByText(/\$12[05]/).first()).toBeVisible();
    // Well-Architected review section is present.
    await expect(
      page.getByText(/well.architected/i).first(),
    ).toBeVisible();

    // Terraform section exists with its file tabs.
    await expect(page.getByText("main.tf")).toBeVisible();
  });

  test("no-database job omits the database tier honestly", async ({ page }) => {
    await page.goto(`/share/${NO_DB}`, { waitUntil: "domcontentloaded" });
    await expect(
      page.getByText("Viewing a shared recommendation"),
    ).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("db.t3.medium")).toHaveCount(0);
  });

  test("compute-only job still renders compute guidance", async ({ page }) => {
    await page.goto(`/share/${COMPUTE_ONLY}`, { waitUntil: "domcontentloaded" });
    await expect(
      page.getByText("Viewing a shared recommendation"),
    ).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("m5.large").first()).toBeVisible();
  });
});

test.describe("command palette", () => {
  test("opens with ctrl+k and the shortcuts sheet works", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });

    await page.keyboard.press("Control+k");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // Footer link opens the shortcuts sheet inside the same dialog.
    await dialog.getByRole("button", { name: "? shortcuts" }).click();
    await expect(
      dialog.getByText("Keyboard shortcuts", { exact: true }),
    ).toBeVisible();
    await expect(
      dialog.getByText("Toggle this palette"),
    ).toBeVisible();

    // Back navigation returns to the command list.
    await dialog.getByText("← back to commands").click();
    await expect(
      dialog.getByPlaceholder("Search commands..."),
    ).toBeVisible();
  });
});

test.describe("404 page", () => {
  test("renders the on-brand not-found page with a way back", async ({
    page,
  }) => {
    const response = await page.goto("/definitely-not-a-route", {
      waitUntil: "domcontentloaded",
    });
    expect(response?.status()).toBe(404);
    await expect(page.getByText("page not found")).toBeVisible();
    const back = page.getByRole("link", { name: /back to advisor/i });
    await expect(back).toBeVisible();
    await back.click();
    await expect(page).toHaveURL(/\/$/);
  });
});
