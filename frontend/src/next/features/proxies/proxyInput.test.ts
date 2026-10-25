import { describe, expect, it } from "vitest";
import { buildDirectProxyUrl, isDirectProxyMode, normalizeProxyHost, parseProxyBatchLine } from "./proxyInput";

describe("proxyInput", () => {
  it("builds direct proxy URLs with encoded credentials", () => {
    expect(buildDirectProxyUrl("socks5", "1.2.3.4", "1080")).toBe("socks5://1.2.3.4:1080");
    expect(buildDirectProxyUrl("http", "proxy.example", "8080", "us er", "p@ss")).toBe(
      "http://us%20er:p%40ss@proxy.example:8080",
    );
    expect(buildDirectProxyUrl("http", "", "8080")).toBe("");
  });

  it("normalizes hosts pasted as URLs or IPv6", () => {
    expect(normalizeProxyHost("http://proxy.example:9000")).toBe("proxy.example");
    expect(normalizeProxyHost("2001:db8::1")).toBe("[2001:db8::1]");
  });

  it("parses batch lines in host:port[:user:pass] and URL form", () => {
    expect(parseProxyBatchLine("1.2.3.4:1080:u:p", "socks5", 1)).toEqual({
      name: "SOCKS5 1.2.3.4:1080",
      proxy: "socks5://u:p@1.2.3.4:1080",
      mode: "socks5",
    });
    expect(parseProxyBatchLine("vless://id@host.example:443#Tokyo", "socks5", 2)).toMatchObject({
      name: "Tokyo",
      mode: "vless",
    });
    expect(parseProxyBatchLine("# comment", "socks5", 3)).toBeNull();
    expect(parseProxyBatchLine("host-only", "socks5", 4)).toBeNull();
  });

  it("knows which modes take host and port", () => {
    expect(isDirectProxyMode("https")).toBe(true);
    expect(isDirectProxyMode("trojan")).toBe(false);
  });
});
