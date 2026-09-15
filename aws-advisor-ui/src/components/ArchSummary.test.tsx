import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ArchSummary } from "./ArchSummary";

describe("ArchSummary", () => {
  it("renders the complete summary immediately when reduced motion is enabled", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      media: "(prefers-reduced-motion: reduce)",
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    });
    render(<ArchSummary text="Full architecture summary" />);
    expect(screen.getByText("Full architecture summary")).toBeInTheDocument();
    expect(screen.getByText("Full architecture summary")).not.toHaveClass("typewriter-cursor");
  });
});
