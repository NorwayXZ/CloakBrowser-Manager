import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetConnectionForTests } from "../../shared/api/connection";
import { expectNoAxeViolations, mockFetch, renderApp, shellRoutes, type MockRoute } from "../../test/utils";
import { makeProfile } from "../profiles/testing";
import type { Profile } from "../profiles/types";
import type { CheckState, EvolutionLog, Proposal, Report } from "./api";

const SITES = [
  { id: "creepjs", name: "CreepJS", url: "https://abrahamjuliot.github.io/creepjs/", criteria: "没有 lies" },
  { id: "pixelscan", name: "Pixelscan", url: "https://pixelscan.net/fingerprint-check", criteria: "指纹一致" },
];

const REPORT: Report = {
  id: "20261020-190000-win",
  created_at: "2026-10-20T19:00:00+08:00",
  overall: "fail",
  environment: { profile_id: "p1", profile_name: "win", host_os: "windows", kernel_version: "154.0.8037.57.1", exit_ip: "1.2.3.4", exit_country: "JP" },
  results: [
    { site: "creepjs", name: "CreepJS", criteria: "没有 lies", status: "pass", summary: "没有 lies，headless 0%，stealth 0%", details: ["lies：0 处"], screenshot: "creepjs.png" },
    { site: "pixelscan", name: "Pixelscan", criteria: "指纹一致", status: "fail", summary: "指纹不一致、检测到伪装", details: ["指纹：不一致"], screenshot: "pixelscan.png" },
  ],
};

const SUMMARY = { id: REPORT.id, created_at: REPORT.created_at, overall: "fail" as const, profile_name: "win", host_os: "windows", passed: 1, total: 2 };

let profiles: Profile[];
let state: CheckState;

function checkRoutes(extra: MockRoute[] = [], report: Report = REPORT): MockRoute[] {
  return shellRoutes([
    ...extra,
    { path: "/api/profiles", respond: () => profiles },
    { path: "/api/site-checks/sites", respond: SITES },
    { path: "/api/site-checks/current", respond: () => state },
    { path: "/api/site-checks", respond: [SUMMARY] },
    { path: `/api/site-checks/${REPORT.id}`, respond: report },
    { path: "/api/evolution/status", respond: { busy: false, pending_proposals: 0 } },
    { path: "/api/automation/hours", respond: { hours: null, open_now: true } },
  ]);
}

async function open(path = "/checks", extra: MockRoute[] = [], report?: Report) {
  const fetchMock = mockFetch(checkRoutes(extra, report));
  const utils = renderApp(path);
  await screen.findByRole("heading", { name: "检测" });
  return { fetchMock, ...utils };
}

function calls(fetchMock: ReturnType<typeof mockFetch>, method: string, url: string) {
  return fetchMock.mock.calls.filter(([u, init]) => String(u) === url && (init?.method ?? "GET") === method);
}

