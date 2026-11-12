import { describe, expect, it } from "vitest";
import { recommendationToMarkdown } from "./reportMarkdown";
import type { SystemDesignRecommendation } from "./types";

const recommendation: SystemDesignRecommendation = {
  compute: {
    recommended_instance: "t3.micro",
    why: "Steady API workload",
    assumptions: ["Low burst demand"],
    confidence: "high",
    alternative_instance: "t3.small",
    trade_off: "More memory",
  },
  database: {
    needed: true,
    recommended_instance: "db.t3.small",
    engine_suggestion: "PostgreSQL",
    why: "Transactional storage",
    assumptions: [],
    confidence: "medium",
  },
  cache: {
    needed: false,
    why: "The workload does not need caching.",
    assumptions: [],
    confidence: "high",
  },
  load_balancer: {
    needed: false,
    why: "One instance is sufficient.",
  },
  architecture_summary: "A small API backed by PostgreSQL.",
  estimated_cost: {
    compute_monthly_low: 8,
    compute_monthly_high: 12,
    database_monthly: 30,
    cache_monthly: null,
    total_monthly_low: 38,
    total_monthly_high: 42,
  },
};

describe("recommendationToMarkdown", () => {
  it("includes populated recommendation content and meaningful not-needed labels", () => {
    const markdown = recommendationToMarkdown({
      sdr: recommendation,
      technicalNeeds: {
        estimated_concurrency: 20,
        min_instances: 1,
        max_instances: 1,
        scaling_recommendation: "fixed",
        needs_database: true,
        needs_cache: false,
        load_balancer_needed: false,
        resource_profile: "balanced",
        traffic_pattern: "steady",
        requires_gpu: false,
        reasoning: "steady API",
      },
      userRequirements: { registered_users: 500 },
    });

    expect(markdown).toContain("A small API backed by PostgreSQL.");
    expect(markdown).toContain("Users -> t3.micro -> db.t3.small");
    expect(markdown).toContain("Stated registered users: 500");
    expect(markdown).toContain("Cache: not needed");
    expect(markdown).toContain("Instance subtotal: $38 - $42");
    expect(markdown).toContain("Excludes load balancers");
    expect(markdown).not.toContain("undefined");
  });

  it("uses workload-aware concurrency wording and keeps long rationale text intact", () => {
    const databaseWhy = "Vertical scaling is appropriate for this workload because the database has sustained transactional demand and requires additional memory headroom.";
    const markdown = recommendationToMarkdown({
      sdr: {
        ...recommendation,
        database: { ...recommendation.database, why: databaseWhy },
      },
      technicalNeeds: {
        estimated_concurrency: 1,
        min_instances: 1,
        max_instances: 1,
        scaling_recommendation: "fixed",
        needs_database: true,
        needs_cache: false,
        load_balancer_needed: false,
        resource_profile: "balanced",
        traffic_pattern: "steady",
        requires_gpu: false,
        reasoning: "batch workload",
      },
      userRequirements: { workload_type: "batch_processing" },
    });

    expect(markdown).toContain("Estimated concurrency: 1 concurrent job/worker slot");
    expect(markdown).toContain(`Why: ${databaseWhy}`);
  });

  it("includes repository coverage, assumptions, and a commit-pinned evidence link", () => {
    const commit = "a".repeat(40);
    const markdown = recommendationToMarkdown({
      sdr: recommendation,
      repositoryAssumptions: ["Provisional sizing assumes 10 peak requests per second."],
      repository: {
        repository: { owner: "acme", name: "service" },
        commit_sha: commit,
        coverage: "partial",
        files_discovered: 3,
        files_analyzed: 2,
        skipped: { unreadable: 1 },
        limitations: ["One file could not be read."],
        stack: ["FastAPI"],
        databases: ["PostgreSQL"],
        workflows: [],
        workload_type: "api_service",
        has_dockerfile: false,
        local_inference: false,
        hosted_inference: false,
        model_artifacts: 0,
        advisory_status: "not_configured",
        findings: [{
          category: "database", title: "PostgreSQL referenced", action: "Verify the production data store.",
          path: "data files/config.py", line: 12, severity: "info", confidence: "observed",
        }],
      },
    });
    expect(markdown).toContain("partial, 2 of 3 tracked files read");
    expect(markdown).toContain("Provisional sizing assumes 10 peak requests per second.");
    expect(markdown).toContain(`https://github.com/acme/service/blob/${commit}/data%20files/config.py#L12`);
  });
});
