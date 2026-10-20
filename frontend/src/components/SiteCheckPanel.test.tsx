import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Profile, type SiteCheckReport } from "../lib/api";
import { SiteCheckPanel } from "./SiteCheckPanel";

const SITES = [
  { id: "creepjs", name: "CreepJS", url: "https://abrahamjuliot.github.io/creepjs/", criteria: "没有 lies" },
  { id: "pixelscan", name: "Pixelscan", url: "https://pixelscan.net/fingerprint-check", criteria: "指纹一致" },
];

function profile(id: string, name: string, status: "running" | "stopped" = "stopped"): Profile {
  return { id, name, status } as unknown as Profile;
}

const REPORT: SiteCheckReport = {
  id: "20261020-190000-win",
  created_at: "2026-10-20T19:00:00+08:00",
  overall: "fail",
  environment: { profile_name: "win", host_os: "windows", kernel_version: "154.0.8037.57.1", exit_ip: "1.2.3.4", exit_country: "JP" },
  results: [
    { site: "creepjs", name: "CreepJS", url: "u", criteria: "没有 lies", status: "pass", summary: "没有 lies，headless 0%，stealth 0%", details: ["lies：0 处"], screenshot: "creepjs.png", seconds: 30 },
    { site: "pixelscan", name: "Pixelscan", url: "u", criteria: "指纹一致", status: "fail", summary: "指纹不一致、检测到伪装", details: ["指纹：不一致"], screenshot: "pixelscan.png", seconds: 28 },
  ],
};

function mockApi(state = { phase: "idle" as const }) {
  vi.spyOn(api, "listSiteCheckSites").mockResolvedValue(SITES);
  vi.spyOn(api, "getSiteCheckState").mockResolvedValue(state);
  vi.spyOn(api, "listSiteCheckReports").mockResolvedValue([
    { id: REPORT.id, created_at: REPORT.created_at, overall: "fail", profile_name: "win", host_os: "windows", passed: 1, total: 2 },
  ]);
}

afterEach(() => vi.restoreAllMocks());

describe("SiteCheckPanel", () => {
  it("lists the sites, their criteria and past reports", async () => {
    mockApi();
    render(<SiteCheckPanel profiles={[profile("p1", "win")]} onRefresh={vi.fn()} />);

    expect(await screen.findByText("CreepJS")).toBeTruthy();
    expect(screen.getByText(/没有 lies/)).toBeTruthy();
    expect(await screen.findByText("1/2 通过")).toBeTruthy();
  });

  it("will not check a profile that is open", async () => {
    mockApi();
    render(<SiteCheckPanel profiles={[profile("p1", "win", "running")]} onRefresh={vi.fn()} />);

    const start = (await screen.findByRole("button", { name: "开始检测" })) as HTMLButtonElement;
    expect(start.disabled).toBe(true);
    expect(screen.getByText(/请先关闭它/)).toBeTruthy();
  });

  it("starts after confirmation and shows live results", async () => {
    mockApi();
    const start = vi.spyOn(api, "startSiteCheck").mockResolvedValue({
      phase: "checking", profile_name: "win", site: "pixelscan", index: 1, total: 2,
      results: [REPORT.results[0]!],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<SiteCheckPanel profiles={[profile("p1", "win")]} onRefresh={vi.fn()} />);
    await screen.findByText("CreepJS");

    fireEvent.click(screen.getByRole("button", { name: "开始检测" }));

    await waitFor(() => expect(start).toHaveBeenCalledWith("p1"));
    expect(await screen.findByText(/正在检测「win」：Pixelscan（2\/2）/)).toBeTruthy();
    expect(screen.getByText("没有 lies，headless 0%，stealth 0%")).toBeTruthy();
  });

  it("opens a report with each site's verdict, details and screenshot", async () => {
    mockApi();
    vi.spyOn(api, "getSiteCheckReport").mockResolvedValue(REPORT);
    render(<SiteCheckPanel profiles={[profile("p1", "win")]} onRefresh={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "查看" }));

    expect(await screen.findByText("win：未通过")).toBeTruthy();
    expect(screen.getByText("指纹不一致、检测到伪装")).toBeTruthy();
    expect(screen.getByAltText("Pixelscan 截图").getAttribute("src")).toBe(api.siteCheckFileUrl(REPORT.id, "pixelscan.png"));
    expect(screen.getByRole("link", { name: /导出报告（zip）/ }).getAttribute("href")).toBe(api.siteCheckDownloadUrl(REPORT.id));
  });

  it("deletes a report after confirmation", async () => {
    mockApi();
    const remove = vi.spyOn(api, "deleteSiteCheckReport").mockResolvedValue({ ok: true });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<SiteCheckPanel profiles={[profile("p1", "win")]} onRefresh={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: `删除报告 ${REPORT.id}` }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(REPORT.id));
  });
});
