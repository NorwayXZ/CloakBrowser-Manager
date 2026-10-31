import { ChevronLeft, ChevronRight, Clock, Cpu, Info, Monitor, Moon, Plug, ShieldCheck, Sparkles, Sun } from "lucide-react";
import { Link, Navigate, useParams } from "react-router";
import { useManagerStatus } from "../features/app/api";
import { THEME_OPTIONS, usePreferences, type ThemePreference } from "../features/settings/preferences";
import { cn } from "../shared/lib/cn";
import { PageHeader, Section, Spinner } from "../ui";
import { AboutSection } from "../features/settings/AboutSection";
import { AccountSection } from "../features/settings/AccountSection";
import { AgentAccessSection } from "../features/settings/AgentAccessSection";
import { AiSection } from "../features/settings/AiSection";
import { AutomationSection } from "../features/settings/AutomationSection";
import { KernelSection } from "../features/settings/KernelSection";

const SECTIONS = [
  { id: "appearance", label: "外观" },
  { id: "kernel", label: "浏览器内核", desc: "版本、授权密钥和更新方式", icon: Cpu, tile: "from-[#6e8bff] to-[#7b6bff]" },
  { id: "ai", label: "AI 接口", desc: "用来按人设生成一周的浏览剧本", icon: Sparkles, tile: "from-[#c06bff] to-[#ff6bb0]" },
  { id: "agent", label: "AI 接入", desc: "让外部 AI 工具来操作环境", icon: Plug, tile: "from-[#6bd0ff] to-[#6e8bff]" },
  { id: "automation", label: "自动化", desc: "定时任务只在这个时间段内运行", icon: Clock, tile: "from-[#ffb36b] to-[#ff7b6b]" },
  { id: "account", label: "账号与安全", desc: "管理员账号、密码和退出登录", icon: ShieldCheck, tile: "from-[#5ad0a0] to-[#4fb0ff]" },
  { id: "about", label: "关于与更新", desc: "版本信息、检查更新", icon: Info, tile: "from-[#9aa3b8] to-[#6b7390]" },
] as const;

export function SettingsPage() {
  const { section } = useParams();
  const current = SECTIONS.find((item) => item.id === (section ?? "appearance"));
  if (!current) return <Navigate to="/settings" replace />;
  const landing = current.id === "appearance";

  return (
    <div className="flex min-h-full flex-col gap-6 px-6 pb-8 pt-2 lg:px-10">
      {landing ? (
        <>
          <PageHeader title="设置" description="外观、内核、AI、自动化、账号与更新。" />
          <div className="grid min-w-0 grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
            <nav aria-label="设置分类" className="min-w-0 max-w-[820px]">
              <ul className="m-0 flex list-none flex-col gap-3 p-0">
                {SECTIONS.filter((item) => item.id !== "appearance").map((item) => (
                  <li key={item.id}>
                    <SettingsCard item={item as SectionCard} />
                  </li>
                ))}
              </ul>
            </nav>
            <AppearanceSettings />
          </div>
        </>
      ) : (
        <>
          <h1 className="sr-only">设置</h1>
          <Link to="/settings" className="inline-flex w-fit items-center gap-1 rounded-full px-3 py-1.5 text-sm font-medium text-accent hover:bg-surface/60">
            <ChevronLeft className="h-4 w-4" aria-hidden />
            设置
          </Link>
          <div className="min-w-0 max-w-form">
            <CurrentSection id={current.id} />
          </div>
        </>
      )}
    </div>
  );
}

type SectionCard = Extract<(typeof SECTIONS)[number], { icon: unknown }>;

function SettingsCard({ item }: { item: SectionCard }) {
  const status = useManagerStatus();
  const value =
    item.id === "kernel" ? status.data?.binary_version || null : item.id === "about" ? (status.data ? (status.data.app_version ? `v${status.data.app_version}` : "源码版") : null) : null;
  return (
    <Link
      to={`/settings/${item.id}`}
      className="glass group flex min-h-[72px] items-center gap-5 rounded-lg px-6 py-3.5 transition-transform duration-base hover:-translate-y-0.5"
    >
      <span aria-hidden className={cn("flex h-11 w-11 shrink-0 items-center justify-center rounded-[14px] bg-gradient-to-br text-accent-on shadow-raised", item.tile)}>
        <item.icon className="h-5 w-5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-md font-semibold tracking-tight text-fg">{item.label}</span>
        <span className="block truncate text-sm text-fg-2">{item.desc}</span>
      </span>
      {value && <span className="hidden shrink-0 font-mono text-xs text-fg-2 sm:block">{value}</span>}
      <ChevronRight className="h-5 w-5 shrink-0 text-fg-3 transition-transform duration-fast group-hover:translate-x-0.5" aria-hidden />
    </Link>
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
        <div className="grid grid-cols-1 gap-2.5">
          {THEME_OPTIONS.map((option) => {
            const Icon = ICONS[option.value];
            const checked = theme === option.value;
            return (
              <label
                key={option.value}
                className={cn(
                  "flex cursor-pointer flex-col gap-1 rounded-md border p-3.5 transition-colors duration-fast",
                  "has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
                  checked ? "border-accent bg-accent-soft" : "border-border/60 bg-surface/60 hover:bg-surface",
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

function CurrentSection({ id }: { id: (typeof SECTIONS)[number]["id"] }) {
  switch (id) {
    case "kernel":
      return <KernelSection />;
    case "ai":
      return <AiSection />;
    case "agent":
      return <AgentAccessSection />;
    case "automation":
      return <AutomationSection />;
    case "account":
      return <AccountSection />;
    case "about":
      return <AboutSection />;
    default:
      return <AppearanceSettings />;
  }
}
