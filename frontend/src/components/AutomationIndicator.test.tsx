import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { AutomationIndicator } from "./AutomationIndicator";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AutomationIndicator", () => {
  it("shows the running automation's label and profile name", async () => {
    vi.spyOn(api, "getAutomationStatus").mockResolvedValue({
      active: true, kind: "warmup", label: "养号",
      profile_id: "p1", profile_name: "主力号",
    });
    render(<AutomationIndicator />);
    expect(await screen.findByText(/自动化运行中：养号 · 主力号/)).toBeTruthy();
  });

  it("shows a site check without a profile name", async () => {
    vi.spyOn(api, "getAutomationStatus").mockResolvedValue({
      active: true, kind: "site_check", label: "指纹检测",
      profile_id: "p2", profile_name: null,
    });
    render(<AutomationIndicator />);
    expect(await screen.findByText(/自动化运行中：指纹检测/)).toBeTruthy();
  });

  it("renders nothing while idle", async () => {
    vi.spyOn(api, "getAutomationStatus").mockResolvedValue({
      active: false, kind: null, label: null, profile_id: null, profile_name: null,
    });
    const { container } = render(<AutomationIndicator />);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when the status call fails", async () => {
    vi.spyOn(api, "getAutomationStatus").mockRejectedValue(new Error("down"));
    const { container } = render(<AutomationIndicator />);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(container.firstChild).toBeNull();
  });
});
