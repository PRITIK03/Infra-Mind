"use client";

import { useEffect, useState } from "react";
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

type PaletteView = "commands" | "shortcuts";

// The shortcuts that actually exist — kept honest on purpose. The palette's
// own affordances (? / Esc / ↑↓ / Enter) are also listed here so this sheet
// is the single place a keyboard user can read them all.
const SHORTCUTS: Array<{ keys: string; description: string }> = [
  { keys: "⌘K / Ctrl+K", description: "Toggle this palette" },
  { keys: "?", description: "Show keyboard shortcuts" },
  { keys: "↑↓", description: "Navigate results" },
  { keys: "Enter", description: "Run the selected command" },
  { keys: "Esc", description: "Close" },
];

export function CommandPalette({
  open,
  onOpenChange,
  onNewAnalysis,
  onCopyReport,
  onViewRawJson,
  onGoToHistory,
  resultSections,
}: Props) {
  // Which sheet the dialog shows: the command list or the shortcuts list.
  // Resets to commands whenever the dialog closes, so re-opening (⌘K or ?)
  // always starts from the command list.
  const [view, setView] = useState<PaletteView>("commands");

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setView("commands");
        onOpenChange(!open);
        return;
      }
      // "?" opens the shortcuts sheet — but never while the user is typing
      // in an input, textarea, or contenteditable field.
      if (event.key === "?" && !event.metaKey && !event.ctrlKey && !event.altKey) {
        const target = event.target as HTMLElement | null;
        const tag = target?.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target?.isContentEditable) {
          return;
        }
        event.preventDefault();
        setView("shortcuts");
        onOpenChange(true);
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
      onOpenChange={(next) => {
        if (!next) setView("commands");
        onOpenChange(next);
      }}
      label="Command palette"
      overlayClassName="fixed inset-0 z-40 bg-black/40 animate-fade-in"
      contentClassName="fixed left-1/2 top-1/2 z-50 w-[min(560px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 border border-border-subtle bg-canvas shadow-2xl animate-slide-in"
    >
      {view === "commands" ? (
        <>
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
                  onSelect={() => select(onCopyReport!)}
                  className="cursor-pointer px-3 py-2 text-sm text-ink-muted aria-selected:bg-white/[0.05] aria-selected:text-ink"
                >
                  Copy report as Markdown
                </Command.Item>
              )}
              {onViewRawJson && (
                <Command.Item
                  value="view raw json"
                  onSelect={() => select(onViewRawJson!)}
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
            <kbd>Esc</kbd> close <span className="mx-2">·</span> <kbd>↑↓</kbd> navigate <span className="mx-2">·</span> <kbd>Enter</kbd> select{" "}
            <span className="mx-2">·</span>{" "}
            <button
              type="button"
              onClick={() => setView("shortcuts")}
              className="text-ink-dim underline decoration-border-subtle underline-offset-2 transition-colors hover:text-amber"
            >
              <kbd>?</kbd> shortcuts
            </button>
          </div>
        </>
      ) : (
        <div>
          <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
            <span className="font-mono text-sm text-ink">Keyboard shortcuts</span>
            <button
              type="button"
              onClick={() => setView("commands")}
              className="font-mono text-xs text-ink-dim transition-colors hover:text-amber"
            >
              ← back to commands
            </button>
          </div>
          <ul className="p-2">
            {SHORTCUTS.map((shortcut) => (
              <li
                key={shortcut.keys}
                className="flex items-center justify-between px-3 py-2 text-sm"
              >
                <span className="text-ink-muted">{shortcut.description}</span>
                <kbd className="font-mono text-xs text-ink">{shortcut.keys}</kbd>
              </li>
            ))}
          </ul>
          <div className="border-t border-border-subtle px-4 py-2 font-mono text-[10px] text-ink-dim">
            Press <kbd>?</kbd> anywhere to open this sheet
          </div>
        </div>
      )}
    </Command.Dialog>
  );
}
