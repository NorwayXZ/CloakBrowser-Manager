/** Parsing and building proxy strings for saved proxies (carried over from src/lib/proxyInput.ts). */

export type ProxyInputMode = "single" | "batch";
export type ProxyMode = "http" | "https" | "socks5" | "vless" | "vmess" | "trojan" | "ss";

export const DIRECT_PROXY_MODES: ProxyMode[] = ["http", "https", "socks5"];
export const LINK_PROXY_MODES: ProxyMode[] = ["vless", "vmess", "trojan", "ss"];

export function isDirectProxyMode(mode: string): mode is ProxyMode {
  return DIRECT_PROXY_MODES.includes(mode as ProxyMode);
}

export function normalizeProxyHost(host: string) {
  let value = host.trim();
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) {
    try {
      value = new URL(value).hostname;
    } catch {
      // Keep the original value and let backend validation report the error.
    }
  }
  if (value.includes(":") && !value.startsWith("[") && !value.endsWith("]")) {
    return `[${value}]`;
  }
  return value;
}

export function buildDirectProxyUrl(
  mode: ProxyMode,
  host: string,
  port: string,
  username = "",
  password = "",
) {
  const cleanHost = normalizeProxyHost(host);
  const cleanPort = port.trim();
  if (!cleanHost || !cleanPort) return "";
  const user = username.trim();
  const pass = password.trim();
  const auth = user || pass
    ? `${encodeURIComponent(user)}:${encodeURIComponent(pass)}@`
    : "";
  return `${mode}://${auth}${cleanHost}:${cleanPort}`;
}

export function proxyNameFromUrl(proxy: string, fallbackMode: string, index: number) {
  try {
    const url = new URL(proxy);
    const fragment = decodeURIComponent(url.hash.replace(/^#/, "")).trim();
    if (fragment) return fragment.slice(0, 64);
    if (url.hostname) return `${fallbackMode.toUpperCase()} ${url.hostname}${url.port ? `:${url.port}` : ""}`.slice(0, 64);
  } catch {
    // Fall through to generic name.
  }
  return `${fallbackMode.toUpperCase()} 代理 ${index}`;
}

export function parseProxyBatchLine(line: string, defaultMode: ProxyMode, index: number) {
  const value = line.trim();
  if (!value || value.startsWith("#")) return null;

  const scheme = value.split(":", 1)[0]?.toLowerCase() as ProxyMode;
  if ([...DIRECT_PROXY_MODES, ...LINK_PROXY_MODES].includes(scheme)) {
    return {
      name: proxyNameFromUrl(value, scheme, index),
      proxy: value,
      mode: scheme,
    };
  }

  const parts = value.split(":");
  if (parts.length === 2 || parts.length >= 4) {
    const [host, port, username = "", password = ""] = parts;
    const proxy = buildDirectProxyUrl(defaultMode, host ?? "", port ?? "", username, password);
    if (!proxy) return null;
    return {
      name: `${defaultMode.toUpperCase()} ${host}:${port}`.slice(0, 64),
      proxy,
      mode: defaultMode,
    };
  }

  return null;
}
