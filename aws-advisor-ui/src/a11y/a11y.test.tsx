import { describe, expect, it, vi, beforeAll, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { axe } from "vitest-axe";
import type { AxeResults } from "axe-core";
import LandingPage from "@/app/page";
import ShareView from "@/app/share/[jobId]/ShareView";
import HistoryPage from "@/app/history/page";
import type { JobResponse, SystemDesignRecommendation } from "@/lib/types";

// vitest-axe's toHaveNoViolations matcher is incompatible with vitest 5's
// chai, so the assertion is written directly against the results object —
// same check, explicit failure output listing every violation found.
function assertNoViolations(results: AxeResults) {
  const summary = results.violations
    .map(
      (v) =>
        `${v.id} (${v.impact}): ${v.nodes.length} node(s) — ${v.nodes
          .map((n) => n.target.join(" "))
          .join("; ")}`,
    )
    .join("\n");
  expect(summary, "axe found accessibility violations").toBe("");
}

/**
 * Automated accessibility audit (Part D): axe-core over the four real pages,
 * against a seeded completed job (the OG-verification fixture technique —
 * zero live calls). Assertions use toHaveNoViolations; anything reported is
 * either fixed genuinely or (rarely) excluded with a written justification.
 */

// The landing page navigates programmatically; jsdom has no app router.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    healthCheck: vi.fn().mockResolvedValue({ status: "ok" }),
    getStats: vi
      .fn()
      .mockResolvedValue({ ec2: 700, rds: 60, cache: 20 }),
    getRuns: vi.fn().mockResolvedValue({
      runs: [],
      page: 1,
      page_size: 20,
      total: 0,
      observability_enabled: false,
    }),
    fetchSharedJob: vi.fn(),
  };
});

const sdr: SystemDesignRecommendation = {
  compute: {
    recommended_instance: "m5.large",
    why: "Balanced general purpose compute.",
    assumptions: [],
    confidence: "high",
  },
  database: {
    needed: true,
    recommended_instance: "db.t3.medium",
    engine_suggestion: "PostgreSQL",
    why: "Standard relational storage.",
    assumptions: [],
    confidence: "medium",
  },
  cache: {
    needed: true,
    recommended_instance: "cache.t3.micro",
    engine: "Redis",
    why: "Session cache.",
    assumptions: [],
    confidence: "high",
  },
  load_balancer: { needed: false, why: "Single instance." },
  architecture_summary: "Two-tier web service.",
  well_architected_review: [
    {
      pillar: "operational_excellence" as const,
      severity: "info" as const,
      message: "Infrastructure is expressed as reviewed Terraform.",
    },
  ],
  estimated_cost: { total_monthly_low: 120, total_monthly_high: 150 },
};

const doneJob: JobResponse = {
  job_id: "axe-job-1",
  status: "done",
  current_stage: "Complete",
  created_at: 1,
  result: { system_design_recommendation: sdr },
};

beforeAll(() => {
  // jsdom lacks layout; these APIs are only used for scroll positioning.
  Element.prototype.scrollIntoView = () => {};
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("accessibility (axe-core)", () => {
  it("landing page has no violations", async () => {
    const { container } = render(<LandingPage />);
    const results = await axe(container);
    assertNoViolations(results);
  });

  it("completed results (share view) has no violations", async () => {
    const { fetchSharedJob } = await import("@/lib/api");
    vi.mocked(fetchSharedJob).mockResolvedValue(doneJob);

    const { container } = render(<ShareView jobId="axe-job-1" />);
    // Wait past the loading state so the full result is audited.
    await vi.waitFor(() => {
      expect(container.textContent).toContain(
        "Viewing a shared recommendation",
      );
    });
    const results = await axe(container);
    assertNoViolations(results);
  });

  it("history page has no violations", async () => {
    const { container } = render(<HistoryPage />);
    // Let the (mocked) run-history fetch settle before auditing.
    await vi.waitFor(() => {
      expect(container.textContent).not.toContain("loading run history");
    });
    const results = await axe(container);
    assertNoViolations(results);
  });
});
