import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ExportPdfButton } from "./ExportPdfButton";

describe("ExportPdfButton", () => {
  it("renders export as pdf button and triggers window.print on click", () => {
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});
    render(<ExportPdfButton />);

    const button = screen.getByRole("button", { name: /export report as pdf/i });
    expect(button).toBeInTheDocument();
    expect(button).toHaveTextContent("export as pdf");

    fireEvent.click(button);
    expect(printSpy).toHaveBeenCalledTimes(1);

    printSpy.mockRestore();
  });
});
