import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CommandPalette } from "./CommandPalette";

// The palette's keyboard behavior: "?" opens the shortcuts sheet, Esc closes
// the dialog, and the sheet has a back-to-commands path. The dialog content
// only mounts while open, so each test renders it open.

function renderPalette(overrides: Partial<Parameters<typeof CommandPalette>[0]> = {}) {
  const onNewAnalysis = vi.fn();
  const onGoToHistory = vi.fn();
  const onOpenChange = vi.fn();
  const utils = render(
    <CommandPalette
      open
      onOpenChange={onOpenChange}
      onNewAnalysis={onNewAnalysis}
      onGoToHistory={onGoToHistory}
      resultSections={[]}
      {...overrides}
    />,
  );
  return { ...utils, onOpenChange, onNewAnalysis, onGoToHistory };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CommandPalette shortcuts sheet", () => {
  it("opens the shortcuts sheet when ? is pressed outside an input", async () => {
    const user = userEvent.setup();
    renderPalette();
    // Radix auto-focuses the search input when the dialog opens; blur it to
    // simulate pressing ? while focus is on the page, not in a field.
    (document.activeElement as HTMLElement | null)?.blur?.();
    await user.keyboard("?");
    expect(screen.getByText("Keyboard shortcuts")).toBeInTheDocument();
    expect(screen.getByText("Toggle this palette")).toBeInTheDocument();
    expect(screen.getByText("⌘K / Ctrl+K")).toBeInTheDocument();
  });

  it("ignores ? while the user is typing in an input", async () => {
    const user = userEvent.setup();
    renderPalette();
    const input = screen.getByPlaceholderText("Search commands...");
    await user.type(input, "how much?");
    // The typed "?" landed in the input text; the shortcuts sheet never opened.
    expect(input).toHaveValue("how much?");
    expect(screen.queryByText("Keyboard shortcuts")).not.toBeInTheDocument();
  });

  it("returns to the command list via the back button", async () => {
    const user = userEvent.setup();
    renderPalette();
    (document.activeElement as HTMLElement | null)?.blur?.();
    await user.keyboard("?");
    expect(screen.getByText("Keyboard shortcuts")).toBeInTheDocument();
    await user.click(screen.getByText("← back to commands"));
    expect(
      screen.getByPlaceholderText("Search commands..."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Keyboard shortcuts")).not.toBeInTheDocument();
  });

  it("opens the shortcuts sheet from the footer link", async () => {
    const user = userEvent.setup();
    renderPalette();
    // The footer button's label is split across a <kbd> and a text node;
    // match by accessible name instead of raw text.
    await user.click(screen.getByRole("button", { name: "? shortcuts" }));
    expect(screen.getByText("Keyboard shortcuts")).toBeInTheDocument();
  });

  it("still toggles the dialog with ctrl+k", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderPalette();
    await user.keyboard("{Control>}k/{/Control}");
    expect(onOpenChange).toHaveBeenCalled();
  });

  it("keeps command selection working alongside the shortcuts view", async () => {
    const user = userEvent.setup();
    const { onNewAnalysis, onOpenChange } = renderPalette();
    await user.click(screen.getByText("New analysis"));
    expect(onNewAnalysis).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
