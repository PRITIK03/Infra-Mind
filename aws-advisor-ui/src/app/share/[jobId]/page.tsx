import type { Metadata } from "next";
import { shareRouteMetadata } from "@/lib/shareMeta";
import ShareView from "./ShareView";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ jobId: string }>;
}): Promise<Metadata> {
  const { jobId } = await params;
  return shareRouteMetadata(jobId);
}

/**
 * Thin server shell around the read-only share view.
 *
 * Metadata (above) is generated server-side from the REAL job so social
 * unfurlers get title/description without running client JS; the view itself
 * stays a client component (renamed ShareView) so its fetch, read-only
 * composition, and honest unavailable state behave byte-identically.
 */
export default async function SharePage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  return <ShareView jobId={jobId} />;
}
