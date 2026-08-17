import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PreflightDialog, type PreflightEntry } from "./PreflightDialog";

function entry(canLaunch: boolean): PreflightEntry {
  return {
    id: "profile-1",
    name: "KKK",
    result: {
      status: canLaunch ? "warning" : "fail",
      browser_engine: "cloakbrowser",
      launch_mode: "manual",
      can_launch: canLaunch,
      issues: canLaunch
        ? [{ severity: "warning", code: "external_probe", message: "外部探针尚未完成" }]
        : [{ severity: "error", code: "platform", message: "画像平台不匹配" }],
      capabilities: {
        external_cdp: false,
        fingerprint_args: true,
        proxy_dns_policy: "proxy_host_resolver",
        tls_externally_verified: false,
      },
    },
  };
}

describe("PreflightDialog", () => {
  it("shows warnings and allows an explicit launch confirmation", () => {
    const onConfirm = vi.fn();
    render(<PreflightDialog entries={[entry(true)]} onCancel={vi.fn()} onConfirm={onConfirm} />);

    expect(screen.getByText("外部探针尚未完成")).toBeTruthy();
    const button = screen.getByRole("button", { name: "继续启动" }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("disables confirmation when any profile cannot launch", () => {
    render(<PreflightDialog entries={[entry(false)]} onCancel={vi.fn()} onConfirm={vi.fn()} />);

    expect(screen.getByText("画像平台不匹配")).toBeTruthy();
    expect((screen.getByRole("button", { name: "继续启动" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
