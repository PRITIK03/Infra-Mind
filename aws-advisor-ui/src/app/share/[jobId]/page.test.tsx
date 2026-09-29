import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { JobResponse, SystemDesignRecommendation } from "@/lib/types";
import { CopyShareLinkButton } from "@/components/CopyShareLinkButton";
import SharePage from "@/app/share/[jobId]/page";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchSharedJob: vi.fn(),
    shareUrl: (jobId: string) => `http://localhost:3000/share/${jobId}`,
  };
});

vi.mock("next/navigation", () => ({
  useParams: () => ({ jobId: "shared-job-1" }),
}));

const { fetchSharedJob } = await import("@/lib/api");
const mockedFetchSharedJob = vi.mocked(fetchSharedJob);

const sdr: SystemDesignRecommendation = {
  compute: {
    recommended_instance: "m5.large",
    why: "Balanced general purpose compute.",
    assumptions: ["steady load"],
    confidence: "high",
  },
  database: {
    needed: true,
    recommended_instance: "db.t3.medium",
    engine_suggestion: "PostgreSQL",
    why: "Standard relational storage.",
    assumptions: [],
    confidence: "medium",
  },
  cache: { needed: false, why: "No cache required.", assumptions: [], confidence: "high" },
  load_balancer: { needed: false, why: "Single instance." },
  architecture_summary: "Balanced single-instance architecture.",
};

const doneJob: JobResponse = {
  job_id: "shared-job-1",
  status: "done",
  current_stage: "Complete",
  created_at: 1,
  result: { system_design_recommendation: sdr },
};

describe("CopyShareLinkButton", () => {
  it("copies {origin}/share/{job_id} to the clipboard", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    render(<CopyShareLinkButton jobId="abc-123" />);
    await user.click(screen.getByRole("button", { name: /copy share link/i }));

    expect(writeText).toHaveBeenCalledWith("http://localhost:3000/share/abc-123");
    expect(screen.getByRole("button", { name: /copy share link/i })).toHaveTextContent(
      "link copied",
    );
  });
});

describe("SharePage", () => {
  it("renders a read-only result for a done job — no follow-up, no new analysis", async () => {
    mockedFetchSharedJob.mockResolvedValue(doneJob);

    render(<SharePage />);

    await waitFor(() => {
      expect(screen.getByText("Viewing a shared recommendation")).toBeInTheDocument();
    });
    // Same rendering path as an active session (the compute instance shows in
    // more than one section — summary strip, report body, request summary):
    expect(screen.getAllByText("m5.large").length).toBeGreaterThan(0);
    // Read-only by composition — interactive affordances are never mounted:
    expect(screen.queryByLabelText(/ask a follow-up/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new analysis/i })).not.toBeInTheDocument();
  });

  it("shows the honest not-available state when the link is invalid", async () => {
    mockedFetchSharedJob.mockRejectedValue(new Error("Shared result not found"));

    render(<SharePage />);

    await waitFor(() => {
      expect(screen.getByText("recommendation unavailable")).toBeInTheDocument();
    });
    expect(
      screen.getByText(/may still be running, or the link is invalid/i),
    ).toBeInTheDocument();
  });
});
