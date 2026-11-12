import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ResultReport } from "./ResultReport";
import { recommendationToMarkdown } from "@/lib/reportMarkdown";
import type { SystemDesignRecommendation } from "@/lib/types";

const sdr: SystemDesignRecommendation = {
  compute: { recommended_instance: "m5.large", why: "Capacity estimate", confidence: "medium", assumptions: [] },
  database: { needed: false, why: "Existing database", confidence: "high", assumptions: [] },
  cache: { needed: false, why: "No cache", confidence: "high", assumptions: [] },
  load_balancer: { needed: false, why: "Single instance" },
  architecture_summary: "An API with an existing database.",
  grounding_passed: null,
  grounding_notes: ["Consistency check unavailable."],
  deployment_handoff: {
    generated_resources: ["EC2 m5.large · Auto Scaling group 1–1"],
    actions: [
      { id: "application", phase: "before_apply", title: "Supply the application", detail: "Stock Amazon Linux does not contain your application." },
      { id: "external-database", phase: "before_traffic", title: "Connect the existing database", detail: "Verify connectivity, TLS and recovery." },
    ],
  },
};

describe("Deployment handoff", () => {
  it("renders actionable phases, expands a step, and keeps the full detail in Markdown", async () => {
    const user = userEvent.setup();
    render(<ResultReport sdr={sdr} />);
    expect(screen.getByRole("region", { name: "Deployment handoff" })).toBeInTheDocument();
    expect(screen.getByText("Terraform scaffold")).toBeInTheDocument();
    expect(screen.getByText("Consistency check unavailable")).toBeInTheDocument();
    const step = screen.getByText("Supply the application").closest("details")!;
    expect(step).not.toHaveAttribute("open");
    await user.click(screen.getByText("Supply the application"));
    expect(step).toHaveAttribute("open");
    expect(screen.getByText("Stock Amazon Linux does not contain your application.")).toBeVisible();
    const markdown = recommendationToMarkdown({ sdr });
    expect(markdown).toContain("### Before Applying");
    expect(markdown).toContain("### Before Serving Traffic");
    expect(markdown).toContain("Verify connectivity, TLS and recovery.");
    expect(markdown).toContain("Consistency check: unavailable");
  });

  it("preserves older reports without a handoff or verification fields", async () => {
    render(<ResultReport sdr={{ ...sdr, deployment_handoff: null, grounding_notes: [], grounding_passed: null }} />);
    expect(screen.queryByRole("region", { name: "Deployment handoff" })).not.toBeInTheDocument();
    expect(screen.queryByText("Consistency check unavailable")).not.toBeInTheDocument();
    expect(await screen.findByText("An API with an existing database.")).toBeInTheDocument();
  });
});
