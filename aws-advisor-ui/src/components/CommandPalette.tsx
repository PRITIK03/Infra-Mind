"use client";

import { useEffect } from "react";
import { Command } from "cmdk";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onNewAnalysis: () => void;
  onCopyReport?: () => void;
  onViewRawJson?: () => void;
  onGoToHistory: () => void;
  resultSections: Array<{ id: string; label: string }>;
}

export function CommandPalette({
  open,
  onOpenChange,
  onNewAnalysis,
  onCopyReport,
  onViewRawJson,
  onGoToHistory,
  resultSections,
}: Props) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onOpenChange, open]);

  const select = (action: () => void) => {
    onOpenChange(false);
    action();
  };

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Command palette"
      overlayClassName="fixed inset-0 z-40 bg-black/40 animate-fade-in"
      contentClassName="fixed left-1/2 top-1/2 z-50 w-[min(560px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 border border-border-subtle bg-canvas shadow-2xl animate-slide-in"
    >
      <Command.Input
        placeholder="Search commands..."
        className="w-full border-b border-border-subtle bg-transparent px-4 py-3 font-mono text-sm text-ink outline-none placeholder:text-ink-dim"
      />
      <Command.List className="max-h-[min(420px,calc(100vh-10rem))] overflow-y-auto p-2">
        <Command.Empty className="px-3 py-8 text-center font-mono text-xs text-ink-dim">
          No matching command.
        </Command.Empty>

        <Command.Group heading="Actions" className="px-1 pb-2 font-mono text-[10px] uppercase tracking-widest text-ink-dim">
          <Command.Item
            value="new analysis"
            onSelect={() => select(onNewAnalysis)}
            className="cursor-pointer px-3 py-2 text-sm text-ink-muted aria-selected:bg-white/[0.05] aria-selected:text-ink"
          >
            New analysis
          </Command.Item>
          {onCopyReport && (
            <Command.Item
              value="copy report as markdown"
              onSelect={() => select(onCopyReport)}
              className="cursor-pointer px-3 py-2 text-sm text-ink-muted aria-selected:bg-white/[0.05] aria-selected:text-ink"
            >
              Copy report as Markdown
            </Command.Item>
          )}
          {onViewRawJson && (
            <Command.Item
              value="view raw json"
              onSelect={() => select(onViewRawJson)}
              className="cursor-pointer px-3 py-2 text-sm text-ink-muted aria-selected:bg-white/[0.05] aria-selected:text-ink"
            >
              View raw JSON
            </Command.Item>
          )}
          <Command.Item
            value="go to run history"
            onSelect={() => select(onGoToHistory)}
            className="cursor-pointer px-3 py-2 text-sm text-ink-muted aria-selected:bg-white/[0.05] aria-selected:text-ink"
          >
            Go to run history
          </Command.Item>
        </Command.Group>

        {resultSections.length > 0 && (
          <Command.Group heading="Jump to section" className="px-1 pt-2 font-mono text-[10px] uppercase tracking-widest text-ink-dim">
            {resultSections.map((section) => (
              <Command.Item
                key={section.id}
                value={`jump to ${section.label}`}
                onSelect={() => select(() => document.getElementById(section.id)?.scrollIntoView({ behavior: "smooth", block: "start" }))}
                className="cursor-pointer px-3 py-2 text-sm text-ink-muted aria-selected:bg-white/[0.05] aria-selected:text-ink"
              >
                {section.label}
              </Command.Item>
            ))}
          </Command.Group>
        )}
      </Command.List>
      <div className="border-t border-border-subtle px-4 py-2 font-mono text-[10px] text-ink-dim">
        <kbd>Esc</kbd> close <span className="mx-2">·</span> <kbd>↑↓</kbd> navigate <span className="mx-2">·</span> <kbd>Enter</kbd> select
      </div>
    </Command.Dialog>
  );
}
