import { Keyboard, Monitor, Moon, Sun } from "lucide-react";
import { useState } from "react";
import { Link, NavLink } from "react-router";
import { useAutomationStatus, useManagerStatus, useRunningProfiles } from "../features/app/api";
import { APP_UPDATE_ACTIVE, useUpdateCheck } from "../features/settings/api";
import { THEME_OPTIONS, usePreferences, type ThemePreference } from "../features/settings/preferences";
import { useAppUpdateWatcher } from "../features/settings/updateWatcher";
import { cn } from "../shared/lib/cn";
import { formatShortcut, useMediaQuery } from "../shared/lib/hotkeys";
import { Badge, IconButton, Menu, MenuRadioGroup, Popover, Skeleton, Spinner, StatusDot, Tooltip } from "../ui";
import { COMPACT_QUERY, NAV_ITEMS } from "./nav";

const THEME_ICONS: Record<ThemePreference, typeof Sun> = { system: Monitor, light: Sun, dark: Moon };

/**
 * The one bar at the top of every page: the product mark, the page switcher as
 * a floating pill, and the status indicators (update, automation, running
 * browsers, appearance, shortcuts). Below 900 px the pill shows icons only.
 */
export function Toolbar({ onShowShortcuts }: { onShowShortcuts: () => void }) {
  const compact = useMediaQuery(COMPACT_QUERY);

  return (
    <header className="flex h-20 shrink-0 items-center gap-4 px-6 lg:px-10">
      <div className="flex min-w-0 shrink-0 items-center gap-2.5">
        <div aria-hidden className="flex h-9 w-9 items-center justify-center rounded-[12px] bg-gradient-to-br from-accent-fill to-accent-fill-2 text-md font-bold text-accent-on shadow-raised">
          C
        </div>
        {!compact && <span className="text-md font-semibold tracking-tight text-fg">CloakBrowser</span>}
      </div>

      <nav aria-label="页面" className="glass-strong mx-auto flex min-w-0 items-center gap-1 rounded-full p-1.5">
        {NAV_ITEMS.map((item) => {
          const link = (
            <NavLink
              to={item.path}
              aria-label={compact ? item.label : undefined}
              // A plain string, not NavLink's function form: the tooltip's Slot would
              // stringify a function. NavLink sets aria-current on the active link.
              className={cn(
                "flex h-10 items-center justify-center gap-2 rounded-full text-sm font-medium text-fg-2 transition-[background-color,color,box-shadow] duration-fast hover:text-fg",
                "aria-[current=page]:bg-surface aria-[current=page]:font-semibold aria-[current=page]:text-fg aria-[current=page]:shadow-raised",
                compact ? "w-10" : "px-5",
              )}
            >
              {compact && <item.icon className="h-[18px] w-[18px]" aria-hidden />}
              {!compact && <span>{item.label}</span>}
            </NavLink>
          );
          return compact ? (
            <Tooltip key={item.path} content={item.label} shortcut={formatShortcut(`mod+${item.key}`)}>
              {link}
            </Tooltip>
          ) : (
            <span key={item.path}>{link}</span>
          );
        })}
      </nav>

      <div className="flex shrink-0 items-center gap-1.5">
        <UpdateIndicator />
        <AutomationIndicator />
        <RunningIndicator />
        <ThemeMenu />
        <IconButton label="快捷键" shortcut="?" icon={<Keyboard className="h-4 w-4" />} onClick={onShowShortcuts} />
      </div>
    </header>
  );
}

