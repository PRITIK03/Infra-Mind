import { ImageResponse } from "next/og";
import { AMBER, BORDER_SUBTLE, CANVAS, INK, INK_DIM, INK_MUTED, loadOgFonts } from "@/lib/og";

/**
 * Static Open Graph image for the landing page (and the results view it
 * renders) — file-convention route, so Next links it into <meta og:image>
 * automatically.  Same console palette + IBM Plex Mono as the rest of the
 * app; the /share/[jobId] route has its own dynamic image built from real
 * job data.
 */

export const runtime = "nodejs"; // fonts are read from disk; edge has no fs
export const alt = "AWS Instance Advisor";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
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
        <span style={{ fontFamily: "IBM Plex Mono", fontSize: 32, color: AMBER }}>
          aws-instance-advisor
        </span>

        <div
          style={{
            fontFamily: "IBM Plex Mono",
            fontSize: 76,
            color: INK,
            marginTop: 96,
            display: "flex",
          }}
        >
          AWS Instance Advisor
        </div>

        <div
          style={{
            fontFamily: "IBM Plex Sans",
            fontSize: 34,
            color: INK_MUTED,
            marginTop: 22,
            display: "flex",
            maxWidth: 980,
          }}
        >
          Describe your workload. Get a vetted compute, database, cache, and
          load-balancer recommendation — plus ready-to-apply Terraform.
        </div>

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
          <span
            style={{ fontFamily: "IBM Plex Mono", fontSize: 24, color: INK_DIM }}
          >
            compute · database · cache · terraform
          </span>
          <span
            style={{ fontFamily: "IBM Plex Sans", fontSize: 24, color: INK_DIM }}
          >
            AI-generated infrastructure — review every terraform plan
          </span>
        </div>
      </div>
    ),
    { ...size, fonts: loadOgFonts() },
  );
}