beforeEach(() => {
  profiles = [makeProfile({ id: "p1", name: "win" })];
  state = { phase: "idle" };
  resetConnectionForTests();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("detection reports", () => {
  it("lists the sites, their criteria and past reports", async () => {
    await open();
    expect(await screen.findByText("CreepJS")).toBeInTheDocument();
    expect(screen.getByText(/：没有 lies/)).toBeInTheDocument();
    expect(await screen.findByText(/1\/2 通过/)).toBeInTheDocument();
  });

  it("will not check a profile whose browser is open", async () => {
    profiles = [makeProfile({ id: "p1", name: "win", status: "running" })];
    await open();
    expect(await screen.findByRole("button", { name: "开始检测" })).toBeDisabled();
    expect(screen.getByText(/请先关闭它/)).toBeInTheDocument();
  });

  it("starts after confirmation, shows live progress and opens the report when done", async () => {
    const { fetchMock, router } = await open("/checks", [
      { method: "POST", path: "/api/profiles/p1/site-check", respond: () => {
        state = { phase: "checking", profile_name: "win", site: "pixelscan", index: 1, total: 2, results: [REPORT.results[0]!] };
        return state;
      } },
    ]);
    await screen.findByText("CreepJS");
    fireEvent.click(screen.getByRole("button", { name: "开始检测" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "对「win」开始检测？" })).getByRole("button", { name: "开始检测" }));
    await waitFor(() => expect(calls(fetchMock, "POST", "/api/profiles/p1/site-check")).toHaveLength(1));
    expect(await screen.findByText("正在检测「win」：Pixelscan（2/2）")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "检测进度" })).toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByText("没有 lies，headless 0%，stealth 0%")).toBeInTheDocument();

    state = { phase: "done", report_id: REPORT.id };
    await waitFor(() => expect(router.state.location.search).toBe(`?report=${REPORT.id}`), { timeout: 5000 });
    expect(await screen.findByRole("heading", { name: "win：未通过" })).toBeInTheDocument();
  });

  it("explains a check that could not start", async () => {
    await open("/checks", [{ method: "POST", path: "/api/profiles/p1/site-check", status: 409, respond: { detail: "已经有一项检测在进行" } }]);
    fireEvent.click(await screen.findByRole("button", { name: "开始检测" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "开始检测" }));
    expect(await screen.findByText("已经有一项检测在进行")).toBeInTheDocument();
  });

  it("shows a failed check", async () => {
    state = { phase: "failed", error: "浏览器没能启动" };
    await open();
    expect(await screen.findByText("浏览器没能启动")).toBeInTheDocument();
  });

  it("opens a report with each site's verdict, details and screenshot", async () => {
    await open();
    fireEvent.click(await screen.findByRole("button", { name: /win.*1\/2 通过/ }));
    expect(await screen.findByRole("heading", { name: "win：未通过" })).toBeInTheDocument();
    expect(screen.getByText("指纹不一致、检测到伪装")).toBeInTheDocument();
    expect(screen.getByAltText("Pixelscan 截图")).toHaveAttribute("src", `/api/site-checks/${REPORT.id}/files/pixelscan.png`);
    expect(screen.getByRole("link", { name: /导出报告（zip）/ })).toHaveAttribute("href", `/api/site-checks/${REPORT.id}/download`);
    expect(screen.getByRole("link", { name: "查看环境" })).toHaveAttribute("href", "/profiles?p=p1");
    fireEvent.click(screen.getByAltText("Pixelscan 截图"));
    expect(await screen.findByRole("dialog", { name: "Pixelscan 截图" })).toBeInTheDocument();
  });

  it("shows counts, the egress note, local items and IP caveats", async () => {
    const rich: Report = {
      ...REPORT,
      summary: { pass: 1, warn: 1, fail: 1, unknown: 0, error: 0, total: 3 },
      egress_note: "本次 direct 出口 1.2.3.4（JP）。标注「IP 信誉」的条目结论受出口 IP 影响。",
      results: [
        { site: "local_gpu", name: "GPU / WebGL", criteria: "与设备型号配置一致", status: "pass", summary: "ANGLE (NVIDIA)", details: [], screenshot: null, source: "local" },
        { site: "fingerprint", name: "Fingerprint.com", criteria: "不是机器人", status: "warn", summary: "浏览器没被认出，但 IP 被认出", details: [], screenshot: null, source: "site", ip_note: "这一项的结论受出口 IP 信誉影响" },
        REPORT.results[1]!,
      ],
    };
    await open(`/checks?report=${REPORT.id}`, [], rich);
    expect(await screen.findByText(/共 3 项：通过 1 · 警告 1 · 未通过 1/)).toBeInTheDocument();
    expect(screen.getByText(/标注「IP 信誉」的条目结论受出口 IP 影响/)).toBeInTheDocument();
    expect(screen.getByText("本地自检")).toBeInTheDocument();
    expect(screen.getByText(/IP 信誉：这一项的结论受出口 IP 信誉影响/)).toBeInTheDocument();
  });

  it("shows what changed against the previous report and marks the row", async () => {
    const withDiff: Report = {
      ...REPORT,
      diff: {
        previous_created_at: "2026-10-19T19:00:00+08:00",
        changes: [
          { site: "pixelscan", name: "Pixelscan", from: "pass", to: "fail", summary: "指纹不一致、检测到伪装" },
          { site: "local_gpu", name: "GPU / WebGL", from: null, to: "pass", summary: "ANGLE (NVIDIA)" },
        ],
      },
    };
    await open(`/checks?report=${REPORT.id}`, [], withDiff);
    expect(await screen.findByText(/与上次报告（.*）相比的变化/)).toBeInTheDocument();
    expect(screen.getByText("新增")).toBeInTheDocument();
    const changedRow = document.querySelector("li[data-changed]");
    expect(changedRow).toHaveTextContent("Pixelscan");
    expect(within(changedRow as HTMLElement).getByText("和上次不同")).toBeInTheDocument();
  });

  it("says so when nothing changed against the previous report", async () => {
    await open(`/checks?report=${REPORT.id}`, [], { ...REPORT, diff: { previous_created_at: "2026-10-19T19:00:00+08:00", changes: [] } });
    expect(await screen.findByText(/各条目结论没有变化/)).toBeInTheDocument();
  });

  it("deletes a report after confirmation", async () => {
    const { fetchMock } = await open("/checks", [{ method: "DELETE", path: `/api/site-checks/${REPORT.id}`, respond: { ok: true } }]);
    fireEvent.click(await screen.findByRole("button", { name: "删除报告 win" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "删除这份检测报告和截图？" })).getByRole("button", { name: "删除" }));
    await waitFor(() => expect(calls(fetchMock, "DELETE", `/api/site-checks/${REPORT.id}`)).toHaveLength(1));
  });

  it("has no accessibility violations with a report open", async () => {
    const { container } = await open(`/checks?report=${REPORT.id}`);
    await screen.findByRole("heading", { name: "win：未通过" });
    await expectNoAxeViolations(container);
  });
});

