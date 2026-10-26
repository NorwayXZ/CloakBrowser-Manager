import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type AgentLease } from "../lib/api";
import { AgentLeaseBadge } from "./AgentLeaseBadge";

afterEach(() => {
  vi.restoreAllMocks();
});

const agentLease: AgentLease = {
  holder: "codex#ab12cd",
  kind: "agent",
  acquired_at: "2026-10-25T00:00:00+00:00",
  expires_at: "2026-10-25T00:15:00+00:00",
  seconds_left: 600,
};

describe("AgentLeaseBadge", () => {
  it("shows the agent holder and takes over on click", async () => {
    const takeover = vi.spyOn(api, "takeoverProfile").mockResolvedValue({ lease: null, cdp_connections_closed: 1 });
    const onChanged = vi.fn();
    render(<AgentLeaseBadge profileId="p1" lease={agentLease} onChanged={onChanged} />);
    expect(screen.getByText(/AI 控制中：codex#ab12cd（10 分钟内有效）/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "接管" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(takeover).toHaveBeenCalledWith("p1");
  });

  it("offers to hand the profile back after a takeover", async () => {
    const release = vi.spyOn(api, "releaseProfileLease").mockResolvedValue({ released: true });
    const onChanged = vi.fn();
    render(
      <AgentLeaseBadge
        profileId="p1"
        lease={{ ...agentLease, holder: "human", kind: "human", seconds_left: 1500 }}
        onChanged={onChanged}
      />,
    );
    expect(screen.getByText(/你已接管/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "归还给 AI" }));
    await waitFor(() => expect(release).toHaveBeenCalledWith("p1"));
  });

  it("reports a failed action", async () => {
    vi.spyOn(api, "takeoverProfile").mockRejectedValue(new Error("boom"));
    render(<AgentLeaseBadge profileId="p1" lease={agentLease} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "接管" }));
    expect(await screen.findByText("操作失败")).toBeTruthy();
  });
});
