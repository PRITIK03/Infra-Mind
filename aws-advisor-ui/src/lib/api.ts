import type { FollowupExchange, JobResponse, RunsResponse } from "./types";

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
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // ignore parse error — use status code message
    }
    throw new Error(detail);
  }

  return res.json() as Promise<T>;
}

/** POST /api/recommend — kick off a new job */
export async function createJob(message: string): Promise<{ job_id: string }> {
  return request<{ job_id: string }>("/api/recommend", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

/** GET /api/recommend/{job_id} — poll job status */
export async function pollJob(jobId: string): Promise<JobResponse> {
  return request<JobResponse>(`/api/recommend/${jobId}`);
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

