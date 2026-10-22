import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { AutomationHoursHint, AutomationHoursSettings } from "./AutomationHours";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AutomationHoursSettings", () => {
  it("loads the current window and saves edits", async () => {
    vi.spyOn(api, "getAutomationHours").mockResolvedValue({ hours: "09-18", open_now: true });
    const update = vi.spyOn(api, "updateAutomationHours")
      .mockResolvedValue({ hours: "23-07", open_now: false });

    render(<AutomationHoursSettings />);
    const input = (await screen.findByLabelText("自动化时段")) as HTMLInputElement;
    expect(input.value).toBe("09-18");

    fireEvent.change(input, { target: { value: "23-07" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("23-07"));
    expect(await screen.findByText("已保存")).toBeTruthy();
  });

  it("saves an empty value as no restriction", async () => {
    vi.spyOn(api, "getAutomationHours").mockResolvedValue({ hours: "09-18", open_now: true });
    const update = vi.spyOn(api, "updateAutomationHours")
      .mockResolvedValue({ hours: null, open_now: true });

    render(<AutomationHoursSettings />);
    const input = (await screen.findByLabelText("自动化时段")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith(null));
  });

  it("surfaces a rejected window from the API", async () => {
    vi.spyOn(api, "getAutomationHours").mockResolvedValue({ hours: null, open_now: true });
    vi.spyOn(api, "updateAutomationHours")
      .mockRejectedValue(new Error("时段格式不对，请用 HH-HH"));

    render(<AutomationHoursSettings />);
    const input = (await screen.findByLabelText("自动化时段")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "banana" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText(/时段格式不对/)).toBeTruthy();
  });
});

describe("AutomationHoursHint", () => {
  it("warns when a window is set and now is outside it", async () => {
    vi.spyOn(api, "getAutomationHours").mockResolvedValue({ hours: "09-18", open_now: false });
    render(<AutomationHoursHint />);
    expect(await screen.findByText(/当前不在自动化时段（09-18）内/)).toBeTruthy();
    expect(screen.getByText(/手动触发不受影响/)).toBeTruthy();
  });

  it("stays silent inside the window", async () => {
    vi.spyOn(api, "getAutomationHours").mockResolvedValue({ hours: "09-18", open_now: true });
    const { container } = render(<AutomationHoursHint />);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(container.firstChild).toBeNull();
  });

  it("stays silent when no window is set", async () => {
    vi.spyOn(api, "getAutomationHours").mockResolvedValue({ hours: null, open_now: true });
    const { container } = render(<AutomationHoursHint />);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(container.firstChild).toBeNull();
  });
});
