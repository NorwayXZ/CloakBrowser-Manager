import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { EnvironmentManager } from "./EnvironmentManager";

function renderManager(versions: { app: string | null; kernel: string | null } | null) {
  const async = () => vi.fn().mockResolvedValue(undefined);
  return render(
    <EnvironmentManager
      profiles={[]}
      groups={[]}
      proxyPresets={[]}
      trashProfiles={[]}
      error={null}
      authRequired={false}
      authUsername={null}
      versions={versions}
      onNew={vi.fn()}
      onEdit={vi.fn()}
      onDuplicate={async()}
      onDelete={async()}
      onUpdateNotes={async()}
      onLaunch={async()}
      onBatchLaunch={async()}
      onStop={async()}
      onBatchStop={async()}
      onRefresh={async()}
      onCreateGroup={async()}
      onDeleteGroup={async()}
      onCreateProxyPreset={async()}
      onCreateProxyPresets={async()}
      onDeleteProxyPreset={async()}
      onRestoreProfile={async()}
      onPurgeProfile={async()}
      onAccount={vi.fn()}
      onLogout={vi.fn()}
    />,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("EnvironmentManager versions", () => {
  it("always shows the Manager and kernel versions", () => {
    renderManager({ app: "0.4.2", kernel: "154.0.8037.57.1" });

    expect(screen.getByText("Manager v0.4.2")).toBeTruthy();
    expect(screen.getByText("内核 154.0.8037.57.1")).toBeTruthy();
  });

  it("labels a source checkout", () => {
    renderManager({ app: null, kernel: null });

    expect(screen.getByText("Manager 源码版")).toBeTruthy();
    expect(screen.getByText("内核 未下载")).toBeTruthy();
  });

  it("says a new release was found instead of claiming the upgrade finished", async () => {
    vi.spyOn(api, "updateManager").mockResolvedValue({
      ok: true, updated: false, before: "0.3.0", after: "0.4.1", branch: null, restart_required: false,
      message: "发现新版本 0.4.1（当前 0.3.0）。", log: [], download_url: "https://example.com/dmg",
    });
    vi.spyOn(api, "updateBrowser").mockResolvedValue({
      ok: true, updated: false, wrapper_version: "0.6.2", current_version: "154.0.8037.57.1",
      available_version: "154.0.8037.57.1", installed_version: "154.0.8037.57.1-pro", platform: "darwin-arm64",
      binary_verified: true, restart_required: false, message: "当前内核 154.0.8037.57.1-pro 已是最新。",
    });
    renderManager({ app: "0.3.0", kernel: "154.0.8037.57.1" });

    fireEvent.click(screen.getByRole("button", { name: /升级/ }));

    expect(await screen.findByText("发现新版本 0.4.1，请下载安装")).toBeTruthy();
    expect(screen.queryByText(/升级完成/)).toBeNull();
  });
});