describe("evolution", () => {
  const PROPOSAL: Proposal = {
    id: "prop-1", profile_id: "p1", profile_name: "主力号", knob: "fingerprint_options.noise", label: "关闭指纹噪声",
    from_value: null, to_value: false, evidence: { rationale: "噪声是 lies 的成因", targets: { creepjs: { from: "fail", to: "pass" } } },
    status: "pending", created_at: "2026-10-20T00:00:00Z",
  };
  const LOG: EvolutionLog = {
    id: "log-1", profile_name: "主力号", started_at: "2026-10-20T00:00:00Z", trigger: "scheduled", outcome: "experiments",
    summary: "检测发现 2 个问题，克隆实验 1 个：1 个有效，已生成 1 条待批准提案",
    detail: {
      experiments: [{ knob: "fingerprint_options.noise", label: "关闭指纹噪声", from_value: null, to_value: false, verdict: "improved", targets_detail: { creepjs: { from: "fail", to: "pass" } }, regressions: [] }],
      unfixable: [{ site: "pixelscan", name: "Pixelscan", reason: "结论受出口 IP 信誉影响，配置层没有对应开关" }],
    },
  };

  function evolutionRoutes(proposals: Proposal[] = [], logs: EvolutionLog[] = [], extra: MockRoute[] = []): MockRoute[] {
    return [
      ...extra,
      { path: "/api/evolution/proposals", respond: proposals },
      { path: "/api/evolution/logs?limit=30", respond: logs },
    ];
  }

  it("shows a pending proposal with its evidence and approves it after confirmation", async () => {
    profiles = [makeProfile({ id: "p1", name: "主力号" })];
    const { fetchMock } = await open("/checks/evolution", evolutionRoutes([PROPOSAL], [], [{ method: "POST", path: "/api/evolution/proposals/prop-1/approve", respond: { ...PROPOSAL, status: "applied" } }]));
    expect(await screen.findByText("关闭指纹噪声")).toBeInTheDocument();
    expect(screen.getByText(/自动（内核决定） → 关闭/)).toBeInTheDocument();
    expect(screen.getByText(/creepjs：/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "批准应用" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "批准应用" }));
    await waitFor(() => expect(calls(fetchMock, "POST", "/api/evolution/proposals/prop-1/approve")).toHaveLength(1));
  });

  it("dismisses a proposal without applying it", async () => {
    const { fetchMock } = await open("/checks/evolution", evolutionRoutes([PROPOSAL], [], [{ method: "POST", path: "/api/evolution/proposals/prop-1/dismiss", respond: { ...PROPOSAL, status: "dismissed" } }]));
    fireEvent.click(await screen.findByRole("button", { name: "忽略" }));
    await waitFor(() => expect(calls(fetchMock, "POST", "/api/evolution/proposals/prop-1/dismiss")).toHaveLength(1));
    expect(calls(fetchMock, "POST", "/api/evolution/proposals/prop-1/approve")).toHaveLength(0);
  });

  it("renders the timeline with experiment verdicts and unfixable reasons", async () => {
    await open("/checks/evolution", evolutionRoutes([], [LOG]));
    expect(await screen.findByText("实验完成")).toBeInTheDocument();
    fireEvent.click(screen.getByText(/克隆实验 1 个：1 个有效/));
    expect(await screen.findByText("有效")).toBeInTheDocument();
    expect(screen.getByText("不可自动修复")).toBeInTheDocument();
    expect(screen.getByText(/出口 IP 信誉影响/)).toBeInTheDocument();
  });

  it("toggles auto-evolution through the profile update path", async () => {
    const { fetchMock } = await open("/checks/evolution", evolutionRoutes([], [], [{ method: "PUT", path: "/api/profiles/p1", respond: (body: unknown) => ({ ...profiles[0], ...(body as object) }) }]));
    fireEvent.click(await screen.findByRole("switch", { name: "自动进化" }));
    await waitFor(() => expect(JSON.parse(String((calls(fetchMock, "PUT", "/api/profiles/p1")[0]![1] as RequestInit).body))).toEqual({ evolution_enabled: true, evolution_interval_hours: 24 }));
    expect(await screen.findByRole("switch", { name: "自动进化" })).toBeChecked();
  });

  it("runs a cycle on demand after confirmation, and shows empty states", async () => {
    const { fetchMock } = await open("/checks/evolution", evolutionRoutes([], [], [{ method: "POST", path: "/api/profiles/p1/evolution/run", respond: { ok: true, started: true } }]));
    expect(await screen.findByText(/暂无待批准提案/)).toBeInTheDocument();
    expect(screen.getByText("还没有进化记录")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "现在运行一次" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "开始" }));
    await waitFor(() => expect(calls(fetchMock, "POST", "/api/profiles/p1/evolution/run")).toHaveLength(1));
  });

  it("counts pending proposals in the tab", async () => {
    mockFetch(checkRoutes([{ path: "/api/evolution/status", respond: { busy: false, pending_proposals: 2 } }, ...evolutionRoutes()]));
    renderApp("/checks");
    expect(await screen.findByText("2 待批准")).toBeInTheDocument();
  });
});

