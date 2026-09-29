import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ResultSummaryStrip } from "./ResultSummaryStrip";
import type { SystemDesignRecommendation } from "@/lib/types";

const baseSdr: SystemDesignRecommendation = {
  compute: {
    recommended_instance: "c6i.xlarge",
    why: "Compute optimized",
    assumptions: [],
    confidence: "high",
  },
  database: {
    needed: false,
    why: "",
    assumptions: [],
    confidence: "low",
  },
  cache: {
    needed: false,
    why: "",
    assumptions: [],
    confidence: "low",
  },
  load_balancer: {
    needed: false,
    why: "",
  },
  architecture_summary: "Test summary",
  grounding_passed: true,
  estimated_cost: {
    total_monthly_low: 120,
    total_monthly_high: 150,
  },
  well_architected_review: [
    { pillar: "reliability", severity: "warning", message: "Single AZ warning" },
    { pillar: "security", severity: "info", message: "Audit logs recommendation" },
  ],
};

describe("ResultSummaryStrip", () => {
  it("renders compute instance, cost range, grounding status, and well-architected counts", () => {
    render(<ResultSummaryStrip sdr={baseSdr} />);

    expect(screen.getByText("compute")).toBeInTheDocument();
    expect(screen.getByText("c6i.xlarge")).toBeInTheDocument();

    expect(screen.getByText("est. monthly cost")).toBeInTheDocument();
    expect(screen.getByText("$120–$150/mo")).toBeInTheDocument();

    expect(screen.getByText("grounding")).toBeInTheDocument();
    expect(screen.getByText("verified")).toBeInTheDocument();

    expect(screen.getByText("well-architected")).toBeInTheDocument();
    expect(screen.getByText(/2 findings/)).toBeInTheDocument();
    expect(screen.getByText(/1 warning/)).toBeInTheDocument();
  });

  it("handles missing optional values gracefully", () => {
    const minimalSdr: SystemDesignRecommendation = {
      ...baseSdr,
      estimated_cost: undefined,
      grounding_passed: undefined,
      well_architected_review: [],
    };

    render(<ResultSummaryStrip sdr={minimalSdr} />);

    expect(screen.getByText("compute")).toBeInTheDocument();
    expect(screen.getByText("c6i.xlarge")).toBeInTheDocument();
    expect(screen.queryByText("est. monthly cost")).not.toBeInTheDocument();
    expect(screen.queryByText("grounding")).not.toBeInTheDocument();
    expect(screen.queryByText("well-architected")).not.toBeInTheDocument();
  });
});
