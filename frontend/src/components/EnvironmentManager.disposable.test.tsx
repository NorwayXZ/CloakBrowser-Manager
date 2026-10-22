import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Profile } from "../lib/api";
import { EnvironmentManager } from "./EnvironmentManager";

function profile(overrides: Partial<Profile>): Profile {
  return {
    id: "p1",
    name: "画像一",
    status: "stopped",
    group_name: "未分组",
    proxy: null,
    proxy_geo: null,
    notes: null,
    tags: [],
    browser_engine: "cloakbrowser",
    disposable: false,
    last_exit_reason: null,
    last_opened_at: null,
    updated_at: "2026-10-22T00:00:00Z",
    ...overrides,
  } as unknown as Profile;
}

function renderManager(profiles: Profile[]) {
  const async = () => vi.fn().mockResolvedValue(undefined);
  return render(
    <EnvironmentManager
      profiles={profiles}
      groups={[]}
      proxyPresets={[]}
      trashProfiles={[]}
      error={null}
      authRequired={false}
      authUsername={null}
      versions={null}
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

describe("EnvironmentManager disposable identities", () => {
  it("badges disposable profiles and only them", () => {
    renderManager([
      profile({ id: "d1", name: "临时甲", disposable: true }),
      profile({ id: "n1", name: "长期乙", disposable: false }),
    ]);
    expect(screen.getByText("一次性")).toBeTruthy();
    expect(screen.getByText("临时甲")).toBeTruthy();
    expect(screen.getByText("长期乙")).toBeTruthy();
  });

  it("creates a disposable identity for the chosen region", async () => {
    const create = vi.spyOn(api, "createDisposable").mockResolvedValue(profile({ disposable: true }));
    renderManager([]);

    fireEvent.change(screen.getByLabelText("一次性身份地区"), { target: { value: "JP" } });
    fireEvent.click(screen.getByRole("button", { name: /一次性身份/ }));

    await waitFor(() => expect(create).toHaveBeenCalledWith({ region: "JP" }));
  });

  it("burns a disposable profile from the row menu after confirmation", async () => {
    const burn = vi.spyOn(api, "burnProfile").mockResolvedValue({
      ok: true, profile_id: "d1", user_data_dir: "/tmp/d1", files_removed: 3, was_running: false,
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderManager([profile({ id: "d1", name: "临时甲", disposable: true })]);

    fireEvent.click(screen.getByTitle("更多"));
    fireEvent.click(await screen.findByText("焚毁（彻底删除）"));

    await waitFor(() => expect(burn).toHaveBeenCalledWith("d1"));
  });

  it("does not burn when the confirmation is declined", async () => {
    const burn = vi.spyOn(api, "burnProfile").mockResolvedValue({
      ok: true, profile_id: "d1", user_data_dir: "/tmp/d1", files_removed: 0, was_running: false,
    });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderManager([profile({ id: "d1", name: "临时甲", disposable: true })]);

    fireEvent.click(screen.getByTitle("更多"));
    fireEvent.click(await screen.findByText("焚毁（彻底删除）"));

    expect(burn).not.toHaveBeenCalled();
  });

  it("offers no burn action for normal profiles", async () => {
    renderManager([profile({ id: "n1", name: "长期乙", disposable: false })]);

    fireEvent.click(screen.getByTitle("更多"));
    expect(await screen.findByText("删除")).toBeTruthy();
    expect(screen.queryByText("焚毁（彻底删除）")).toBeNull();
  });
});
