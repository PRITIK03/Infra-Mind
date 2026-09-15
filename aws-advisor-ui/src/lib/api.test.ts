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