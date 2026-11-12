import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ExportPdfButton } from "./ExportPdfButton";

describe("ExportPdfButton", () => {
  it("prints closed deployment actions and restores the reader's expanded state", () => {
    render(<main><details><summary>Closed action</summary><p>Required deployment work</p></details><details open><summary>Open action</summary></details><ExportPdfButton /></main>);
    const closed = screen.getByText("Closed action").closest("details")!;
    const open = screen.getByText("Open action").closest("details")!;
    fireEvent(window, new Event("beforeprint"));
    expect(closed.open).toBe(true);
    expect(open.open).toBe(true);
    fireEvent(window, new Event("afterprint"));
    expect(closed.open).toBe(false);
    expect(open.open).toBe(true);
  });
  it("renders export as pdf button and triggers window.print on click", () => {
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});
    render(<ExportPdfButton />);

    const button = screen.getByRole("button", { name: /export as pdf/i });
    expect(button).toBeInTheDocument();
    expect(button).toHaveTextContent("export as pdf");

    fireEvent.click(button);
    expect(printSpy).toHaveBeenCalledTimes(1);

    printSpy.mockRestore();
  });
});