describe("linkability", () => {
  const RESULT = {
    profile_count: 3,
    unclustered_count: 1,
    clusters: [
      {
        id: "c1", risk: "high", profiles: [{ id: "a", name: "出口甲" }, { id: "b", name: "出口乙" }],
        links: [{ a_id: "a", b_id: "b", a_name: "出口甲", b_name: "出口乙", score: 55, level: "strong", reasons: ["共用同一代理出口 203.0.113.9"], suggestions: ["给其中一个设备型号换一个独立的代理出口"] }],
      },
    ],
  };

  it("renders clusters with reasons, risk badge, suggestions and links to the profiles", async () => {
    await open("/checks/links", [{ path: "/api/linkability", respond: RESULT }]);
    expect(await screen.findByText("高风险")).toBeInTheDocument();
    expect(screen.getByText(/共用同一代理出口/)).toBeInTheDocument();
    expect(screen.getByText(/建议：给其中一个设备型号换一个独立的代理出口/)).toBeInTheDocument();
    expect(screen.getByText(/强关联 · 55 分/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "出口甲" })).toHaveAttribute("href", "/profiles?p=a");
    expect(screen.getByText(/其中 2 个落在 1 组关联里/)).toBeInTheDocument();
  });

  it("shows the all-clear state when nothing is linked", async () => {
    await open("/checks/links", [{ path: "/api/linkability", respond: { profile_count: 2, unclustered_count: 2, clusters: [] } }]);
    expect(await screen.findByText("没有发现可关联的环境组合")).toBeInTheDocument();
    expect(screen.getByText(/当前 2 个环境之间没有共用出口/)).toBeInTheDocument();
  });

  it("surfaces load errors and re-runs on demand", async () => {
    const { fetchMock } = await open("/checks/links", [{ path: "/api/linkability", status: 500, respond: { detail: "数据库被锁定" } }]);
    expect(await screen.findByText("数据库被锁定")).toBeInTheDocument();
    const before = calls(fetchMock, "GET", "/api/linkability").length;
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "重新分析" }));
    });
    await waitFor(() => expect(calls(fetchMock, "GET", "/api/linkability").length).toBeGreaterThan(before));
  });
});
