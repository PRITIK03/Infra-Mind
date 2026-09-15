import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { answerJob, createJob, healthCheck, pollJob } from "@/lib/api";
import { useJobPoller } from "./useJobPoller";

vi.mock("@/lib/api", () => ({
  answerJob: vi.fn(),
  createJob: vi.fn(),
  healthCheck: vi.fn(),
  pollJob: vi.fn(),
}));

const mockedCreateJob = vi.mocked(createJob);
const mockedPollJob = vi.mocked(pollJob);
const mockedHealthCheck = vi.mocked(healthCheck);

const response = (status: "collecting" | "awaiting_input" | "done" | "error") => ({
  job_id: "job-1",
  status,
  current_stage: "Collecting requirements",
  created_at: 1,
  ...(status === "awaiting_input" ? { next_question: "What workload?" } : {}),
  ...(status === "error" ? { error: "backend exploded" } : {}),
});

describe("useJobPoller", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mockedHealthCheck.mockResolvedValue({ status: "ok" });
    vi.mocked(answerJob).mockResolvedValue({ job_id: "job-1", status: "running" });
  });

  it("transitions through collecting, awaiting input, and done, then stops polling", async () => {
    mockedCreateJob.mockResolvedValue({ job_id: "job-1" });
    mockedPollJob
      .mockResolvedValueOnce(response("awaiting_input"))
      .mockResolvedValueOnce(response("done"));
    const { result, unmount } = renderHook(() => useJobPoller());

    await act(async () => { await result.current.submit("api workload"); });
    expect(result.current.status).toBe("collecting");
    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    expect(result.current.status).toBe("awaiting_input");
    await act(async () => { await result.current.answer("api service"); });
    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    expect(result.current.status).toBe("done");
    expect(mockedPollJob).toHaveBeenCalledTimes(2);
    unmount();
  });

  it("preserves a rate-limit error in the UI state", async () => {
    mockedCreateJob.mockRejectedValue(new Error("Too many recommendation requests"));
    const { result } = renderHook(() => useJobPoller());
    await act(async () => { await result.current.submit("test"); });
    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe("Too many recommendation requests");
  });

  it("stops polling after an error response and on unmount", async () => {
    mockedCreateJob.mockResolvedValue({ job_id: "job-1" });
    mockedPollJob.mockResolvedValue(response("error"));
    const { result, unmount } = renderHook(() => useJobPoller());
    await act(async () => { await result.current.submit("test"); });
    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    expect(result.current.status).toBe("error");
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(mockedPollJob).toHaveBeenCalledTimes(1);
    unmount();
  });
});
