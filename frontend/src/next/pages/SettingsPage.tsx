import { ChevronLeft, ChevronRight, Clock, Cpu, Database, Info, KeyRound, Plug, ScanSearch, ShieldCheck, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { Link, Navigate, useParams } from "react-router";
import { useManagerStatus } from "../features/app/api";
import { cn } from "../shared/lib/cn";
import { PageHeader } from "../ui";
import { AboutSection } from "../features/settings/AboutSection";
import { AccountSection } from "../features/settings/AccountSection";
import { AgentAccessSection } from "../features/settings/AgentAccessSection";
import { AiSection } from "../features/settings/AiSection";
import { AutomationSection } from "../features/settings/AutomationSection";
import { KernelSection } from "../features/settings/KernelSection";
import { VaultSection } from "../features/settings/VaultSection";

/** 检测 and 数据 used to be top-level pages; they keep their own routes under /settings. */
const PAGES = [
  { id: "checks", label: "检测", desc: "检测报告、进化修复和环境关联分析", icon: ScanSearch, tile: "from-[#4fb0ff] to-[#5ad0a0]" },
  { id: "data", label: "数据", desc: "备份、恢复、导出配置和回收站", icon: Database, tile: "from-[#ffb36b] to-[#ffd36b]" },
] as const;

const SECTIONS = [
  { id: "kernel", label: "浏览器内核", desc: "版本、授权密钥和更新方式", icon: Cpu, tile: "from-[#6e8bff] to-[#7b6bff]" },
  { id: "ai", label: "AI 接口", desc: "用来按人设生成一周的浏览剧本", icon: Sparkles, tile: "from-[#c06bff] to-[#ff6bb0]" },
  { id: "agent", label: "AI 接入", desc: "让外部 AI 工具来操作环境", icon: Plug, tile: "from-[#6bd0ff] to-[#6e8bff]" },
  { id: "vault", label: "保险库", desc: "AI 注册账号时生成的密码，AI 只拿到引用", icon: KeyRound, tile: "from-[#8bd35a] to-[#4fb0ff]" },
  { id: "automation", label: "自动化", desc: "定时任务只在这个时间段内运行", icon: Clock, tile: "from-[#ffb36b] to-[#ff7b6b]" },
  { id: "account", label: "账号与安全", desc: "管理员账号、密码和退出登录", icon: ShieldCheck, tile: "from-[#5ad0a0] to-[#4fb0ff]" },
  { id: "about", label: "关于与更新", desc: "版本信息、检查更新", icon: Info, tile: "from-[#9aa3b8] to-[#6b7390]" },
] as const;

export function SettingsPage() {
  const { section } = useParams();
  if (!section) {
    return (
      <div className="flex min-h-full flex-col gap-6 pb-8 pt-2">
        <PageHeader title="设置" description="检测、数据、内核、AI、保险库、自动化、账号与更新。" />
        <nav aria-label="设置分类" className="min-w-0">
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {[...PAGES, ...SECTIONS].map((item) => (
              <li key={item.id}>
                <SettingsCard item={item} />
              </li>
            ))}
          </ul>
        </nav>
      </div>
    );
  }
  const current = SECTIONS.find((item) => item.id === section);
  if (!current) return <Navigate to="/settings" replace />;
  return (
    <div className="flex min-h-full flex-col gap-6 pb-8 pt-2">
      <h1 className="sr-only">设置</h1>
      <BackToSettings />
      <div className="mx-auto w-full min-w-0 max-w-form">
        <CurrentSection id={current.id} />
      </div>
    </div>
  );
}

/** A full page (检测, 数据) opened from the settings cards, with the same way back. */
export function SettingsSubpage({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-col pt-2">
      <BackToSettings />
      {children}
    </div>
  );
}

function BackToSettings() {
  return (
    <Link to="/settings" className="inline-flex w-fit items-center gap-1 rounded-full px-3 py-1.5 text-sm font-medium text-accent hover:bg-surface/60">
      <ChevronLeft className="h-4 w-4" aria-hidden />
      设置
    </Link>
  );
}

type SectionCard = (typeof PAGES)[number] | (typeof SECTIONS)[number];

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

function CurrentSection({ id }: { id: (typeof SECTIONS)[number]["id"] }) {
  switch (id) {
    case "kernel":
      return <KernelSection />;
    case "ai":
      return <AiSection />;
    case "agent":
      return <AgentAccessSection />;
    case "vault":
      return <VaultSection />;
    case "automation":
      return <AutomationSection />;
    case "account":
      return <AccountSection />;
    case "about":
      return <AboutSection />;
  }
}
