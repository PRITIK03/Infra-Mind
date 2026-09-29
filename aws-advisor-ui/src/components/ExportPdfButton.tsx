"use client";

interface Props {
  /** Label shown before the report title in the PDF header. */
  title?: string;
}

/**
 * Triggers the browser's native print-to-PDF dialog.
 *
 * All styling for the printed output lives in the @media print block in
 * globals.css — no external library, no bundle-size cost.
 */
export function ExportPdfButton({ title }: Props = {}) {
  const handlePrint = () => {
    if (title && typeof document !== "undefined") {
      const prev = document.title;
      document.title = title;
      window.print();
      document.title = prev;
      return;
    }
    window.print();
  };

  return (
    <button
      type="button"
      onClick={handlePrint}
      aria-label="Export report as PDF"
      className={[
        "border border-border-subtle px-3 py-1.5",
        "font-mono text-xs text-ink-dim uppercase tracking-wider",
        "transition-colors duration-150",
        "hover:text-amber hover:border-amber/40 hover:bg-white/[0.03]",
        "active:translate-y-px",
        "print:hidden",
      ].join(" ")}
    >
      export as pdf
    </button>
  );
}
