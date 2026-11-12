import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ArchSummary } from "./ArchSummary";

describe("ArchSummary", () => {
  it("renders the complete summary immediately for reading and print", () => {
    render(<ArchSummary text="Full architecture summary" />);
    expect(screen.getByText("Full architecture summary")).toBeInTheDocument();
    expect(screen.getByText("Full architecture summary")).not.toHaveClass("typewriter-cursor");
  });
});
