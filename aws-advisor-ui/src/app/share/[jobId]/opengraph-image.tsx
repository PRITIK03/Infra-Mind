import { ImageResponse } from "next/og";
import { fetchSharedJob } from "@/lib/api";
import type { JobResponse } from "@/lib/types";
import {
  AMBER,
  BORDER_SUBTLE,
  CANVAS,
  INK,
  INK_DIM,
  INK_MUTED,
  loadOgFonts,
} from "@/lib/og";
import { formatShareCost, shareCardContent } from "@/lib/shareMeta";

/**
 * Dynamic Open Graph image for shared links, generated from the REAL job
 * (same source as generateMetadata — no fabricated content).
 *
 * Palette and fonts come from @/lib/og (mirrors the tailwind design system),
 * so the static landing card and this dynamic one can't drift apart.
 *
 * Deliberately simple: wordmark, the compute instance, the same
 * compute/+engine/+cost description, and a thin 1-3 box topology row for the
 * tiers that actually exist.  If the job can't be read, the image says so
 * honestly instead of inventing a result.
 */

export const runtime = "nodejs"; // fonts are read from disk; edge has no fs
export const alt = "AWS infrastructure recommendation";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

function TierBoxes({ tiers }: { tiers: Array<{ label: string; value: string }> }) {
  return (
    <div style={{ display: "flex", alignItems: "center", marginTop: 56 }}>
      {tiers.map((tier, i) => (
        <div key={tier.label} style={{ display: "flex", alignItems: "center" }}>
          {i > 0 && (
            <div
              style={{
                width: 56,
                height: 1,
                backgroundColor: "rgba(232,163,61,0.35)",
              }}
            />
          )}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              border: `1px solid ${BORDER_SUBTLE}`,
              padding: "16px 28px",
              minWidth: 220,
            }}
          >
            <span
              style={{
                fontFamily: "IBM Plex Sans",
                fontSize: 20,
                color: INK_DIM,
                textTransform: "uppercase",
                letterSpacing: 2,
              }}
            >
              {tier.label}
            </span>
            <span
              style={{
                fontFamily: "IBM Plex Mono",
                fontSize: 30,
                color: INK,
                marginTop: 6,
              }}
            >
              {tier.value}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

export default async function Image({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  const fonts = loadOgFonts();

  let job: JobResponse | null = null;
  try {
    // Same fetch the metadata builder uses — one source for card + image.
    job = await fetchSharedJob(jobId);
  } catch {
    job = null;
  }
  const card = job ? shareCardContent(job) : null;

  if (!card) {
    // Honest unavailable state — same copy the share view shows.
    return new ImageResponse(
      (
        <div
          style={{
            width: "100%",
            height: "100%",
            backgroundColor: CANVAS,
            color: INK,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            padding: 80,
          }}
        >
          <span
            style={{
              fontFamily: "IBM Plex Mono",
              fontSize: 44,
              color: INK,
            }}
          >
            recommendation unavailable
          </span>
          <span
            style={{
              fontFamily: "IBM Plex Sans",
              fontSize: 32,
              color: INK_MUTED,
              marginTop: 24,
            }}
          >
            This recommendation isn&apos;t available (it may still be running,
            or the link is invalid).
          </span>
        </div>
      ),
      { ...size, fonts },
    );
  }

  const sdr = job?.result?.system_design_recommendation;
  const tiers: Array<{ label: string; value: string }> = [];
  if (sdr?.compute?.recommended_instance) {
    tiers.push({ label: "compute", value: sdr.compute.recommended_instance });
  }
  if (sdr?.database?.needed) {
    const db = sdr.database.engine_suggestion ?? sdr.database.recommended_instance;
    if (db) tiers.push({ label: "database", value: db });
  }
  if (sdr?.cache?.needed && sdr.cache.engine) {
    tiers.push({ label: "cache", value: sdr.cache.engine });
  }
  const cost = formatShareCost(
    sdr?.estimated_cost?.total_monthly_low,
    sdr?.estimated_cost?.total_monthly_high,
  );

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          backgroundColor: CANVAS,
          color: INK,
          display: "flex",
          flexDirection: "column",
          padding: 64,
        }}
      >
        {/* Wordmark + share tag */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span style={{ fontFamily: "IBM Plex Mono", fontSize: 32, color: AMBER }}>
            aws-instance-advisor
          </span>
          <span
            style={{
              fontFamily: "IBM Plex Sans",
              fontSize: 22,
              color: INK_DIM,
              border: `1px solid ${BORDER_SUBTLE}`,
              padding: "8px 18px",
              textTransform: "uppercase",
              letterSpacing: 3,
            }}
          >
            shared recommendation
          </span>
        </div>

        {/* Headline fact — the compute instance from the metadata title */}
        <div
          style={{
            fontFamily: "IBM Plex Mono",
            fontSize: 88,
            color: INK,
            marginTop: 72,
            display: "flex",
          }}
        >
          {card.title.replace(/^AWS Infra Recommendation — /, "")}
        </div>

        {/* Exactly the description generateMetadata ships */}
        <div
          style={{
            fontFamily: "IBM Plex Sans",
            fontSize: 36,
            color: INK_MUTED,
            marginTop: 18,
            display: "flex",
          }}
        >
          {card.description}
        </div>

        {/* Topology shape: one thin box per tier that actually exists */}
        {tiers.length > 0 && <TierBoxes tiers={tiers} />}

        {/* Footer: cost + the standing honesty line */}
        <div style={{ flex: 1 }} />
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderTop: `1px solid ${BORDER_SUBTLE}`,
            paddingTop: 24,
          }}
        >
          <span style={{ fontFamily: "IBM Plex Mono", fontSize: 26, color: INK }}>
            {cost ? `${cost}/mo est.` : "cost unavailable"}
          </span>
          <span
            style={{ fontFamily: "IBM Plex Sans", fontSize: 24, color: INK_DIM }}
          >
            AI-generated infrastructure — review every terraform plan
          </span>
        </div>
      </div>
    ),
    { ...size, fonts },
  );
}
