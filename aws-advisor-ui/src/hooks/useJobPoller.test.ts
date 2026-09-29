import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { answerJob, createJob, healthCheck, pollJob } from "@/lib/api";
import { streamJobUrl } from "@/lib/api";
import { useJobPoller } from "./useJobPoller";

vi.mock("@/lib/api", () => ({
  answerJob: vi.fn(),
  createJob: vi.fn(),
  healthCheck: vi.fn(),
  pollJob: vi.fn(),
  streamJobUrl: vi.fn(),
}));

const mockedCreateJob = vi.mocked(createJob);
const mockedPollJob = vi.mocked(pollJob);
const mockedHealthCheck = vi.mocked(healthCheck);
const mockedStreamJobUrl = vi.mocked(streamJobUrl);

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
    // Default: no SSE in jsdom — the hook must stay purely on polling, which
    // also keeps the three pre-existing polling tests meaningful.
    mockedStreamJobUrl.mockReturnValue(null);
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

// ── SSE preference with silent polling fallback ────────────────────────────
// jsdom has no EventSource, so the stream transport is injected per test —
// exactly the seams the hook consults (streamJobUrl + global EventSource).

type Handler = (event: { data: string }) => void;

interface MockSource {
  url: string;
  onmessage: Handler | null;
  onerror: (() => void) | null;
  close: ReturnType<typeof vi.fn>;
  emit: (payload: unknown) => void;
  fail: () => void;
}

function installMockEventSource() {
  const instances: MockSource[] = [];
  class MockEventSource {
    onmessage: Handler | null = null;
    onerror: (() => void) | null = null;
    close = vi.fn();
    url: string;
    constructor(url: string) {
      this.url = url;
      const self = this as unknown as MockSource;
      // The hook only reads onmessage/onerror/close at event time, so the
      // live facade can delegate straight back to this instance.
      self.emit = (payload: unknown) =>
        this.onmessage?.({ data: JSON.stringify(payload) });
      self.fail = () => this.onerror?.();
      instances.push(self);
    }
  }
  vi.stubGlobal("EventSource", MockEventSource);
  return instances;
}

describe("useJobPoller SSE", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mockedHealthCheck.mockResolvedValue({ status: "ok" });
    mockedStreamJobUrl.mockReturnValue("http://localhost:8000/api/recommend/job-1/stream");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("applies streamed transitions immediately without any poll request", async () => {
    const sources = installMockEventSource();
    mockedCreateJob.mockResolvedValue({ job_id: "job-1" });
    const { result, unmount } = renderHook(() => useJobPoller());

    await act(async () => { await result.current.submit("api workload"); });
    expect(sources).toHaveLength(1);
    expect(sources[0].url).toContain("/api/recommend/job-1/stream");

    act(() => {
      sources[0].emit({
        job_id: "job-1",
        status: "running",
        current_stage: "Researching compute options",
        created_at: 1,
      });
    });
    expect(result.current.status).toBe("running");
    expect(result.current.currentStage).toBe("Researching compute options");

    // Polling stays a silent standby while the stream is healthy: advancing
    // the clock must not fire a single pollJob request.
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(mockedPollJob).not.toHaveBeenCalled();

    unmount();
  });

  it("falls back to polling silently when the stream errors after connecting", async () => {
    const sources = installMockEventSource();
    mockedCreateJob.mockResolvedValue({ job_id: "job-1" });
    mockedPollJob.mockResolvedValue(response("done"));
    const { result, unmount } = renderHook(() => useJobPoller());

    await act(async () => { await result.current.submit("api workload"); });
    expect(result.current.status).toBe("collecting");

    // Stream breaks mid-run (the corporate-proxy failure mode): the close
    // races nothing, the standby interval takes over, next tick polls.
    act(() => { sources[0].fail(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });

    expect(mockedPollJob).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("done");
    expect(sources[0].close).toHaveBeenCalled();
    unmount();
  });

  it("falls back to polling when the stream errors on connect and ignores late frames", async () => {
    const sources = installMockEventSource();
    mockedCreateJob.mockResolvedValue({ job_id: "job-1" });
    mockedPollJob.mockResolvedValue(response("done"));
    const { result, unmount } = renderHook(() => useJobPoller());

    await act(async () => { await result.current.submit("api workload"); });
    // Connection never establishes: error arrives before any frame.
    act(() => { sources[0].fail(); });
    // A mangled/late frame from the dead stream must not resurrect it.
    act(() => {
      sources[0].emit({
        job_id: "job-1",
        status: "running",
        current_stage: "Researching compute options",
        created_at: 1,
      });
    });
    expect(result.current.status).toBe("collecting");

    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    expect(mockedPollJob).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("done");
    unmount();
  });

  it("falls back to polling when the stream connects but never delivers a frame", async () => {
    // The accepted-connection / buffering-proxy case: EventSource exists and
    // reports no error, but no frame ever arrives. The hook must give up on
    // the stream within the connect grace window and poll instead.
    const sources = installMockEventSource();
    mockedCreateJob.mockResolvedValue({ job_id: "job-1" });
    mockedPollJob.mockResolvedValue(response("done"));
    const { result, unmount } = renderHook(() => useJobPoller());

    await act(async () => { await result.current.submit("api workload"); });
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });

    expect(mockedPollJob).toHaveBeenCalledTimes(1);
    expect(sources[0].close).toHaveBeenCalled();
    expect(result.current.status).toBe("done");
    unmount();
  });

  it("keeps a low-rate backstop poll while streaming so a silent stall self-heals", async () => {
    // Stream delivered once (so it looks healthy) then goes quiet without an
    // error event: the periodic backstop poll still applies fresh state.
    const sources = installMockEventSource();
    mockedCreateJob.mockResolvedValue({ job_id: "job-1" });
    const { result, unmount } = renderHook(() => useJobPoller());

    await act(async () => { await result.current.submit("api workload"); });
    act(() => {
      sources[0].emit({
        job_id: "job-1",
        status: "running",
        current_stage: "Researching compute options",
        created_at: 1,
      });
    });
    expect(result.current.currentStage).toBe("Researching compute options");

    mockedPollJob.mockResolvedValue({
      job_id: "job-1",
      status: "running",
      current_stage: "Building final recommendation",
      created_at: 1,
    });
    // 6 ticks = 15s — well past the first few silent standby ticks.
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });

    expect(mockedPollJob).toHaveBeenCalledTimes(1);
    expect(result.current.currentStage).toBe("Building final recommendation");
    unmount();
  });
});
