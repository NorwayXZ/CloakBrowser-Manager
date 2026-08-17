import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NativeWindowStatus } from "./NativeWindowStatus";


describe("NativeWindowStatus", () => {
  const writeText = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    writeText.mockClear();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
  });

  it("shows that the profile runs in a native window", () => {
    render(<NativeWindowStatus profileId="profile-1" profileName="Work" cdpUrl={null} />);
    expect(screen.getByText("已在原生窗口打开")).toBeTruthy();
    expect(screen.getByText(/Work 正在这台电脑上运行/)).toBeTruthy();
  });

  it("copies the Manager CDP endpoint", async () => {
      render(
      <NativeWindowStatus
        profileId="profile-1"
        profileName="Work"
        cdpUrl="/api/profiles/profile-1/cdp"
      />,
    );
    fireEvent.click(screen.getByTitle("复制 CDP 地址"));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(
        `${window.location.protocol}//${window.location.host}/api/profiles/profile-1/cdp`,
      );
    });
  });

  it("exposes fingerprint self-check in debug mode", () => {
    render(
      <NativeWindowStatus
        profileId="profile-1"
        profileName="Work"
        cdpUrl="/api/profiles/profile-1/cdp"
      />,
    );
    expect(screen.getByTitle("运行指纹自检")).toBeTruthy();
  });
});
