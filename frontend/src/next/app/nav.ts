import { Boxes, LayoutGrid, Settings, type LucideIcon } from "lucide-react";

export interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
  /** Shortcut number: mod+N opens the page. */
  key: string;
}

export const NAV_ITEMS: NavItem[] = [
  { path: "/profiles", label: "环境", icon: LayoutGrid, key: "1" },
  { path: "/resources", label: "资源", icon: Boxes, key: "2" },
  { path: "/settings", label: "设置", icon: Settings, key: "3" },
];

/** Pages that used to have their own top-level entry, and where they live now. */
export const MOVED_PAGES: Record<string, string> = {
  "/proxies": "/resources/proxies",
  "/mail": "/resources/mail",
  "/checks": "/settings/checks",
  "/data": "/settings/data",
};

export function navItemFor(pathname: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => pathname === item.path || pathname.startsWith(`${item.path}/`));
}

/** The panel is served from the site root. */
export const APP_BASENAME = "/";

/** The previous panel, kept for one release as a way back. */
export const LEGACY_PANEL_URL = "/legacy/";

/** Below this width the top bar's page switcher shows icons only. */
export const COMPACT_QUERY = "(max-width: 899px)";

/** Below this width side panels float over the content instead of docking. */
export const NARROW_QUERY = "(max-width: 1179px)";
