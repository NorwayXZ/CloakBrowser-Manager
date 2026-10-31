import { describe, expect, it } from "vitest";
import {
  ALL_GROUPS,
  countByGroup,
  duplicatePayload,
  filterProfiles,
  lastState,
  launchFailureReason,
  locationText,
  proxyHost,
  proxyType,
} from "./format";
import { makeProfile } from "./testing";

describe("proxyType", () => {
  it.each([
    [null, "直连"],
    ["", "直连"],
    ["http://1.2.3.4:80", "HTTP"],
    ["https://1.2.3.4:443", "HTTPS"],
    ["socks5://u:p@1.2.3.4:1080", "SOCKS5"],
    ["vless://uuid@host:443?type=ws", "VLESS"],
    ["vmess://abc", "VMESS"],
    ["trojan://pw@host:443", "TROJAN"],
    ["ss://abc@host:8388", "SS"],
    ["1.2.3.4:8000", "代理"],
  ])("%s → %s", (proxy, expected) => {
    expect(proxyType({ proxy })).toBe(expected);
  });
});

describe("proxyHost", () => {
  it("prefers the detected exit IP", () => {
    expect(proxyHost({ proxy: "socks5://u:p@1.2.3.4:1080", proxy_geo: { ip: "203.0.113.9" } })).toBe("203.0.113.9");
    expect(proxyHost({ proxy: null, proxy_geo: { ip: "198.51.100.1" } })).toBe("198.51.100.1");
  });

  it("shows host:port and never the credentials", () => {
    expect(proxyHost({ proxy: "socks5://alice:secret@1.2.3.4:1080", proxy_geo: null })).toBe("1.2.3.4:1080");
    expect(proxyHost({ proxy: "1.2.3.4:8000:alice:secret", proxy_geo: null })).toBe("1.2.3.4:8000");
    expect(proxyHost({ proxy: "vless://uuid@edge.example.com:443?security=tls", proxy_geo: null })).toBe("edge.example.com:443");
  });

  it("says local network for a direct profile not yet checked", () => {
    expect(proxyHost({ proxy: null, proxy_geo: null })).toBe("本地网络");
  });
});

describe("locationText", () => {
  it("combines country and city, or says when it will be detected", () => {
    expect(locationText({ proxy: "http://x:1", proxy_geo: { country_code: "US", country: "United States", region: "WA", city: "Seattle" } })).toBe("US - United States · WA / Seattle");
    expect(locationText({ proxy: "http://x:1", proxy_geo: null })).toBe("打开后检测");
    expect(locationText({ proxy: null, proxy_geo: null })).toBe("启动时检测本地出口");
    expect(locationText({ proxy: null, proxy_geo: {} })).toBe("未知地区");
  });
});

describe("launch state", () => {
  it("translates license exit codes 76–79", () => {
    expect(launchFailureReason({ last_exit_reason: "异常退出（代码 76）" })).toBe("授权并发已满，请先关闭其他防检测浏览器");
    expect(launchFailureReason({ last_exit_reason: "异常退出（代码 77）" })).toBe("CloakBrowser 授权无效或已过期");
    expect(launchFailureReason({ last_exit_reason: "异常退出（代码 78）" })).toBe("CloakBrowser 授权服务器连接失败");
    expect(launchFailureReason({ last_exit_reason: "异常退出（代码 79）" })).toBe("本地授权配置异常");
    expect(launchFailureReason({ last_exit_reason: "启动失败：找不到内核" })).toBe("启动失败：找不到内核");
    expect(launchFailureReason({ last_exit_reason: null })).toBe("上一次启动未成功");
  });

  it("says running, failed, or when it was last opened", () => {
    expect(lastState(makeProfile({ status: "running" })).kind).toBe("running");
    expect(lastState(makeProfile({ last_exit_reason: "异常退出（代码 76）" }))).toEqual({ kind: "failed", text: "上次启动失败" });
    expect(lastState(makeProfile({ status: "running", last_exit_reason: "异常退出（代码 76）" })).kind).toBe("running");
    expect(lastState(makeProfile({ last_exit_reason: "正常关闭" })).kind).toBe("idle");
  });
});

describe("filtering", () => {
  const profiles = [
    makeProfile({ id: "a", name: "Amazon US", group_name: "美国账号", notes: "主店铺" }),
    makeProfile({ id: "b", name: "TikTok", group_name: null, user_agent: "Mozilla/5.0 Special" }),
    makeProfile({ id: "c", name: "Etsy", group_name: "未分组", proxy: "socks5://1.2.3.4:1080", tags: [{ tag: "vip", color: null }] }),
  ];

  it("searches name, proxy, notes, UA and tags, case-insensitively", () => {
    expect(filterProfiles(profiles, "主店铺", ALL_GROUPS).map((p) => p.id)).toEqual(["a"]);
    expect(filterProfiles(profiles, "special", ALL_GROUPS).map((p) => p.id)).toEqual(["b"]);
    expect(filterProfiles(profiles, "1.2.3.4", ALL_GROUPS).map((p) => p.id)).toEqual(["c"]);
    expect(filterProfiles(profiles, "VIP", ALL_GROUPS).map((p) => p.id)).toEqual(["c"]);
    expect(filterProfiles(profiles, "  ", ALL_GROUPS)).toHaveLength(3);
  });

  it("treats an empty group as 未分组", () => {
    expect(filterProfiles(profiles, "", "未分组").map((p) => p.id)).toEqual(["b", "c"]);
    expect(countByGroup(profiles).get("未分组")).toBe(2);
    expect(countByGroup(profiles).get("美国账号")).toBe(1);
  });
});

describe("duplicatePayload", () => {
  it("copies the configuration with a new name, a fresh seed and no auto launch", () => {
    const source = makeProfile({ name: "Amazon US", fingerprint_seed: 1234, auto_launch: true, browser_engine: "cloakbrowser", proxy: "http://1.2.3.4:80", notes: "n" });
    const payload = duplicatePayload(source);
    expect(payload.name).toBe("Amazon US 副本");
    expect(payload.fingerprint_seed).toBeNull();
    expect(payload.auto_launch).toBe(false);
    expect(payload.browser_engine).toBe("cloakbrowser");
    expect(payload.proxy).toBe("http://1.2.3.4:80");
    expect(payload.notes).toBe("n");
  });

  it("falls back to auto for an unknown engine", () => {
    expect(duplicatePayload(makeProfile({ browser_engine: "something" })).browser_engine).toBe("auto");
  });
});
