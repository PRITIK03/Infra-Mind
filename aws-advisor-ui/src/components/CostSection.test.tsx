import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CostSection } from "./CostSection";

describe("CostSection", () => {
  it("renders ranges, totals, and unavailable component pricing", async () => {
    render(
      <CostSection
        cost={{
          compute_monthly_low: 8,
          compute_monthly_high: 15,
          database_monthly: 30,
          cache_monthly: null,
          total_monthly_low: 38,
          total_monthly_high: 45,
        }}
        databaseNeeded
        cacheNeeded
      />,
    );

    await waitFor(() => expect(screen.getByLabelText("Copy $8 - $15")).toHaveTextContent("$8 - $15"));
    await waitFor(() => expect(screen.getByLabelText("Copy $38 - $45")).toHaveTextContent("$38 - $45 /mo"));
    expect(screen.getByText("pricing unavailable")).toBeInTheDocument();
  });

  it("renders nothing when cost is absent", () => {
    const { container } = render(
      <CostSection cost={null} databaseNeeded={false} cacheNeeded={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a dash for tiers that are not needed", () => {
    render(
      <CostSection
        cost={{
          compute_monthly_low: 8,
          compute_monthly_high: 8,
          database_monthly: null,
          cache_monthly: null,
          total_monthly_low: 8,
          total_monthly_high: 8,
        }}
        databaseNeeded={false}
        cacheNeeded={false}
      />,
    );

    expect(screen.getAllByText("—")).toHaveLength(2);
    expect(screen.queryByText("pricing unavailable")).not.toBeInTheDocument();
  });
});
