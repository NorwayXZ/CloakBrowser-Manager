import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { AgentAccessPanel } from "./AgentAccessPanel";

function mockLoad(mode: "read-only" | "automation" = "read-only") {
  vi.spyOn(api, "getMcpMode").mockResolvedValue({ mode });
  vi.spyOn(api, "listMcpAudit").mockResolvedValue([]);
}

beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AgentAccessPanel", () => {
  it("shows the current mode and saves a change", async () => {
    mockLoad();
    const setMode = vi.spyOn(api, "setMcpMode").mockResolvedValue({ mode: "full" });
    render(<AgentAccessPanel />);
    const readOnly = (await screen.findByLabelText(/^只读（默认）/)) as HTMLInputElement;
    await waitFor(() => expect(readOnly.checked).toBe(true));
    fireEvent.click(screen.getByLabelText(/^可启停/));
    await waitFor(() => expect(setMode).toHaveBeenCalledWith("full"));
    expect(await screen.findByText(/MCP 客户端需要重启/)).toBeTruthy();
  });

  it("asks before allowing page control and does nothing when declined", async () => {
    mockLoad();
    vi.mocked(window.confirm).mockReturnValue(false);
    const setMode = vi.spyOn(api, "setMcpMode").mockResolvedValue({ mode: "automation" });
    render(<AgentAccessPanel />);
    fireEvent.click(await screen.findByLabelText(/^可操作页面/));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("Cookie"));
    expect(setMode).not.toHaveBeenCalled();
  });

  it("warns while page control is on", async () => {
    mockLoad("automation");
    render(<AgentAccessPanel />);
    expect(await screen.findByText(/当前允许 AI 操作页面/)).toBeTruthy();
  });

  it("shows recent agent calls", async () => {
    vi.spyOn(api, "getMcpMode").mockResolvedValue({ mode: "read-only" });
      vi.spyOn(api, "listMcpAudit").mockResolvedValue([
      { id: "a1", ts: "2026-10-26T01:00:00+00:00", client_name: "codex", client_version: null,
        tool: "open_browser", args_summary: {}, ok: false, reason: "profile_leased", duration_ms: 12 },
    ]);
    render(<AgentAccessPanel />);
    expect(await screen.findByText("open_browser")).toBeTruthy();
    expect(screen.getByText("profile_leased")).toBeTruthy();
    expect(screen.getByText("codex")).toBeTruthy();
  });

  it("has no agent-token section", async () => {
    mockLoad();
    render(<AgentAccessPanel />);
    await screen.findByText("AI agent 权限");
    expect(screen.queryByText("Agent token")).toBeNull();
    expect(screen.queryByRole("button", { name: "签发 token" })).toBeNull();
  });

  it("shows a load error", async () => {
    vi.spyOn(api, "getMcpMode").mockRejectedValue(new Error("boom"));
      vi.spyOn(api, "listMcpAudit").mockResolvedValue([]);
    render(<AgentAccessPanel />);
    expect(await screen.findByText("boom")).toBeTruthy();
  });
});
