import { Database, Globe2, LayoutGrid, Settings, ShieldCheck, type LucideIcon } from "lucide-react";

export interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
  /** Shortcut number: mod+N opens the page. */
  key: string;
}

export const NAV_ITEMS: NavItem[] = [
  { path: "/profiles", label: "环境", icon: LayoutGrid, key: "1" },
  { path: "/proxies", label: "代理", icon: Globe2, key: "2" },
  { path: "/checks", label: "检测", icon: ShieldCheck, key: "3" },
  { path: "/data", label: "数据", icon: Database, key: "4" },
  { path: "/settings", label: "设置", icon: Settings, key: "5" },
];

export function navItemFor(pathname: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => pathname === item.path || pathname.startsWith(`${item.path}/`));
}

/** Where the redesigned panel is served until it replaces the current one. */
export const APP_BASENAME = "/next";

/** The current panel, for pages that are not rebuilt yet. */
export const LEGACY_PANEL_URL = "/";

/** Below this width the sidebar only shows icons and side panels collapse. */
export const NARROW_QUERY = "(max-width: 1179px)";
