import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConsensusResult } from "./ConsensusResult";
import type { ConsensusResult as ConsensusResultType } from "@/lib/types";

const ran: ConsensusResultType = {
  enabled: true,
  primary_model: "openrouter/free",
  secondary_model: "nvidia/nemotron-3-ultra-550b-a55b:free",
  agreement_level: "partial",
  agreements: ["database", "load_balancer"],
  disagreements: [
    { tier: "compute", primary_choice: "m6a.large", secondary_choice: "m8g.large" },
    { tier: "cache", primary_choice: "cache.t3.medium", secondary_choice: "cache.m6g.large" },
  ],
  note: null,
};

describe("ConsensusResult", () => {
  it("renders nothing when consensus was declined (enabled=false)", () => {
    const { container } = render(
      <ConsensusResult consensus={{ ...ran, enabled: false, agreement_level: null }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders agreement level and per-tier disagreements when consensus ran", () => {
    render(<ConsensusResult consensus={ran} />);

    // agreement_level surfaced in human form
    expect(screen.getByText("partial agreement")).toBeInTheDocument();

    // per-tier disagreements, both choices shown side by side
    expect(screen.getByText("m6a.large")).toBeInTheDocument();
    expect(screen.getByText("m8g.large")).toBeInTheDocument();
    expect(screen.getByText("cache.t3.medium")).toBeInTheDocument();
    expect(screen.getByText("cache.m6g.large")).toBeInTheDocument();

    // agreed tiers listed with humanised labels
    expect(screen.getByText(/agreed on:/)).toHaveTextContent(
      "Database, Load balancer",
    );
  });
});
