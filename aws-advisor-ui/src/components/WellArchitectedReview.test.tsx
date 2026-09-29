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

  it("distinguishes severity by dot opacity only — message text is consistently styled", () => {
    const { container } = render(
      <WellArchitectedReview
        findings={[
          finding("reliability", "warning", "warn message"),
          finding("security", "info", "info message"),
        ]}
      />,
    );

    const warn = screen.getByText("warn message");
    const info = screen.getByText("info message");

    // Message text must NOT carry opacity or colour variation by severity —
    // the dot alone carries the severity signal so content stays readable.
    expect(warn.style.opacity).toBe("");
    expect(info.style.opacity).toBe("");
    // Both message spans should share the same Tailwind class set.
    expect(warn.className).toBe(info.className);
    // No colour-based badge utilities should have been introduced.
    expect(warn.className).not.toMatch(/text-(red|green|yellow|blue)/);
    expect(info.className).not.toMatch(/text-(red|green|yellow|blue)/);

    // The severity dot for each finding carries differentiated opacity via
    // inline backgroundColor rgba string. Use the raw style attribute which
    // JSDOM preserves exactly as authored.
    const dots = container.querySelectorAll<HTMLElement>('[aria-hidden="true"].rounded-full');
    expect(dots.length).toBe(2); // one per finding

    // Extract opacity from rgba(r,g,b,opacity) in the style attribute string.
    const parseOpacity = (el: HTMLElement): number => {
      const styleAttr = el.getAttribute("style") ?? "";
      const m = styleAttr.match(/rgba\([^,]+,[^,]+,[^,]+,\s*([\d.]+)\)/);
      return m ? Number(m[1]) : 0;
    };

    // warning dot (reliability pillar, first in canonical order) > info dot (security, second)
    const warnDotOpacity = parseOpacity(dots[0]);
    const infoDotOpacity = parseOpacity(dots[1]);
    expect(warnDotOpacity).toBeGreaterThan(infoDotOpacity);
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
