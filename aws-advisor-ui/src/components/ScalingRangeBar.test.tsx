import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScalingRangeBar } from "./ScalingRangeBar";

describe("ScalingRangeBar", () => {
  it("renders a fixed-instance label without an SVG bar", async () => {
    const { container } = render(
      <ScalingRangeBar
        minInstances={1}
        maxInstances={1}
        scalingRecommendation="fixed-size deployment"
      />,
    );

    await waitFor(() => expect(screen.getByLabelText("Fixed: 1 instances")).toHaveTextContent("Fixed: 1 instance"));
    expect(container.querySelector("svg")).not.toBeInTheDocument();
  });
});