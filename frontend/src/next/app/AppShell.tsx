import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router";
import { useManagerStatus } from "../features/app/api";
import { usePreferences } from "../features/settings/preferences";
import { onReconnect, useConnectionState } from "../shared/api/connection";
import { useHotkeys, useMediaQuery } from "../shared/lib/hotkeys";
import { Banner, Dialog, Kbd, Spinner, useToast } from "../ui";
import { NARROW_QUERY, NAV_ITEMS } from "./nav";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import { Sidebar } from "./Sidebar";
import { SHORTCUTS, Toolbar } from "./Toolbar";

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const { sidebarCollapsed, setSidebarCollapsed } = usePreferences();
  const narrow = useMediaQuery(NARROW_QUERY);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const collapsed = narrow || sidebarCollapsed;

  useHotkeys([
    ...NAV_ITEMS.map((item) => ({ combo: `mod+${item.key}`, handler: () => navigate(item.path) })),
    { combo: "?", handler: () => setShortcutsOpen(true) },
  ]);

  return (
    <div className="flex h-full min-h-0 bg-canvas">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-[70] focus:rounded focus:bg-surface focus:px-3 focus:py-2 focus:shadow-popover"
      >
        跳到主要内容
      </a>
      <Sidebar collapsed={collapsed} canToggle={!narrow} onToggle={() => setSidebarCollapsed(!sidebarCollapsed)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Toolbar onShowShortcuts={() => setShortcutsOpen(true)} />
        <ConnectionBanner />
        <OutdatedBackendBanner />
        <DowngradeBanner />
        <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-auto focus:outline-none">
          <RouteErrorBoundary key={location.pathname}>
            <Outlet />
          </RouteErrorBoundary>
        </main>
      </div>
      <Dialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} title="快捷键" size="sm">
        <ul className="flex flex-col gap-2">
          {SHORTCUTS.map((item) => (
            <li key={item.combo} className="flex items-center justify-between gap-4">
              <span className="text-fg-2">{item.label}</span>
              <Kbd>{item.keys}</Kbd>
            </li>
          ))}
        </ul>
      </Dialog>
    </div>
  );
}

/** The panel was rebuilt but the Manager serving it was not restarted. */
function OutdatedBackendBanner() {
  const { backendOutdated } = usePreferences();
  if (!backendOutdated) return null;
  return (
    <div className="shrink-0 border-b border-border bg-surface px-4 py-2">
      <Banner tone="warning" title="Manager 服务是旧版本，需要重启">
        面板已经更新，但正在运行的 Manager 服务还是旧版本，部分功能用不了。源码版请运行 ./bin/cloak restart；安装包版请从菜单栏或托盘退出后重新打开。
      </Banner>
    </div>
  );
}

/** The data was last used by a newer release than the one running now. */
function DowngradeBanner() {
  const { data } = useManagerStatus();
  if (!data?.data_newer_than_app) return null;
  return (
    <div className="shrink-0 border-b border-border bg-surface px-4 py-2">
      <Banner tone="warning" title="这份数据来自更新版本的 Manager">
        你现在运行的是较旧的版本，它可能读不全或写坏新版本保存的内容。建议先更新到最新版本再继续使用；如果要保留现在的数据，请先在“数据”里做一次完整备份。
      </Banner>
    </div>
  );
}

function ConnectionBanner() {
  const state = useConnectionState();
  const queryClient = useQueryClient();
  const toast = useToast();

  useEffect(
    () =>
      onReconnect(() => {
        void queryClient.invalidateQueries();
        toast.show({ tone: "success", title: "已重新连接到 Manager" });
      }),
    [queryClient, toast],
  );

  if (state === "online") return null;
  return (
    <div className="shrink-0 border-b border-border bg-surface px-4 py-2">
      <Banner tone="warning" title="连接不到 Manager 服务" action={<Spinner className="h-4 w-4 text-warning" label="正在重新连接" />}>
        正在自动重新连接。恢复前，保存、启动等操作暂时不可用；已经打开的浏览器不受影响。
      </Banner>
    </div>
  );
}
