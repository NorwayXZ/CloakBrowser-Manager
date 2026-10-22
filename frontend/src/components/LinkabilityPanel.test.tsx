import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type LinkabilityResult } from "../lib/api";
import { LinkabilityPanel } from "./LinkabilityPanel";

const CLUSTERED: LinkabilityResult = {
  profile_count: 3,
  unclustered_count: 1,
  clusters: [
    {
      id: "cluster-1",
      risk: "high",
      profiles: [
        { id: "a", name: "出口甲" },
        { id: "b", name: "出口乙" },
      ],
      links: [
        {
          a_id: "a",
          b_id: "b",
          a_name: "出口甲",
          b_name: "出口乙",
          score: 55,
          level: "strong",
          reasons: ["「出口甲」与「出口乙」共用同一代理出口（socks5://1.2.3.4:1080）"],
          suggestions: ["给其中一个画像换一个独立的代理出口 — 共用出口是最强的关联信号"],
        },
      ],
    },
  ],
};

afterEach(() => vi.restoreAllMocks());

describe("LinkabilityPanel", () => {
  it("renders clusters with reasons, risk badge and suggestions", async () => {
    vi.spyOn(api, "getLinkability").mockResolvedValue(CLUSTERED);
    render(<LinkabilityPanel />);

    expect(await screen.findByText("高风险")).toBeTruthy();
    expect(screen.getAllByText("出口甲").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("出口乙").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/共用同一代理出口/)).toBeTruthy();
    expect(screen.getByText(/建议：给其中一个画像换一个独立的代理出口/)).toBeTruthy();
    expect(screen.getByText(/强关联 · 55 分/)).toBeTruthy();
  });

  it("shows the all-clear state when nothing is linked", async () => {
    vi.spyOn(api, "getLinkability").mockResolvedValue({ profile_count: 2, unclustered_count: 2, clusters: [] });
    render(<LinkabilityPanel />);

    expect(await screen.findByText("没有发现可关联的画像组合")).toBeTruthy();
    expect(screen.getByText(/当前 2 个画像之间没有共用出口/)).toBeTruthy();
  });

  it("surfaces load errors", async () => {
    vi.spyOn(api, "getLinkability").mockRejectedValue(new Error("服务不可用"));
    render(<LinkabilityPanel />);

    expect(await screen.findByText("服务不可用")).toBeTruthy();
  });
});
