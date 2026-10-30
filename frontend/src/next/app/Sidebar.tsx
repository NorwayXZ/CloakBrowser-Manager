import { PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import { NavLink, useNavigate } from "react-router";
import { useManagerStatus } from "../features/app/api";
import { cn } from "../shared/lib/cn";
import { formatShortcut } from "../shared/lib/hotkeys";
import { Button, IconButton, Tooltip } from "../ui";
import { NAV_ITEMS } from "./nav";

export function Sidebar({
  collapsed,
  canToggle,
  onToggle,
}: {
  collapsed: boolean;
  /** false when the window is too narrow to expand it. */
  canToggle: boolean;
  onToggle: () => void;
}) {
  const navigate = useNavigate();
  const status = useManagerStatus();
  const appVersion = status.data ? (status.data.app_version ? `v${status.data.app_version}` : "源码版") : "…";
  const kernelVersion = status.data?.binary_version || "未下载";

  return (
    <aside
      aria-label="主导航"
      className={cn(
        "flex h-full shrink-0 flex-col border-r border-border bg-sidebar transition-[width] duration-base",
        collapsed ? "w-sidebar-collapsed" : "w-sidebar",
      )}
    >
      <div className={cn("flex h-toolbar shrink-0 items-center gap-2.5", collapsed ? "justify-center px-0" : "px-4")}>
        <div aria-hidden className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] bg-gradient-to-b from-accent-fill to-accent-fill-hover text-sm font-semibold text-accent-on shadow-raised">
          C
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-fg">CloakBrowser</div>
            <div className="truncate text-xs text-fg-3">Manager</div>
          </div>
        )}
      </div>

      <div className={cn("pt-3", collapsed ? "px-2" : "px-3")}>
        {collapsed ? (
          <IconButton
            label="新建环境"
            variant="primary"
            icon={<Plus className="h-4 w-4" />}
            className="w-full"
            onClick={() => navigate("/profiles/new")}
          />
        ) : (
          <Button variant="primary" className="w-full" icon={<Plus className="h-4 w-4" />} onClick={() => navigate("/profiles/new")}>
            新建环境
          </Button>
        )}
      </div>

      <nav aria-label="页面" className={cn("mt-3 flex-1 overflow-y-auto", collapsed ? "px-2" : "px-3")}>
        <ul className="flex flex-col gap-0.5">
          {NAV_ITEMS.map((item) => {
            const link = (
              <NavLink
                to={item.path}
                aria-label={collapsed ? item.label : undefined}
                // A plain string, not NavLink's function form: the tooltip's Slot would
                // stringify a function. NavLink sets aria-current on the active link.
                className={cn(
                  "group flex h-8 items-center gap-2.5 rounded text-sm text-fg transition-colors duration-fast hover:bg-fg/5",
                  "aria-[current=page]:bg-fg/10 aria-[current=page]:font-medium",
                  collapsed ? "justify-center" : "px-2.5",
                )}
              >
                <item.icon className="h-[18px] w-[18px] shrink-0 text-accent" aria-hidden />
                {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
                {!collapsed && <span className="text-xs text-fg-3">{formatShortcut(`mod+${item.key}`)}</span>}
              </NavLink>
            );
            return (
              <li key={item.path}>
                {collapsed ? (
                  <Tooltip content={item.label} shortcut={formatShortcut(`mod+${item.key}`)} side="right">
                    {link}
                  </Tooltip>
                ) : (
                  link
                )}
              </li>
            );
          })}
        </ul>
      </nav>

      <div className={cn("flex shrink-0 items-center gap-2 py-2.5", collapsed ? "flex-col px-2" : "px-4")}>
        {!collapsed && (
          <div className="min-w-0 flex-1 text-xs leading-4 text-fg-3" aria-label="版本信息">
            <div className="truncate">Manager {appVersion}</div>
            <div className="truncate font-mono" title={kernelVersion}>
              内核 {kernelVersion}
            </div>
          </div>
        )}
        {canToggle && (
          <IconButton
            label={collapsed ? "展开侧栏" : "收起侧栏"}
            size="sm"
            icon={collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
            onClick={onToggle}
          />
        )}
      </div>
    </aside>
  );
}
