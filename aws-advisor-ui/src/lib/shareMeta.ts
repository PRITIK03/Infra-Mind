import type { Metadata } from "next";
import type { JobResponse } from "@/lib/types";
import { fetchSharedJob } from "@/lib/api";

/** Fallback metadata when the shared job can't be read (missing/invalid). */
const FALLBACK_METADATA: Metadata = {
  title: "Shared recommendation — AWS Instance Advisor",
  description:
    "A shared infrastructure recommendation. The link may have expired or the job may still be running.",
};

export function formatShareCost(
  low?: number | null,
  high?: number | null,
): string | null {
  if (low == null && high == null) return null;
  const fmt = (v: number) =>
    v === 0 ? "$0" : v < 10 ? `$${v.toFixed(2)}` : `$${Math.round(v)}`;
  if (low == null) return fmt(high!);
  if (high == null) return fmt(low);
  return Math.abs(high - low) < 0.01 ? fmt(low) : `${fmt(low)}-${fmt(high)}`;
}

export function shareCardContent(job: JobResponse): {
  title: string;
  description: string;
} {
  const sdr = job.result?.system_design_recommendation;
  const compute = sdr?.compute?.recommended_instance ?? "a vetted setup";
  const title = `AWS Infra Recommendation — ${compute}`;

  const parts: string[] = [compute];
  const dbText = sdr?.database?.needed
    ? sdr.database.engine_suggestion ?? sdr.database.recommended_instance
    : null;
  if (dbText) parts.push(dbText);
  const cacheEngine = sdr?.cache?.needed ? sdr.cache.engine : null;
  if (cacheEngine) parts.push(cacheEngine);

  const cost = formatShareCost(
    sdr?.estimated_cost?.total_monthly_low,
    sdr?.estimated_cost?.total_monthly_high,
  );
  const description = cost
    ? `${parts.join(" + ")} — ${cost}/mo`
    : parts.join(" + ");

  return { title, description };
}

/** Metadata for /share/[jobId]: dynamic when the job reads, honest fallback otherwise. */
export async function shareRouteMetadata(jobId: string): Promise<Metadata> {
  let job: JobResponse | null = null;
  try {
    job = await fetchSharedJob(jobId);
  } catch {
    job = null;
  }
  if (job == null || job.status !== "done") return FALLBACK_METADATA;
  const { title, description } = shareCardContent(job);
  return {
    title,
    description,
    openGraph: {
      title,
      description,
      type: "article",
      images: [{ url: `/share/${jobId}/opengraph-image`, alt: title }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [`/share/${jobId}/opengraph-image`],
    },
  };
}