/** A running app update, its last result, or a new version the last check found. */
function UpdateIndicator() {
  const update = useAppUpdateWatcher();
  const check = useUpdateCheck();
  const state = update.data;
  let badge: { tone: "accent" | "success" | "danger" | "info"; text: string; spinning?: boolean } | null = null;
  if (state && APP_UPDATE_ACTIVE.has(state.phase)) {
    const pct = state.phase === "downloading" && state.total ? ` ${Math.min(100, Math.round(((state.done ?? 0) / state.total) * 100))}%` : "";
    badge = { tone: "accent", text: `${state.label ?? "正在更新"}${pct}`, spinning: true };
  } else if (state?.last_result) {
    badge = state.last_result.ok ? { tone: "success", text: `已更新到 ${state.last_result.to}` } : { tone: "danger", text: "更新没有成功" };
  } else if (check.data?.manager.download_url) {
    badge = { tone: "info", text: `新版本 ${check.data.manager.after ?? ""}`.trim() };
  }
  if (!badge) return null;
  return (
    <Link to="/settings/about" title="查看更新" className="inline-flex min-w-0 max-w-56 rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
      <Badge tone={badge.tone} className="max-w-full">
        {badge.spinning && <Spinner className="h-3 w-3" />}
        <span className="truncate">{badge.text}</span>
      </Badge>
    </Link>
  );
}

function AutomationIndicator() {
  const { data } = useAutomationStatus();
  if (!data?.active) return null;
  const text = `${data.label ?? "自动化"}${data.profile_name ? ` · ${data.profile_name}` : ""}`;
  return (
    <span title="自动化正在后台无头运行，不会弹出浏览器窗口" className="hidden min-w-0 max-w-56 md:inline-flex">
      <Badge tone="accent" className="max-w-full">
        <Spinner className="h-3 w-3" />
        <span className="truncate">{text}</span>
      </Badge>
    </span>
  );
}

function RunningIndicator() {
  const { data } = useManagerStatus();
  const [open, setOpen] = useState(false);
  const running = useRunningProfiles(open);
  const count = data?.running_count ?? 0;

  return (
    <Popover
      label="运行中的浏览器"
      onOpenChange={setOpen}
      trigger={
        <button
          type="button"
          className="flex h-8 items-center gap-1.5 rounded px-2.5 text-sm text-fg-2 transition-colors duration-fast hover:bg-surface-2 hover:text-fg"
        >
          <StatusDot status={count > 0 ? "running" : "stopped"} label={count > 0 ? `运行中 ${count}` : "未运行"} />
        </button>
      }
    >
      <div className="text-xs font-medium text-fg-3">运行中的浏览器</div>
      {running.isPending ? (
        <div className="mt-2 flex flex-col gap-2">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-4 w-32" />
        </div>
      ) : running.data && running.data.length > 0 ? (
        <ul className="mt-2 flex max-h-64 flex-col gap-1.5 overflow-y-auto">
          {running.data.map((profile) => (
            <li key={profile.id} className="flex min-w-0 items-center gap-2">
              <StatusDot status="running" label={profile.name} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-fg-2">现在没有打开的浏览器。</p>
      )}
    </Popover>
  );
}

function ThemeMenu() {
  const { theme, setTheme } = usePreferences();
  const Icon = THEME_ICONS[theme];
  const label = `外观：${THEME_OPTIONS.find((option) => option.value === theme)?.label ?? ""}`;
  return (
    <Menu trigger={<IconButton label={label} icon={<Icon className="h-4 w-4" />} />}>
      <MenuRadioGroup
        label="外观"
        value={theme}
        onValueChange={(value) => setTheme(value as ThemePreference)}
        options={THEME_OPTIONS.map((option) => {
          const OptionIcon = THEME_ICONS[option.value];
          return { value: option.value, label: option.label, icon: <OptionIcon className="h-4 w-4" /> };
        })}
      />
    </Menu>
  );
}

export const SHORTCUTS = [
  { combo: "mod+1", label: "环境" },
  { combo: "mod+2", label: "代理" },
  { combo: "mod+3", label: "检测" },
  { combo: "mod+4", label: "数据" },
  { combo: "mod+5", label: "设置" },
  { combo: "?", label: "显示快捷键" },
  { combo: "esc", label: "关闭对话框或菜单" },
].map((item) => ({ ...item, keys: formatShortcut(item.combo) }));
