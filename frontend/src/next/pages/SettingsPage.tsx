import { Monitor, Moon, Sun } from "lucide-react";
import { NavLink, Navigate, useParams } from "react-router";
import { THEME_OPTIONS, usePreferences, type ThemePreference } from "../features/settings/preferences";
import { cn } from "../shared/lib/cn";
import { PageHeader, Section, Spinner } from "../ui";
import { ComingSoonPanel } from "./ComingSoon";

const SECTIONS = [
  { id: "appearance", label: "外观" },
  { id: "kernel", label: "浏览器内核" },
  { id: "ai", label: "AI 接口" },
  { id: "automation", label: "自动化" },
  { id: "account", label: "账号与安全" },
  { id: "about", label: "关于与更新" },
] as const;

export function SettingsPage() {
  const { section = "appearance" } = useParams();
  const current = SECTIONS.find((item) => item.id === section);
  if (!current) return <Navigate to="/settings" replace />;

  return (
    <div className="flex min-h-full flex-col gap-6 p-6">
      <PageHeader title="设置" description="外观、内核、AI 接口、自动化、账号与更新。" />
      <div className="flex min-w-0 flex-col gap-6 md:flex-row">
        <nav aria-label="设置分类" className="shrink-0 md:w-44">
          <ul className="flex gap-1 overflow-x-auto md:flex-col">
            {SECTIONS.map((item) => (
              <li key={item.id} className="shrink-0">
                <NavLink
                  to={item.id === "appearance" ? "/settings" : `/settings/${item.id}`}
                  end
                  className={({ isActive }) =>
                    cn(
                      "block whitespace-nowrap rounded px-2.5 py-1.5 text-sm transition-colors duration-fast",
                      isActive || (item.id === current.id) ? "bg-surface font-medium text-fg shadow-raised" : "text-fg-2 hover:bg-surface-2 hover:text-fg",
                    )
                  }
                  aria-current={item.id === current.id ? "page" : undefined}
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 max-w-form flex-1">
          {current.id === "appearance" ? <AppearanceSettings /> : <SettingsPlaceholder label={current.label} />}
        </div>
      </div>
    </div>
  );
}

const ICONS: Record<ThemePreference, typeof Sun> = { system: Monitor, light: Sun, dark: Moon };
const HINTS: Record<ThemePreference, string> = {
  system: "跟着电脑的浅色 / 深色设置自动切换",
  light: "始终使用浅色",
  dark: "始终使用深色，适合夜间",
};

function AppearanceSettings() {
  const { theme, setTheme, resolvedTheme, saving } = usePreferences();
  return (
    <Section
      id="appearance"
      title="外观"
      description="只影响这个管理面板，不影响浏览器环境里网页看到的颜色偏好。"
      actions={saving ? <Spinner className="h-4 w-4 text-fg-3" label="正在保存" /> : undefined}
    >
      <fieldset>
        <legend className="mb-3 text-sm font-medium text-fg">主题</legend>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {THEME_OPTIONS.map((option) => {
            const Icon = ICONS[option.value];
            const checked = theme === option.value;
            return (
              <label
                key={option.value}
                className={cn(
                  "flex cursor-pointer flex-col gap-1 rounded-md border p-3 transition-colors duration-fast",
                  "has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
                  checked ? "border-accent bg-accent-soft" : "border-border bg-surface hover:bg-surface-2",
                )}
              >
                <input
                  type="radio"
                  name="theme"
                  value={option.value}
                  checked={checked}
                  onChange={() => setTheme(option.value)}
                  aria-label={option.label}
                  aria-describedby={`theme-hint-${option.value}`}
                  className="sr-only"
                />
                <span className="flex items-center gap-2 text-sm font-medium text-fg">
                  <Icon className={cn("h-4 w-4", checked ? "text-accent" : "text-fg-3")} aria-hidden />
                  {option.label}
                </span>
                <span id={`theme-hint-${option.value}`} className="text-xs text-fg-2">
                  {HINTS[option.value]}
                </span>
              </label>
            );
          })}
        </div>
        <p className="mt-3 text-xs text-fg-3">现在显示的是{resolvedTheme === "dark" ? "深色" : "浅色"}。设置保存在 Manager 里，换端口或恢复备份后仍然有效。</p>
      </fieldset>
    </Section>
  );
}

function SettingsPlaceholder({ label }: { label: string }) {
  return <ComingSoonPanel phase={6} what={`“${label}”设置`} />;
}
