import JSZip from "jszip";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TerraformViewer } from "./TerraformViewer";
import type { SystemDesignRecommendation } from "@/lib/types";

const files = {
  "main.tf": "resource \"aws_instance\" \"app\" {}",
  "variables.tf": "variable \"region\" {}",
  "outputs.tf": "output \"ip\" {}",
};

const recommendation = {
  compute: { recommended_instance: "t3.micro", why: "steady", assumptions: [], confidence: "high" },
  database: { needed: false, why: "not needed", assumptions: [], confidence: "high" },
  cache: { needed: false, why: "not needed", assumptions: [], confidence: "high" },
  load_balancer: { needed: false, why: "not needed" },
  architecture_summary: "A small service.",
} as SystemDesignRecommendation;

describe("TerraformViewer", () => {
  afterEach(() => vi.restoreAllMocks());

  it("copies the currently selected tab content", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(<TerraformViewer files={files} />);

    await user.click(screen.getByRole("tab", { name: "variables.tf" }));
    await user.click(screen.getByRole("button", { name: "Copy variables.tf to clipboard" }));

    expect(writeText).toHaveBeenCalledWith(files["variables.tf"]);
  });

  it("downloads a valid zip containing every Terraform file", async () => {
    const user = userEvent.setup();
    let downloadedBlob: Blob | undefined;
    vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
      downloadedBlob = blob as Blob;
      return "blob:test";
    });
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<TerraformViewer files={files} />);

    await user.click(screen.getByRole("button", { name: "Download Terraform files as a zip" }));

    await waitFor(async () => {
      expect(downloadedBlob).toBeDefined();
      const zip = await JSZip.loadAsync(await downloadedBlob!.arrayBuffer());
      expect(await zip.file("terraform/main.tf")!.async("string")).toBe(files["main.tf"]);
      expect(await zip.file("terraform/variables.tf")!.async("string")).toBe(files["variables.tf"]);
      expect(await zip.file("terraform/outputs.tf")!.async("string")).toBe(files["outputs.tf"]);
    });
  });

  it("shows the formatted recommendation JSON when requested", async () => {
    const user = userEvent.setup();
    render(<TerraformViewer files={files} recommendation={recommendation} />);

    await user.click(screen.getByRole("button", { name: "view raw json" }));

    expect(screen.getByRole("tabpanel", { name: "raw recommendation JSON" })).toHaveTextContent(
      '"architecture_summary": "A small service."',
    );
    expect(screen.getByRole("button", { name: "hide raw json" })).toBeInTheDocument();
  });
});
