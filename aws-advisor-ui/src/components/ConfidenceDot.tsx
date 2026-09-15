interface Props {
  level: "low" | "medium" | "high";
}

/*
 * Canonical amber confidence scale — the single source of truth for
 * low/medium/high amber intensity. ConfidenceStrip's segment fill uses the
 * same values; do not tune them independently.
 * Full amber opacity ladder (semantic → value):
 *   1.0  active/current indicator, high confidence
 *   0.7  pipeline node indicators
 *   0.6  focus rings
 *   0.4  hover borders, badge borders
 *   0.3  subtle emphasis borders (input focus-within)
 *   0.2  amber section rules
 *   0.35 degraded/dimmed state (low confidence, grounding review)
 *   0.15 faintest accent (bubble chart rings)
 */
export const AMBER_CONFIDENCE_OPACITY = { low: 0.35, medium: 0.65, high: 1.0 } as const;

export function ConfidenceDot({ level }: Props) {
  const opacity = AMBER_CONFIDENCE_OPACITY[level] ?? AMBER_CONFIDENCE_OPACITY.medium;
  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={`${level} confidence`}
      aria-label={`${level} confidence`}
    >
      <span
        className="inline-block w-1.5 h-1.5 rounded-full"
        style={{ backgroundColor: `rgba(232,163,61,${opacity})` }}
      />
      <span className="font-mono text-xs text-ink-dim">{level}</span>
    </span>
  );
}
