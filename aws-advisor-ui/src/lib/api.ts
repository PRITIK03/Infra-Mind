import type { FollowupExchange, JobResponse, RecommendRequest, RunsResponse } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "";

async function request<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  if (!BASE) {
    throw new Error(
      "Backend URL not configured. Set NEXT_PUBLIC_API_URL in the environment before building.",
    );
  }
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    let field: "github_url" | undefined;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail) && typeof body.detail[0]?.msg === "string") {
        detail = body.detail[0].msg.replace(/^Value error, /, "");
      }
      if (body?.field === "github_url") field = body.field;
    } catch {
      // ignore parse error — use status code message
    }
    throw Object.assign(new Error(detail), { field });
  }

  return res.json() as Promise<T>;
}

/** POST /api/recommend — kick off a new job */
export async function createJob(
  message: string,
  consensus = false,
  githubUrl?: string,
): Promise<{ job_id: string }> {
  const payload: RecommendRequest = { message, consensus };
  if (githubUrl) payload.github_url = githubUrl;
  return request<{ job_id: string }>("/api/recommend", {
    method: "POST",
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(25_000),
  });
}

/** GET /api/recommend/{job_id} — poll job status */
export async function pollJob(jobId: string): Promise<JobResponse> {
  return request<JobResponse>(`/api/recommend/${jobId}`, { signal: AbortSignal.timeout(15_000) });
}

/** GET /api/recommend/{job_id}/stream — SSE progress stream URL.

Returns null when the backend URL is unconfigured, mirroring request().
EventSource is constructed by the caller (see useJobPoller) so it can be
closed on terminal events and replaced by polling on connection failure.
*/
export function streamJobUrl(jobId: string): string | null {
  if (!BASE) return null;
  return `${BASE}/api/recommend/${jobId}/stream`;
}

/** GET /api/share/{job_id} — read-only snapshot of a finished job.

Same document as pollJob for a done job; the backend answers 404 for
anything else (running, awaiting input, errored, or unknown id), which
request() surfaces as an Error carrying the backend's detail text.
*/
export async function fetchSharedJob(jobId: string): Promise<JobResponse> {
  return request<JobResponse>(`/api/share/${encodeURIComponent(jobId)}`, { cache: "no-store" });
}

export async function createShareLink(jobId: string): Promise<{ share_id: string }> {
  return request(`/api/recommend/${encodeURIComponent(jobId)}/share`, {
    method: "POST",
    signal: AbortSignal.timeout(10_000),
  });
}
/** Shareable result URL for a finished job — {origin}/share/{job_id}.

Kept next to the API client (rather than scattered through components) so
the main page and the share page can never disagree on the link shape.
*/
export function shareUrl(jobId: string): string {
  return `${window.location.origin}/share/${encodeURIComponent(jobId)}`;
}

/** POST /api/recommend/{job_id}/answer — submit a follow-up answer */
export async function answerJob(
  jobId: string,
  answer: string
): Promise<{ job_id: string; status: string }> {
  return request(`/api/recommend/${jobId}/answer`, {
    method: "POST",
    body: JSON.stringify({ answer }),
  });
}

/** POST /api/recommend/{job_id}/followup — ask a question about a completed recommendation */
export async function askFollowup(
  jobId: string,
  question: string
): Promise<{
  job_id: string;
  answer: string;
  exchange: FollowupExchange;
  followup_history: FollowupExchange[];
}> {
  return request(`/api/recommend/${jobId}/followup`, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

/** GET /api/stats — live instance type counts for landing page readout */
export async function getStats(): Promise<{ ec2: number; rds: number; cache: number }> {
  return request<{ ec2: number; rds: number; cache: number }>("/api/stats");
}

/** GET /api/health — lightweight backend liveness check for cold-start UX */
export async function healthCheck(): Promise<{ status: string }> {
  return request<{ status: string }>("/api/health", {
    signal: AbortSignal.timeout(5000),
  });
}

/** GET /api/runs — historical run list with observability flag */
export async function getRuns(): Promise<RunsResponse> {
  return request<RunsResponse>("/api/runs", {
    signal: AbortSignal.timeout(10000),
  });
}

