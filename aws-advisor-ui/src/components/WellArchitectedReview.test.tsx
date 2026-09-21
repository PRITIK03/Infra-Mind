import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WellArchitectedReview } from "./WellArchitectedReview";
import type { WellArchitectedFinding } from "@/lib/types";

function finding(
  pillar: WellArchitectedFinding["pillar"],
  severity: WellArchitectedFinding["severity"],
  message: string,
): WellArchitectedFinding {
  return { pillar, severity, message };
}

describe("WellArchitectedReview", () => {
  it("renders nothing when there are no findings", () => {
    const { container } = render(<WellArchitectedReview findings={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("groups findings under their pillar, humanising the pillar name", () => {
    render(
      <WellArchitectedReview
        findings={[
          finding("reliability", "warning", "single instance, no redundancy"),
          finding("cost_optimization", "info", "no cache tier for a read-heavy profile"),
        ]}
      />,
    );

    expect(screen.getByText("reliability")).toBeInTheDocument();
    expect(screen.getByText("cost optimization")).toBeInTheDocument();
    expect(screen.getByText("single instance, no redundancy")).toBeInTheDocument();
    expect(
      screen.getByText("no cache tier for a read-heavy profile"),
    ).toBeInTheDocument();
  });

  it("renders pillars in canonical order regardless of input order", () => {
    render(
      <WellArchitectedReview
        findings={[
          finding("operational_excellence", "info", "repo context unavailable"),
          finding("reliability", "warning", "no redundancy"),
        ]}
      />,
    );

    const labels = screen
      .getAllByText(/^(reliability|operational excellence)$/)
      .map((el) => el.textContent);
    expect(labels).toEqual(["reliability", "operational excellence"]);
  });

  it("distinguishes severity by opacity only — no extra colour classes", () => {
    render(
      <WellArchitectedReview
        findings={[
          finding("reliability", "warning", "warn message"),
          finding("security", "info", "info message"),
        ]}
      />,
    );

    const warn = screen.getByText("warn message");
    const info = screen.getByText("info message");

    // Higher opacity for warnings, same hue for both.
    expect(Number(warn.style.opacity)).toBeGreaterThan(Number(info.style.opacity));
    expect(warn.style.color).toBe(info.style.color);
    // No colour-based badge utilities were introduced.
    expect(warn.className).not.toMatch(/text-(red|amber|green|yellow|blue)/);
    expect(info.className).not.toMatch(/text-(red|amber|green|yellow|blue)/);
  });

  it("keeps multiple findings for the same pillar in one group", () => {
    render(
      <WellArchitectedReview
        findings={[
          finding("performance_efficiency", "warning", "scaling without a balancer"),
          finding("performance_efficiency", "info", "single point of contention"),
        ]}
      />,
    );

    expect(screen.getAllByText("performance efficiency")).toHaveLength(1);
    expect(screen.getByText("scaling without a balancer")).toBeInTheDocument();
    expect(screen.getByText("single point of contention")).toBeInTheDocument();
  });
});
