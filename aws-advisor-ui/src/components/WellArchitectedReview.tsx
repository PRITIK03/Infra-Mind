"use client";

import type { WellArchitectedFinding, WellArchitectedPillar } from "@/lib/types";

interface Props {
  findings: WellArchitectedFinding[];
}

// Deterministic findings, so nothing here is generated client-side — this
// component only groups and renders what the backend computed.
//
// Styling follows the Confidence By Tier pattern deliberately: mono type,
// uppercase pillar labels, and severity distinguished by OPACITY ONLY —
// no new colours, no badge chrome.

const C = {
  label: "rgba(237,237,234,0.35)",
  body: "rgba(237,237,234,0.72)",
  marker: "#E8A33D",
} as const;

// Same two-step opacity idea as the confidence scale: warnings read slightly
// stronger than informational notes, at the same hue.
const SEVERITY_OPACITY: Record<WellArchitectedFinding["severity"], number> = {
  info: 0.35,
  warning: 0.9,
};

const PILLAR_ORDER: WellArchitectedPillar[] = [
  "reliability",
  "security",
  "performance_efficiency",
  "cost_optimization",
  "operational_excellence",
];

function _label(pillar: WellArchitectedPillar): string {
  return pillar.replace(/_/g, " ");
}

function SeverityMarker({ severity }: { severity: WellArchitectedFinding["severity"] }) {
  return (
    <span
      aria-hidden="true"
      className="inline-block rounded-full shrink-0 mt-1.5"
      style={{
        width: 5,
        height: 5,
        background: C.marker,
        opacity: SEVERITY_OPACITY[severity],
      }}
    />
  );
}

export function WellArchitectedReview({ findings }: Props) {
  if (!findings.length) return null;

  // Group by pillar, but keep the canonical pillar order so the output of a
  // given run is always laid out identically.
  const grouped = PILLAR_ORDER.map((pillar) => ({
    pillar,
    items: findings.filter((f) => f.pillar === pillar),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="flex flex-col gap-3" data-testid="well-architected-review">
      {grouped.map((group) => (
        <div key={group.pillar} className="flex flex-col gap-1.5">
          <span
            className="font-mono text-xs uppercase tracking-wider"
            style={{ color: C.label }}
          >
            {_label(group.pillar)}
          </span>
          <ul className="flex flex-col gap-1.5 pl-0.5">
            {group.items.map((finding, i) => (
              <li key={i} className="flex items-start gap-2">
                <SeverityMarker severity={finding.severity} />
                <span
                  className="text-xs leading-relaxed"
                  style={{
                    color: C.body,
                    // Opacity is the only severity signal — matching the
                    // existing confidence treatment.
                    opacity: SEVERITY_OPACITY[finding.severity],
                  }}
                >
                  {finding.message}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
