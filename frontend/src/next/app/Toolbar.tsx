import { Keyboard, Monitor, Moon, Sun } from "lucide-react";
import { useState } from "react";
import { useLocation } from "react-router";
import { useAutomationStatus, useManagerStatus, useRunningProfiles } from "../features/app/api";
import { THEME_OPTIONS, usePreferences, type ThemePreference } from "../features/settings/preferences";
import { formatShortcut } from "../shared/lib/hotkeys";
import { Badge, IconButton, Menu, MenuRadioGroup, Popover, Skeleton, Spinner, StatusDot } from "../ui";
import { navItemFor } from "./nav";

const THEME_ICONS: Record<ThemePreference, typeof Sun> = { system: Monitor, light: Sun, dark: Moon };

export function Toolbar({ onShowShortcuts }: { onShowShortcuts: () => void }) {
  const location = useLocation();
  const title = navItemFor(location.pathname)?.label ?? "";

  return (
    <header className="flex h-toolbar shrink-0 items-center gap-3 border-b border-border bg-surface px-4">
      <div className="min-w-0 flex-1 truncate text-base font-semibold text-fg">{title}</div>
      <div className="flex shrink-0 items-center gap-1.5">
        <AutomationIndicator />
        <RunningIndicator />
        <ThemeMenu />
        <IconButton label="快捷键" shortcut="?" icon={<Keyboard className="h-4 w-4" />} onClick={onShowShortcuts} />
      </div>
    </header>
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
