import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchSharedJob } from "@/lib/api";
import type { JobResponse, SystemDesignRecommendation } from "@/lib/types";
import { shareCardContent, shareRouteMetadata } from "./shareMeta";

vi.mock("@/lib/api", () => ({
  fetchSharedJob: vi.fn(),
}));

const mockedFetchSharedJob = vi.mocked(fetchSharedJob);

const baseSdr: SystemDesignRecommendation = {
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
  architecture_summary: "Summary.",
  estimated_cost: { total_monthly_low: 120, total_monthly_high: 150 },
};

function doneJob(sdr: Partial<SystemDesignRecommendation> = {}): JobResponse {
  return {
    job_id: "meta-job-1",
    status: "done",
    current_stage: "Complete",
    created_at: 1,
    result: { system_design_recommendation: { ...baseSdr, ...sdr } },
  };
}

describe("shareCardContent", () => {
  it("builds title and description from real fields (all tiers present)", () => {
    const { title, description } = shareCardContent(doneJob());
    expect(title).toBe("AWS Infra Recommendation — m5.large");
    expect(description).toBe("m5.large + PostgreSQL + Redis — $120-$150/mo");
  });

  it("omits tiers that are not present instead of showing empty text", () => {
    const { description } = shareCardContent(
      doneJob({
        database: { ...baseSdr.database, needed: false },
        cache: { ...baseSdr.cache, needed: false },
      }),
    );
    expect(description).toBe("m5.large — $120-$150/mo");
    expect(description).not.toContain("+"); // no empty tier slots
    expect(description).not.toContain("undefined");
    expect(description).not.toContain("null");
  });

  it("omits the cost suffix when no cost data exists", () => {
    const { description } = shareCardContent(
      doneJob({ estimated_cost: undefined }),
    );
    expect(description).toBe("m5.large + PostgreSQL + Redis");
    expect(description).not.toContain("/mo");
  });
});

describe("shareRouteMetadata", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("produces title/description from a mocked completed job", async () => {
    mockedFetchSharedJob.mockResolvedValue(doneJob());

    const meta = await shareRouteMetadata("meta-job-1");

    expect(meta.title).toBe("AWS Infra Recommendation — m5.large");
    expect(meta.description).toBe("m5.large + PostgreSQL + Redis — $120-$150/mo");
    expect(meta.openGraph?.title).toBe(meta.title);
    expect(meta.openGraph?.description).toBe(meta.description);
    expect(meta.openGraph?.images).toEqual([
      { url: "/share/meta-job-1/opengraph-image", alt: meta.title },
    ]);
    // Twitter metadata is a discriminated union; the summary_large_image
    // variant is the only one carrying a `card` literal, so read it through
    // a record rather than narrowing the whole union in the test.
    expect((meta.twitter as { card?: string } | undefined)?.card).toBe(
      "summary_large_image",
    );    expect(mockedFetchSharedJob).toHaveBeenCalledWith("meta-job-1");
  });

  it("falls back to the honest default when the job can't be read", async () => {
    mockedFetchSharedJob.mockRejectedValue(new Error("Shared result not found"));

    const meta = await shareRouteMetadata("meta-job-1");

    expect(meta.title).toBe("Shared recommendation — AWS Instance Advisor");
    expect(meta.description).toContain("may have expired");
    expect(meta.openGraph?.images).toBeUndefined();
  });
});
