import { afterEach, describe, expect, it, vi } from "vitest";
import { createJob } from "./api";

describe("API error propagation", () => {
  afterEach(() => vi.restoreAllMocks());

  it("exposes backend detail text for 404, 400, and 429 responses", async () => {
    for (const detail of [
      "Job not found",
      "Job is not awaiting input",
      "Too many recommendation requests",
    ]) {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          new Response(JSON.stringify({ detail }), {
            status: detail.startsWith("Too") ? 429 : detail.startsWith("Job is") ? 400 : 404,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      );

      await expect(createJob("test workload")).rejects.toThrow(detail);
    }
  });
});

describe("createJob request body", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("includes the consensus flag — explicit true and default false", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ job_id: "job-1" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createJob("test workload", true);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      message: "test workload",
      consensus: true,
    });

    await createJob("test workload");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      message: "test workload",
      consensus: false,
    });
  });
});