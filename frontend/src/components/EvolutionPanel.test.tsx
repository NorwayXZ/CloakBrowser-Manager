import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type EvolutionLogEntry, type EvolutionProposal, type Profile } from "../lib/api";
import { EvolutionPanel } from "./EvolutionPanel";

function profile(id: string, name: string, extra: Partial<Profile> = {}): Profile {
  return { id, name, status: "stopped", evolution_enabled: false, evolution_interval_hours: 24, ...extra } as unknown as Profile;
}

const PROPOSAL: EvolutionProposal = {
  id: "prop-1",
  profile_id: "p1",
  profile_name: "主力号",
  knob: "fingerprint_options.noise",
  label: "关闭指纹噪声",
  from_value: null,
  to_value: false,
  targets: ["creepjs"],
  evidence: {
    verdict: "improved",
    rationale: "噪声是 lies 的成因",
    targets: { creepjs: { from: "fail", to: "pass" } },
  },
  status: "pending",
  created_at: "2026-10-22T02:00:00+08:00",
  decided_at: null,
};

const LOG: EvolutionLogEntry = {
  id: "log-1",
  profile_id: "p1",
  profile_name: "主力号",
  started_at: "2026-10-22T02:00:00+08:00",
  finished_at: "2026-10-22T02:20:00+08:00",
  trigger: "scheduled",
  outcome: "experiments",
  summary: "检测发现 2 个问题，克隆实验 1 个：1 个有效，已生成 1 条待批准提案",
  detail: {
    source_report_id: "r1",
    problem_count: 2,
    experiments: [
      {
        knob: "fingerprint_options.noise",
        label: "关闭指纹噪声",
        from_value: null,
        to_value: false,
        targets: ["creepjs"],
        rationale: "噪声是 lies 的成因",
        verdict: "improved",
        targets_detail: { creepjs: { from: "fail", to: "pass" } },
        regressions: [],
        clone_report_id: "r2",
        proposal_id: "prop-1",
      },
    ],
    unfixable: [
      { site: "pixelscan", name: "Pixelscan", status: "fail", reason: "结论受出口 IP 信誉影响，配置层没有对应开关" },
    ],
    proposals: ["prop-1"],
  },
};

function mockApi(overrides: { proposals?: EvolutionProposal[]; logs?: EvolutionLogEntry[] } = {}) {
  vi.spyOn(api, "getEvolutionStatus").mockResolvedValue({
    busy: false, profile_id: null, profile_name: null, lock_owner: null, pending_proposals: 0,
  });
  vi.spyOn(api, "listEvolutionProposals").mockResolvedValue(overrides.proposals ?? []);
  vi.spyOn(api, "listEvolutionLogs").mockResolvedValue(overrides.logs ?? []);
}

afterEach(() => vi.restoreAllMocks());

describe("EvolutionPanel", () => {
  it("shows a pending proposal with its evidence and approves it", async () => {
    mockApi({ proposals: [PROPOSAL] });
    const approve = vi.spyOn(api, "approveEvolutionProposal").mockResolvedValue({ ...PROPOSAL, status: "applied" });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<EvolutionPanel profiles={[profile("p1", "主力号")]} onRefresh={vi.fn()} />);

    expect(await screen.findByText("关闭指纹噪声")).toBeTruthy();
    expect(screen.getByText(/自动（内核决定） → 关闭/)).toBeTruthy();
    expect(screen.getByText(/creepjs：/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /批准应用/ }));
    await waitFor(() => expect(approve).toHaveBeenCalledWith("prop-1"));
  });

  it("dismisses a proposal without applying it", async () => {
    mockApi({ proposals: [PROPOSAL] });
    const dismiss = vi.spyOn(api, "dismissEvolutionProposal").mockResolvedValue({ ...PROPOSAL, status: "dismissed" });
    render(<EvolutionPanel profiles={[profile("p1", "主力号")]} onRefresh={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: /忽略/ }));
    await waitFor(() => expect(dismiss).toHaveBeenCalledWith("prop-1"));
  });

  it("renders the battle timeline with experiment verdicts and unfixable reasons", async () => {
    mockApi({ logs: [LOG] });
    render(<EvolutionPanel profiles={[profile("p1", "主力号")]} onRefresh={vi.fn()} />);

    expect(await screen.findByText("实验完成")).toBeTruthy();
    expect(screen.getByText(/克隆实验 1 个：1 个有效/)).toBeTruthy();

    fireEvent.click(screen.getByText(/克隆实验 1 个：1 个有效/));
    expect(await screen.findByText("有效")).toBeTruthy();
    expect(screen.getByText("不可自动修复")).toBeTruthy();
    expect(screen.getByText(/出口 IP 信誉影响/)).toBeTruthy();
  });

  it("toggles auto-evolution through the profile update path", async () => {
    mockApi();
    const update = vi.spyOn(api, "updateProfile").mockResolvedValue(profile("p1", "主力号", { evolution_enabled: true }));
    render(<EvolutionPanel profiles={[profile("p1", "主力号")]} onRefresh={vi.fn()} />);

    fireEvent.click(await screen.findByLabelText("自动进化"));
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith("p1", { evolution_enabled: true, evolution_interval_hours: 24 }),
    );
  });

  it("runs a cycle on demand after confirmation", async () => {
    mockApi();
    const run = vi.spyOn(api, "runEvolutionNow").mockResolvedValue({ ok: true, started: true });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<EvolutionPanel profiles={[profile("p1", "主力号")]} onRefresh={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: /立即进化一次/ }));
    await waitFor(() => expect(run).toHaveBeenCalledWith("p1"));
  });

  it("shows empty states when there is nothing yet", async () => {
    mockApi();
    render(<EvolutionPanel profiles={[profile("p1", "主力号")]} onRefresh={vi.fn()} />);

    expect(await screen.findByText(/暂无待批准提案/)).toBeTruthy();
    expect(screen.getByText(/还没有进化记录/)).toBeTruthy();
  });
});
