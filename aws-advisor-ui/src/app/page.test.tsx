import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Home from "./page";
import type { JobResponse, SystemDesignRecommendation } from "@/lib/types";
import type { UseJobPollerReturn } from "@/hooks/useJobPoller";

const mockSubmit = vi.fn();
const mockAnswer = vi.fn();
const mockReset = vi.fn();

let mockPollerState: UseJobPollerReturn = {
  status: null,
  currentStage: "",
  nextQuestion: null,
  jobResponse: null,
  error: null,
  retryInfo: null,
  isWakingUp: false,
  isActive: false,
  submit: mockSubmit,
  answer: mockAnswer,
  reset: mockReset,
  totalElapsedMs: null,
  retryCount: null,
};

vi.mock("@/hooks/useJobPoller", () => ({
  useJobPoller: () => mockPollerState,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    healthCheck: vi.fn().mockResolvedValue({ status: "ok" }),
    getStats: vi.fn().mockResolvedValue({ ec2: 700, rds: 60, cache: 20 }),
    getRuns: vi.fn().mockResolvedValue({
      runs: [],
      observability_configured: false,
    }),
  };
});

const baseSdr: SystemDesignRecommendation = {
  compute: {
    recommended_instance: "c6i.xlarge",
    why: "Compute-intensive CPU bound workload.",
    assumptions: ["high cpu demand"],
    confidence: "high",
  },
  database: {
    needed: true,
    recommended_instance: "db.r6g.xlarge",
    engine_suggestion: "PostgreSQL",
    why: "Relational transactional database.",
    assumptions: [],
    confidence: "high",
  },
  cache: {
    needed: true,
    recommended_instance: "cache.r6g.large",
    engine: "Redis",
    why: "Sub-millisecond query caching.",
    assumptions: [],
    confidence: "high",
  },
  load_balancer: {
    needed: true,
    load_balancer_type: "Application Load Balancer",
    why: "Distribute incoming HTTP traffic.",
  },
  architecture_summary: "High performance multi-tier AWS architecture.",
};

const doneJobWithConsensus: JobResponse = {
  job_id: "test-consensus-job",
  status: "done",
  current_stage: "Complete",
  created_at: 1000,
  result: {
    system_design_recommendation: {
      ...baseSdr,
      consensus_result: {
        enabled: true,
        primary_model: "openrouter/free",
        secondary_model: "nvidia/nemotron-3-ultra-550b-a55b:free",
        agreement_level: "partial",
        agreements: ["database", "load_balancer"],
        disagreements: [
          { tier: "compute", primary_choice: "c6i.xlarge", secondary_choice: "m8g.xlarge" },
          { tier: "cache", primary_choice: "cache.r6g.large", secondary_choice: "cache.m6g.xlarge" },
        ],
        note: "Secondary model favored Graviton instances for cost efficiency.",
      },
    },
  },
};

const doneJobWithoutConsensus: JobResponse = {
  job_id: "test-no-consensus-job",
  status: "done",
  current_stage: "Complete",
  created_at: 1000,
  result: {
    system_design_recommendation: {
      ...baseSdr,
      consensus_result: null,
    },
  },
};

describe("Landing page consensus toggle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPollerState = {
      status: null,
      currentStage: "",
      nextQuestion: null,
      jobResponse: null,
      error: null,
      retryInfo: null,
      isWakingUp: false,
      isActive: false,
      submit: mockSubmit,
      answer: mockAnswer,
      reset: mockReset,
      totalElapsedMs: null,
      retryCount: null,
    };
  });

  afterEach(() => {
    cleanup();
  });

  it("renders the consensus checkbox unchecked by default", () => {
    render(<Home />);
    const checkbox = screen.getByRole("checkbox", {
      name: /compare with a second model/i,
    });
    expect(checkbox).toBeInTheDocument();
    expect(checkbox).not.toBeChecked();
  });

  it("submits with consensus: false when checkbox is left unchecked", async () => {
    const user = userEvent.setup();
    render(<Home />);
    const textarea = screen.getByRole("textbox", {
      name: /describe your application and workload/i,
    });
    await user.type(textarea, "High traffic gaming backend");

    const submitBtn = screen.getByRole("button", { name: /run →/i });
    await user.click(submitBtn);

    expect(mockSubmit).toHaveBeenCalledWith("High traffic gaming backend", false);
  });

  it("submits with consensus: true when checkbox is checked", async () => {
    const user = userEvent.setup();
    render(<Home />);
    const textarea = screen.getByRole("textbox", {
      name: /describe your application and workload/i,
    });
    await user.type(textarea, "High traffic gaming backend");

    const checkbox = screen.getByRole("checkbox", {
      name: /compare with a second model/i,
    });
    await user.click(checkbox);
    expect(checkbox).toBeChecked();

    const submitBtn = screen.getByRole("button", { name: /run →/i });
    await user.click(submitBtn);

    expect(mockSubmit).toHaveBeenCalledWith("High traffic gaming backend", true);
  });
});

describe("Results page consensus rendering", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("surfaces consensus result clearly when enabled: true", () => {
    mockPollerState = {
      status: "done",
      currentStage: "Complete",
      nextQuestion: null,
      jobResponse: doneJobWithConsensus,
      error: null,
      retryInfo: null,
      isWakingUp: false,
      isActive: false,
      submit: mockSubmit,
      answer: mockAnswer,
      reset: mockReset,
      totalElapsedMs: 1500,
      retryCount: 0,
    };

    render(<Home />);

    // Consensus check region present
    const consensusRegion = screen.getByRole("region", { name: /consensus check/i });
    expect(consensusRegion).toBeInTheDocument();

    const withinConsensus = within(consensusRegion);
    // Agreement level surfaced
    expect(withinConsensus.getByText("partial agreement")).toBeInTheDocument();

    // Models surfaced
    expect(withinConsensus.getByText(/second opinion by/i)).toBeInTheDocument();
    expect(withinConsensus.getByText("openrouter/free")).toBeInTheDocument();

    // Disagreements rendered per-tier side-by-side
    expect(withinConsensus.getByText("c6i.xlarge")).toBeInTheDocument();
    expect(withinConsensus.getByText("m8g.xlarge")).toBeInTheDocument();
    expect(withinConsensus.getByText("cache.r6g.large")).toBeInTheDocument();
    expect(withinConsensus.getByText("cache.m6g.xlarge")).toBeInTheDocument();

    // Agreed tiers listed
    expect(withinConsensus.getByText(/agreed on:/i)).toHaveTextContent("Database, Load balancer");
  });

  it("does not render consensus section when consensus_result is absent", () => {
    mockPollerState = {
      status: "done",
      currentStage: "Complete",
      nextQuestion: null,
      jobResponse: doneJobWithoutConsensus,
      error: null,
      retryInfo: null,
      isWakingUp: false,
      isActive: false,
      submit: mockSubmit,
      answer: mockAnswer,
      reset: mockReset,
      totalElapsedMs: 1500,
      retryCount: 0,
    };

    render(<Home />);

    expect(screen.queryByRole("region", { name: /consensus check/i })).not.toBeInTheDocument();
  });
});
