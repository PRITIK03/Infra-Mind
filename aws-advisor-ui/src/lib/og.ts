import { readFileSync } from "node:fs";
import path from "node:path";

/**
 * Shared OG-image helpers: the design-system palette and the font loading
 * both opengraph-image routes (static root + per-share) use.  The font files
 * are vendored in public/fonts (IBM Plex, SIL OFL) so generation never needs
 * network access.  Satori (next/og) cannot parse woff2, so the .ttf twins
 * vendored alongside are what image generation loads — the woff2 files stay
 * for any future browser-side use.
 */

// Design system — tailwind.config.ts → theme.extend.colors is the source of
// truth; these constants mirror it exactly for image rendering.
export const CANVAS = "#0F0F0E";
export const INK = "#EDEDEA";
export const AMBER = "#E8A33D";
export const INK_MUTED = "rgba(237,237,234,0.45)";
export const INK_DIM = "rgba(237,237,234,0.25)";
export const BORDER_SUBTLE = "rgba(237,237,234,0.10)";

type OgFont = { name: string; data: ArrayBuffer; weight: 400 | 500 };

let cached: OgFont[] | null = null;

export function loadOgFonts(): OgFont[] {
  if (cached) return cached;
  const read = (name: string) =>
    // Buffer is an ArrayBuffer-backed view; Satori accepts the bytes at
    // runtime, but @types/node 20+ no longer claims Buffer IS an ArrayBuffer,
    // so the double-cast keeps the declared shape honest for tsc.
    readFileSync(path.join(process.cwd(), "public", "fonts", name)) as unknown as ArrayBuffer;
  cached = [
    {
      name: "IBM Plex Mono",
      data: read("ibm-plex-mono-latin-500-normal.ttf"),
      weight: 500,
    },
    {
      name: "IBM Plex Sans",
      data: read("ibm-plex-sans-latin-400-normal.ttf"),
      weight: 400,
    },
  ];
  return cached;
}
