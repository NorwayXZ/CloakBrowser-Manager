import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { AgentAccessPanel } from "./AgentAccessPanel";

const noTokens = { enforced: true, scopes: ["read", "control", "cdp"] as const, tokens: [] };

function mockLoad(mode: "read-only" | "automation" = "read-only", tokens: object = noTokens) {
  vi.spyOn(api, "getMcpMode").mockResolvedValue({ mode });
  vi.spyOn(api, "listAgentTokens").mockResolvedValue(tokens as never);
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

  it("creates a token, shows it once, and lists it", async () => {
    mockLoad();
    const record = { id: "t1", name: "codex 笔记本", scope: "control", created_at: 1_700_000_000 };
    const create = vi.spyOn(api, "createAgentToken").mockResolvedValue({
      token: "cbm_control_SECRET", record, enforced: true, note: "",
    } as never);
    render(<AgentAccessPanel />);
    fireEvent.change(await screen.findByLabelText("名称"), { target: { value: "codex 笔记本" } });
    vi.mocked(api.listAgentTokens).mockResolvedValue({ ...noTokens, tokens: [record] } as never);
    fireEvent.click(screen.getByRole("button", { name: "签发 token" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith("codex 笔记本", "control"));
    expect(await screen.findByText("cbm_control_SECRET")).toBeTruthy();
    expect(screen.getByText(/只显示这一次/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "我已保存，关闭" }));
    expect(screen.queryByText("cbm_control_SECRET")).toBeNull();
    expect(screen.getByLabelText("撤销 codex 笔记本")).toBeTruthy();
  });

  it("does not issue a token without a name", async () => {
    mockLoad();
    const create = vi.spyOn(api, "createAgentToken");
    render(<AgentAccessPanel />);
    const button = (await screen.findByRole("button", { name: "签发 token" })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(create).not.toHaveBeenCalled();
  });

  it("revokes a token after confirmation", async () => {
    const record = { id: "t1", name: "旧 token", scope: "read", created_at: 1_700_000_000 };
    mockLoad("read-only", { ...noTokens, tokens: [record] });
    const revoke = vi.spyOn(api, "revokeAgentToken").mockResolvedValue({ ok: true });
    render(<AgentAccessPanel />);
    fireEvent.click(await screen.findByLabelText("撤销 旧 token"));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("t1"));
  });

  it("tells the user tokens are not checked when the Manager has no auth", async () => {
    mockLoad("read-only", { ...noTokens, enforced: false });
    render(<AgentAccessPanel />);
    expect(await screen.findByText(/token 不会被检查/)).toBeTruthy();
  });

  it("shows recent agent calls", async () => {
    vi.spyOn(api, "getMcpMode").mockResolvedValue({ mode: "read-only" });
    vi.spyOn(api, "listAgentTokens").mockResolvedValue(noTokens as never);
    vi.spyOn(api, "listMcpAudit").mockResolvedValue([
      { id: "a1", ts: "2026-10-26T01:00:00+00:00", client_name: "codex", client_version: null,
        tool: "open_browser", args_summary: {}, ok: false, reason: "profile_leased", duration_ms: 12 },
    ]);
    render(<AgentAccessPanel />);
    expect(await screen.findByText("open_browser")).toBeTruthy();
    expect(screen.getByText("profile_leased")).toBeTruthy();
    expect(screen.getByText("codex")).toBeTruthy();
  });

  it("shows a load error", async () => {
    vi.spyOn(api, "getMcpMode").mockRejectedValue(new Error("boom"));
    vi.spyOn(api, "listAgentTokens").mockResolvedValue(noTokens as never);
    vi.spyOn(api, "listMcpAudit").mockResolvedValue([]);
    render(<AgentAccessPanel />);
    expect(await screen.findByText("boom")).toBeTruthy();
  });
});
