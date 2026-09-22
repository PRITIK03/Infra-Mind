import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ContainerizedAlternative } from "./ContainerizedAlternative";

describe("ContainerizedAlternative", () => {
  it("renders recommended Fargate task size and why/trade-off copy", () => {
    render(
      <ContainerizedAlternative
        alternative={{
          recommended: true,
          fargate_cpu_units: 2048,
          fargate_memory_mib: 4096,
          why: "A Dockerfile was detected in the repository; ECS Fargate offers an equivalent serverless container alternative.",
          trade_off: "Fargate removes instance management entirely and bills per-second while tasks run.",
        }}
      />,
    );

    expect(screen.getByText(/containerized alternative/i)).toBeInTheDocument();
    expect(screen.getByText("2048")).toBeInTheDocument();
    expect(screen.getByText("4096")).toBeInTheDocument();
    expect(
      screen.getByText(/A Dockerfile was detected in the repository/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Fargate removes instance management entirely/i),
    ).toBeInTheDocument();
  });

  it("renders non-recommended state without CPU/memory units when workload cannot be containerized", () => {
    render(
      <ContainerizedAlternative
        alternative={{
          recommended: false,
          fargate_cpu_units: null,
          fargate_memory_mib: null,
          why: "A Dockerfile was detected, but workload requires GPU which Fargate does not support.",
          trade_off: "Trade-off notes.",
        }}
      />,
    );

    expect(screen.getByText(/containerized alternative/i)).toBeInTheDocument();
    expect(screen.queryByText("CPU units")).not.toBeInTheDocument();
    expect(screen.getByText(/workload requires GPU/i)).toBeInTheDocument();
  });
});
