import {
  AlertTriangle,
  Archive,
  Bug,
  CheckCircle2,
  Clock3,
  Copy,
  Cpu,
  Database,
  Download,
  Edit3,
  Flame,
  Folder,
  Globe2,
  KeyRound,
  Laptop,
  LayoutGrid,
  LogOut,
  MapPin,
  MoreVertical,
  Network,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Square,
  StickyNote,
  Trash2,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type BrowserUpdateResult, type DeviceTemplateSummary, type LaunchMode, type ManagerUpdateResult, type Profile, type ProfileGroup, type ProxyPreset, type SentenceAssembled, type SentenceDraftResult, type SentenceOptions } from "../lib/api";
import { AppUpdateStatus } from "./AppUpdateStatus";
import { AutomationIndicator } from "./AutomationIndicator";
import { BackupPanel } from "./BackupPanel";
import { GroupsPanel } from "./GroupsPanel";
import { KernelPanel } from "./KernelPanel";
import { LlmSettingsCard } from "./LlmSettingsCard";
import { LinkabilityPanel } from "./LinkabilityPanel";
import { SiteCheckPanel } from "./SiteCheckPanel";
import { ProxyPresetsPanel } from "./ProxyPresetsPanel";
import { SentenceProfileDialog } from "./SentenceProfileDialog";
import { TrashPanel } from "./TrashPanel";
import { formatDate } from "../lib/format";
import { StatusIndicator } from "./StatusIndicator";

interface EnvironmentManagerProps {
  profiles: Profile[];
  groups: ProfileGroup[];
  proxyPresets: ProxyPreset[];
  trashProfiles: Profile[];
  error: string | null;
  authRequired: boolean;
  authUsername: string | null;
  versions?: { app: string | null; kernel: string | null } | null;
  onNew: () => void;
  onEdit: (id: string) => void;
  onDuplicate: (profile: Profile) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onUpdateNotes: (id: string, notes: string | null) => Promise<void>;
  onLaunch: (id: string, mode: LaunchMode) => Promise<void>;
  onBatchLaunch: (ids: string[], mode: LaunchMode) => Promise<void>;
  onStop: (id: string) => Promise<void>;
  onBatchStop: (ids: string[]) => Promise<void>;
  onRefresh: () => Promise<void>;
  onCreateGroup: (name: string, color?: string | null) => Promise<void>;
  onDeleteGroup: (id: string) => Promise<void>;
  onCreateProxyPreset: (data: { name: string; proxy: string; mode: string }) => Promise<void>;
  onCreateProxyPresets: (items: { name: string; proxy: string; mode: string }[]) => Promise<void>;
  onDeleteProxyPreset: (id: string) => Promise<void>;
  onRestoreProfile: (id: string) => Promise<void>;
  onPurgeProfile: (id: string) => Promise<void>;
  onAccount: () => void;
  onLogout: () => void;
}

type ManagerSection = "profiles" | "groups" | "proxies" | "kernel" | "ai" | "checks" | "links" | "backup" | "trash";
type UpdateNotice = {
  tone: "success" | "info" | "error";
  text: string;
  result?: ManagerUpdateResult;
  browser?: BrowserUpdateResult;
};

const DISPOSABLE_REGIONS: { code: string; label: string }[] = [
  { code: "US", label: "美国" },
  { code: "JP", label: "日本" },
  { code: "GB", label: "英国" },
  { code: "DE", label: "德国" },
  { code: "FR", label: "法国" },
  { code: "NL", label: "荷兰" },
  { code: "TW", label: "台湾" },
  { code: "HK", label: "香港" },
  { code: "SG", label: "新加坡" },
  { code: "KR", label: "韩国" },
  { code: "AU", label: "澳大利亚" },
  { code: "CA", label: "加拿大" },
];

const navItems: { id: ManagerSection; label: string; icon: typeof LayoutGrid }[] = [
  { id: "profiles", label: "环境管理", icon: LayoutGrid },
  { id: "groups", label: "分组管理", icon: Folder },
  { id: "proxies", label: "代理管理", icon: Globe2 },
  { id: "kernel", label: "浏览器内核", icon: Cpu },
  { id: "ai", label: "AI 设置", icon: Sparkles },
  { id: "checks", label: "指纹检测", icon: ShieldCheck },
  { id: "links", label: "关联分析", icon: Network },
  { id: "backup", label: "数据备份", icon: Database },
  { id: "trash", label: "回收站", icon: Archive },
];

function proxyType(profile: Profile) {
  const value = profile.proxy?.trim();
  if (!value) return "直连";
  const scheme = value.split(":", 1)[0]?.toUpperCase();
  if (scheme === "VLESS" || scheme === "VMESS" || scheme === "TROJAN" || scheme === "SS") {
    return scheme;
  }
  if (scheme === "SOCKS5") return "SOCKS5";
  if (scheme === "HTTPS") return "HTTPS";
  if (scheme === "HTTP") return "HTTP";
  return "代理";
}

function proxyHost(profile: Profile) {
  if (!profile.proxy?.trim()) return profile.proxy_geo?.ip ?? "本地网络";
  if (profile.proxy_geo?.ip) return profile.proxy_geo.ip;
  const value = profile.proxy.trim();
  try {
    const url = new URL(value);
    return `${url.hostname}${url.port ? `:${url.port}` : ""}`;
  } catch {
    return value.includes("://") ? value.split("://", 2)[1]?.split(/[?#]/, 1)[0] ?? "已配置" : value;
  }
}

function locationText(profile: Profile) {
  const geo = profile.proxy_geo;
  if (!geo) return profile.proxy ? "打开后检测" : "启动时检测本地出口";
  const country = [geo.country_code, geo.country].filter(Boolean).join(" - ");
  const city = [geo.region, geo.city].filter(Boolean).join(" / ");
  return [country, city].filter(Boolean).join(" · ") || "未知地区";
}

function engineLabel(profile: Profile) {
  return profile.browser_engine === "cloakbrowser" ? "伪装画像" : "稳定原生";
}

function noteText(profile: Profile) {
  return profile.notes?.trim() || "-";
}

function lastOpenedText(profile: Profile) {
  if (profile.status === "running") return "运行中";
  const exitReason = profile.last_exit_reason;
  if (exitReason?.startsWith("异常退出") || exitReason?.startsWith("启动失败")) return "上次启动失败";
  return formatDate(profile.last_opened_at || profile.updated_at);
}

function launchFailureReason(profile: Profile) {
  const reason = profile.last_exit_reason;
  if (reason === "异常退出（代码 76）") return "授权并发已满，请先关闭其他伪装画像";
  if (reason === "异常退出（代码 77）") return "CloakBrowser 授权无效或已过期";
  if (reason === "异常退出（代码 78）") return "CloakBrowser 授权服务器连接失败";
  if (reason === "异常退出（代码 79）") return "本地授权配置异常";
  return reason || "上一次启动未成功";
}

function hasLaunchFailure(profile: Profile) {
  const reason = profile.last_exit_reason;
  return profile.status !== "running" && Boolean(
    reason?.startsWith("异常退出") || reason?.startsWith("启动失败"),
  );
}

export function EnvironmentManager({
  profiles,
  groups,
  proxyPresets,
  trashProfiles,
  error,
  authRequired,
  authUsername,
  versions = null,
  onNew,
  onEdit,
  onDuplicate,
  onDelete,
  onUpdateNotes,
  onLaunch,
  onBatchLaunch,
  onStop,
  onBatchStop,
  onRefresh,
  onCreateGroup,
  onDeleteGroup,
  onCreateProxyPreset,
  onCreateProxyPresets,
  onDeleteProxyPreset,
  onRestoreProfile,
  onPurgeProfile,
  onAccount,
  onLogout,
}: EnvironmentManagerProps) {
  const [section, setSection] = useState<ManagerSection>("profiles");
  const [search, setSearch] = useState("");
  const [groupFilter, setGroupFilter] = useState("all");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [batchMenuOpen, setBatchMenuOpen] = useState(false);
  const [batchBusy, setBatchBusy] = useState<null | "launch" | "stop" | "duplicate" | "delete">(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const [savingNoteId, setSavingNoteId] = useState<string | null>(null);
  const [noteErrorId, setNoteErrorId] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);
  const [updateNotice, setUpdateNotice] = useState<UpdateNotice | null>(null);
  const [disposableRegion, setDisposableRegion] = useState("US");
  const [disposableBusy, setDisposableBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [sentenceText, setSentenceText] = useState("");
  const [sentenceBusy, setSentenceBusy] = useState(false);
  const [sentenceError, setSentenceError] = useState<string | null>(null);
  const [sentenceNotice, setSentenceNotice] = useState<string | null>(null);
  const [sentenceDraft, setSentenceDraft] = useState<SentenceDraftResult | null>(null);
  const [sentenceOptions, setSentenceOptions] = useState<SentenceOptions | null>(null);
  const [sentenceTemplates, setSentenceTemplates] = useState<DeviceTemplateSummary[]>([]);
  const [sentenceConfirming, setSentenceConfirming] = useState(false);
  const [sentenceConfirmError, setSentenceConfirmError] = useState<string | null>(null);
  const sentenceRequestRef = useRef(0);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!(event.target instanceof Element)) return;
      const insideBatchMenu = event.target.closest("[data-batch-menu-trigger], [data-batch-menu-panel]");
      const insideRowMenu = event.target.closest("[data-row-menu-trigger], [data-row-menu-panel]");
      if (!insideBatchMenu) setBatchMenuOpen(false);
      if (!insideRowMenu) setMenuOpenId(null);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setBatchMenuOpen(false);
        setMenuOpenId(null);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return profiles.filter((profile) => {
      if (groupFilter !== "all" && (profile.group_name || "未分组") !== groupFilter) {
        return false;
      }
      if (!q) return true;
      const haystack = [
        profile.name,
        profile.proxy ?? "",
        profile.notes ?? "",
        profile.user_agent ?? "",
        profile.locale ?? "",
        profile.timezone ?? "",
        profile.tags.map((tag) => tag.tag).join(" "),
      ].join(" ").toLowerCase();
      return haystack.includes(q);
    });
  }, [groupFilter, profiles, search]);

  const runningCount = profiles.filter((profile) => profile.status === "running").length;
  const allFilteredSelected = filtered.length > 0 && filtered.every((profile) => selectedIds.has(profile.id));
  const selectedProfiles = useMemo(
    () => profiles.filter((profile) => selectedIds.has(profile.id)),
    [profiles, selectedIds],
  );
  const selectedStoppedProfiles = selectedProfiles.filter((profile) => profile.status !== "running");
  const selectedRunningProfiles = selectedProfiles.filter((profile) => profile.status === "running");
  const sectionTitle = {
    profiles: "环境管理",
    groups: "分组管理",
    proxies: "代理管理",
    kernel: "浏览器内核",
    ai: "AI 设置",
    checks: "指纹检测",
    links: "关联分析",
    backup: "数据备份",
    trash: "回收站",
  }[section];
  const sectionSubtitle = {
    profiles: `总数 ${profiles.length} · 已打开 ${runningCount}`,
    groups: `共 ${groups.length} 个分组`,
    proxies: `共 ${proxyPresets.length} 个保存代理`,
    kernel: "查看、更新和清理 CloakBrowser 内核",
    ai: "配置 AI 功能共用的 LLM 接口（自备密钥）",
    checks: "用公开检测网站验收画像，导出报告",
    links: "哪些画像会被检测方关联成同一个人",
    backup: "完整备份 Cookie 与登录状态，或只导出配置",
    trash: `共 ${trashProfiles.length} 个待清理浏览器 · 7 天后自动清理`,
  }[section];

  const toggleSelected = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAllFiltered = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allFilteredSelected) {
        filtered.forEach((profile) => next.delete(profile.id));
      } else {
        filtered.forEach((profile) => next.add(profile.id));
      }
      return next;
    });
  };

  const runRowAction = async (id: string, action: () => Promise<void>) => {
    setBusyId(id);
    try {
      await action();
    } finally {
      setBusyId(null);
      setMenuOpenId(null);
    }
  };

  const runBatchAction = async (
    kind: NonNullable<typeof batchBusy>,
    action: () => Promise<void>,
    clearSelection = false,
  ) => {
    setBatchBusy(kind);
    try {
      await action();
      if (clearSelection) {
        setSelectedIds(new Set());
      }
    } finally {
      setBatchBusy(null);
      setBatchMenuOpen(false);
    }
  };

  const handleBatchLaunch = async () => {
    const ids = selectedStoppedProfiles.map((profile) => profile.id);
    if (ids.length === 0) return;
    await runBatchAction("launch", () => onBatchLaunch(ids, "manual"));
  };

  const handleBatchStop = async () => {
    const ids = selectedRunningProfiles.map((profile) => profile.id);
    if (ids.length === 0) return;
    await runBatchAction("stop", () => onBatchStop(ids));
  };

  const handleBatchDuplicate = async () => {
    if (selectedProfiles.length === 0) return;
    await runBatchAction("duplicate", async () => {
      for (const profile of selectedProfiles) {
        await onDuplicate(profile);
      }
    });
  };

  const handleBatchDelete = async () => {
    if (selectedProfiles.length === 0) return;
    if (!confirm(`确定删除选中的 ${selectedProfiles.length} 个浏览器吗？删除后会进入回收站。`)) return;
    await runBatchAction("delete", async () => {
      for (const profile of selectedProfiles) {
        await onDelete(profile.id);
      }
    }, true);
  };

  const noteValue = (profile: Profile) => noteDrafts[profile.id] ?? profile.notes ?? "";

  const updateNoteDraft = (id: string, value: string) => {
    setNoteErrorId((current) => (current === id ? null : current));
    setNoteDrafts((prev) => ({ ...prev, [id]: value }));
  };

  const clearNoteDraft = (id: string) => {
    setNoteDrafts((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  };

  const saveNote = async (profile: Profile, value: string) => {
    const next = value.trim();
    const current = profile.notes?.trim() ?? "";
    if (next === current) {
      setNoteErrorId((currentId) => (currentId === profile.id ? null : currentId));
      clearNoteDraft(profile.id);
      return;
    }
    setSavingNoteId(profile.id);
    setNoteErrorId(null);
    try {
      await onUpdateNotes(profile.id, next || null);
      clearNoteDraft(profile.id);
    } catch {
      setNoteErrorId(profile.id);
    } finally {
      setSavingNoteId(null);
    }
  };

  const handleDelete = async (profile: Profile) => {
    if (!confirm(`确定删除「${profile.name}」吗？删除后会进入回收站，7 天内可以恢复。`)) return;
    await runRowAction(profile.id, () => onDelete(profile.id));
  };

  const handleCreateDisposable = async () => {
    setDisposableBusy(true);
    setActionError(null);
    try {
      await api.createDisposable({ region: disposableRegion });
      await onRefresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "一次性身份创建失败");
    } finally {
      setDisposableBusy(false);
    }
  };

  const handleDraftSentence = async () => {
    const sentence = sentenceText.trim();
    if (!sentence || sentenceBusy) return;
    const requestId = ++sentenceRequestRef.current;
    setSentenceBusy(true);
    setSentenceError(null);
    setSentenceNotice(null);
    setSentenceConfirmError(null);
    try {
      const [draft, options, templates] = await Promise.all([
        api.draftFromSentence(sentence),
        api.getSentenceOptions().catch(() => null),
        api.listDeviceTemplates().catch(() => [] as DeviceTemplateSummary[]),
      ]);
      if (sentenceRequestRef.current !== requestId) return; // 已被取消，草稿丢弃
      setSentenceOptions(options);
      setSentenceTemplates(templates);
      setSentenceDraft(draft);
    } catch (err) {
      if (sentenceRequestRef.current !== requestId) return;
      setSentenceError(err instanceof Error ? err.message : "解析失败");
    } finally {
      if (sentenceRequestRef.current === requestId) setSentenceBusy(false);
    }
  };

  const handleCancelSentenceDraft = () => {
    sentenceRequestRef.current += 1;
    setSentenceBusy(false);
  };

  const handleConfirmSentence = async (assembled: SentenceAssembled) => {
    setSentenceConfirming(true);
    setSentenceConfirmError(null);
    try {
      const result = await api.createFromSentence({ sentence: sentenceText.trim(), assembled });
      setSentenceDraft(null);
      setSentenceText("");
      await onRefresh();
      if (result.warnings?.length) {
        setSentenceNotice(result.warnings.join("；"));
      }
    } catch (err) {
      setSentenceConfirmError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setSentenceConfirming(false);
    }
  };

  const handleBurn = async (profile: Profile) => {
    if (!confirm(`确定焚毁「${profile.name}」吗？\n焚毁会永久删除这个一次性画像的全部数据（Cookie、登录状态、历史记录和本地文件），不可恢复，也不会进入回收站。`)) return;
    setActionError(null);
    try {
      await api.burnProfile(profile.id);
      await onRefresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "焚毁失败");
    }
  };

  const handleUpdateManager = async () => {
    if (updating) return;
    if (runningCount > 0 && !confirm("当前还有浏览器正在运行。升级会拉取新代码并重建面板，建议先关闭浏览器。确定继续升级吗？")) {
      return;
    }
    setUpdating(true);
    setUpdateNotice(null);
    try {
      const result = await api.updateManager();
      const browser = await api.updateBrowser();
      setUpdateNotice({
        tone: result.updated || browser.updated ? "success" : "info",
        text: `${result.message}\n${browser.message}`,
        result,
        browser,
      });
      await onRefresh();
    } catch (err) {
      setUpdateNotice({
        tone: "error",
        text: err instanceof Error ? err.message : "升级失败",
      });
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div className="flex h-screen bg-surface-0 text-slate-900">
      <aside className="flex w-[248px] shrink-0 flex-col border-r border-border bg-white">
        <div className="px-4 pb-4 pt-6">
          <div className="mb-6 flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-md bg-accent text-sm font-bold text-white">
              C
            </div>
            <div>
              <div className="text-lg font-semibold tracking-tight">CloakBrowser</div>
              <div className="text-xs text-slate-400">本地环境管理</div>
            </div>
          </div>
          <button onClick={onNew} className="btn-primary flex h-10 w-full items-center justify-center gap-2">
            <Plus className="h-4 w-4" />
            <span>新建浏览器</span>
          </button>
        </div>

        <nav className="flex-1 space-y-1 px-3">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.label}
                onClick={() => setSection(item.id)}
                className={`flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm font-medium ${
                  section === item.id
                    ? "bg-accent/10 text-accent"
                    : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                }`}
              >
                <Icon className="h-4 w-4" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="border-t border-border p-4">
          <div className="rounded-md border border-border bg-slate-50 p-3">
            <div className="truncate text-sm font-medium text-slate-800">
              {authUsername || "本地用户"}
            </div>
            <div className="mt-1 text-xs text-slate-500">管理员</div>
            {authRequired && (
              <div className="mt-3 flex gap-2">
                <button onClick={onAccount} className="btn-secondary flex-1 px-2 text-xs">
                  账号
                </button>
                <button onClick={onLogout} className="btn-secondary flex-1 px-2 text-xs">
                  退出
                </button>
              </div>
            )}
          </div>
          {versions && (
            <div className="mt-3 space-y-0.5 px-1 text-xs text-slate-400" aria-label="版本信息">
              <div>Manager {versions.app ? `v${versions.app}` : "源码版"}</div>
              <div className="truncate" title={versions.kernel ?? undefined}>内核 {versions.kernel ?? "未下载"}</div>
            </div>
          )}
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-border bg-white px-5">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">{sectionTitle}</h1>
            <div className="mt-0.5 text-xs text-slate-500">
              {sectionSubtitle}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <AutomationIndicator />
            <button
              className="btn-secondary flex items-center gap-1.5 px-3 disabled:opacity-60"
              title="从 GitHub 拉取最新代码并重建本地面板"
              disabled={updating}
              onClick={() => void handleUpdateManager()}
            >
              <RefreshCw className={`h-4 w-4 ${updating ? "animate-spin" : ""}`} />
              <span>{updating ? "升级中" : "升级"}</span>
            </button>
            <button className="btn-secondary px-2.5" title="刷新" onClick={() => void onRefresh()}>
              <RefreshCw className="h-4 w-4" />
            </button>
            {authRequired && (
              <>
                <button className="btn-secondary px-2.5" title="账号设置" onClick={onAccount}>
                  <KeyRound className="h-4 w-4" />
                </button>
                <button className="btn-secondary px-2.5" title="退出登录" onClick={onLogout}>
                  <LogOut className="h-4 w-4" />
                </button>
              </>
            )}
          </div>
        </header>

        <AppUpdateStatus
          available={updateNotice?.result?.download_url ? updateNotice.result.after ?? null : null}
          downloadUrl={updateNotice?.result?.download_url ?? null}
          runningCount={runningCount}
        />

        {updateNotice && (
          <div className={`border-b px-5 py-3 ${
            updateNotice.tone === "error"
              ? "border-red-200 bg-red-50"
              : updateNotice.tone === "success"
              ? "border-emerald-200 bg-emerald-50"
              : "border-blue-200 bg-blue-50"
          }`}>
            <div className={`flex items-start gap-3 rounded-md border bg-white/70 px-3 py-2 text-sm ${
              updateNotice.tone === "error"
                ? "border-red-200 text-red-900"
                : updateNotice.tone === "success"
                ? "border-emerald-200 text-emerald-900"
                : "border-blue-200 text-blue-900"
            }`}>
              <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${
                updateNotice.tone === "error"
                  ? "bg-red-100 text-red-700"
                  : updateNotice.tone === "success"
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-blue-100 text-blue-700"
              }`}>
                {updateNotice.tone === "error" ? <AlertTriangle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
              </div>
              <div className="min-w-0 flex-1">
                <div className="font-semibold">
                  {updateNotice.tone === "error"
                    ? "升级失败"
                    : updateNotice.result?.download_url
                    ? `发现新版本${updateNotice.result.after ? ` ${updateNotice.result.after}` : ""}，请下载安装`
                    : updateNotice.result?.restart_required || updateNotice.browser?.restart_required
                    ? "升级完成，需要重启"
                    : "升级检查完成"}
                </div>
                <div className="mt-0.5 whitespace-pre-wrap break-words text-xs leading-5">{updateNotice.text}</div>
                {updateNotice.result?.download_url && (
                  <a
                    className="btn-primary mt-2 inline-flex items-center gap-1.5 px-3 text-xs"
                    href={updateNotice.result.download_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Download className="h-3.5 w-3.5" />
                    <span>手动下载</span>
                  </a>
                )}
                {updateNotice.browser && (
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 rounded-md bg-white/70 px-2.5 py-2 text-xs">
                    <span>Wrapper：{updateNotice.browser.wrapper_version || "未知"}</span>
                    <span>平台：{updateNotice.browser.platform || "未知"}</span>
                    <span>已安装：{updateNotice.browser.installed_version || updateNotice.browser.available_version || "未知"}</span>
                    <span className={updateNotice.browser.binary_verified ? "font-medium text-emerald-700" : "font-medium text-red-700"}>
                      内核：{updateNotice.browser.binary_verified ? "已验证" : "未验证"}
                    </span>
                  </div>
                )}
                {updateNotice.result?.restart_required && (
                  <div className="mt-1 text-xs font-medium">请关闭当前终端里的 Manager，然后重新运行启动命令。</div>
                )}
                {!updateNotice.result?.restart_required && updateNotice.browser?.restart_required && (
                  <div className="mt-1 text-xs font-medium">请关闭运行中的浏览器画像，再重新打开画像使用新内核。</div>
                )}
              </div>
              <button
                className="shrink-0 rounded p-1 text-current opacity-60 hover:bg-white hover:opacity-100"
                title="关闭提示"
                onClick={() => setUpdateNotice(null)}
              >
                <XCircle className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {error && (
          <div className="border-b border-amber-200 bg-amber-50 px-5 py-3">
            <div className="flex items-start gap-3 rounded-md border border-amber-200 bg-white/70 px-3 py-2 text-sm text-amber-900">
              <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-amber-100 text-amber-700">
                <AlertTriangle className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <div className="font-semibold">管理服务需要刷新</div>
                <div className="mt-0.5 break-words text-xs leading-5 text-amber-800">{error}</div>
              </div>
            </div>
          </div>
        )}

        {section === "profiles" && (
        <section className="flex min-h-0 flex-1 flex-col p-4">
          <div className="mb-3 grid grid-cols-[180px_minmax(260px,1fr)_auto] gap-3">
            <select
              className="input h-11"
              value={groupFilter}
              onChange={(event) => setGroupFilter(event.target.value)}
            >
              <option value="all">全部分组</option>
              <option value="未分组">未分组</option>
              {groups.map((group) => (
                <option key={group.id} value={group.name}>{group.name}</option>
              ))}
            </select>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
              <input
                className="input h-11 pl-10"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索名称、代理、备注、UA"
              />
            </div>
            <div className="flex h-11 items-center gap-2 rounded-md border border-border bg-white px-3 text-sm text-slate-600">
              <StatusIndicator status={runningCount > 0 ? "running" : "stopped"} size="md" />
              <span>已打开 ({runningCount})</span>
            </div>
          </div>

          <div className="mb-3 flex flex-wrap items-center gap-2">
            <button
              className="btn-primary flex items-center gap-1.5 disabled:opacity-50"
              disabled={selectedStoppedProfiles.length === 0 || batchBusy !== null}
              onClick={() => void handleBatchLaunch()}
              title={selectedStoppedProfiles.length > 0 ? `打开选中的 ${selectedStoppedProfiles.length} 个浏览器` : "请选择未打开的浏览器"}
            >
              <Play className="h-4 w-4" />
              <span>{batchBusy === "launch" ? "打开中..." : "打开"}</span>
            </button>
            <button
              className="btn-secondary flex items-center gap-1.5 disabled:opacity-50"
              disabled={selectedRunningProfiles.length === 0 || batchBusy !== null}
              onClick={() => void handleBatchStop()}
              title={selectedRunningProfiles.length > 0 ? `关闭选中的 ${selectedRunningProfiles.length} 个浏览器` : "请选择运行中的浏览器"}
            >
              <Square className="h-4 w-4" />
              <span>{batchBusy === "stop" ? "关闭中..." : "关闭"}</span>
            </button>
            <div className="relative">
              <button
                className="btn-secondary px-2.5 disabled:opacity-50"
                title="更多批量操作"
                disabled={selectedProfiles.length === 0 || batchBusy !== null}
                onClick={() => setBatchMenuOpen((current) => !current)}
                data-batch-menu-trigger="true"
              >
                <MoreVertical className="h-4 w-4" />
              </button>
              {batchMenuOpen && selectedProfiles.length > 0 && (
                <div className="absolute left-0 top-11 z-20 w-44 rounded-md border border-blue-200 bg-white p-1 shadow-xl" data-batch-menu-panel="true">
                  <button
                    className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
                    onClick={() => {
                      setBatchMenuOpen(false);
                      void handleBatchDuplicate();
                    }}
                  >
                    <Copy className="h-4 w-4" />
                    <span>{batchBusy === "duplicate" ? "复制中..." : `复制选中 (${selectedProfiles.length})`}</span>
                  </button>
                  <button
                    className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50"
                    onClick={() => {
                      setBatchMenuOpen(false);
                      void handleBatchDelete();
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                    <span>{batchBusy === "delete" ? "删除中..." : `删除选中 (${selectedProfiles.length})`}</span>
                  </button>
                  <div className="my-1 border-t border-border" />
                  <button
                    className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
                    onClick={() => {
                      setSelectedIds(new Set());
                      setBatchMenuOpen(false);
                    }}
                  >
                    <XCircle className="h-4 w-4" />
                    <span>清空选择</span>
                  </button>
                </div>
              )}
            </div>
            <div className="flex min-w-[260px] flex-1 items-center gap-2 sm:max-w-md">
              <input
                className="input h-9 flex-1 text-sm"
                value={sentenceText}
                onChange={(event) => setSentenceText(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void handleDraftSentence();
                }}
                placeholder="一句话建号：建个美国号，西雅图，喜欢露营摄影"
                aria-label="一句话建号"
                disabled={sentenceBusy}
              />
              <button
                className="btn-secondary flex shrink-0 items-center gap-1.5 disabled:opacity-50"
                disabled={sentenceBusy || !sentenceText.trim()}
                onClick={() => void handleDraftSentence()}
                title="用一句话解析出完整画像：先预览、可修改，确认后才创建"
              >
                <Sparkles className="h-4 w-4" />
                <span>{sentenceBusy ? "解析中..." : "一句话建号"}</span>
              </button>
              {sentenceBusy && (
                <button
                  className="shrink-0 text-xs text-slate-500 hover:text-slate-700"
                  onClick={handleCancelSentenceDraft}
                >
                  取消
                </button>
              )}
            </div>
            <div className="ml-auto flex items-center gap-2">
              {actionError && <span className="text-xs text-red-600">{actionError}</span>}
              <select
                className="input h-9 w-[104px] text-sm"
                value={disposableRegion}
                onChange={(event) => setDisposableRegion(event.target.value)}
                title="一次性身份的地区（决定时区与语言）"
                aria-label="一次性身份地区"
              >
                {DISPOSABLE_REGIONS.map((region) => (
                  <option key={region.code} value={region.code}>{region.label}</option>
                ))}
              </select>
              <button
                className="btn-secondary flex items-center gap-1.5 disabled:opacity-50"
                disabled={disposableBusy}
                onClick={() => void handleCreateDisposable()}
                title="一键创建一个一次性的全新身份：独立设备模板，时区/语言按地区配套，用完可焚毁"
              >
                <Sparkles className="h-4 w-4" />
                <span>{disposableBusy ? "创建中..." : "一次性身份"}</span>
              </button>
            </div>
            {sentenceError && <div className="w-full text-xs text-red-600">{sentenceError}</div>}
            {sentenceNotice && <div className="w-full text-xs text-emerald-600">{sentenceNotice}</div>}
          </div>

          <div className="min-h-0 flex-1 overflow-hidden rounded-md border border-border bg-white">
            <div className="h-full overflow-auto">
              <table className="w-full min-w-[980px] table-fixed border-separate border-spacing-0 text-sm">
                <colgroup>
                  <col className="w-10" />
                  <col className="w-14" />
                  <col className="w-20" />
                  <col className="w-40" />
                  <col className="w-[195px]" />
                  <col className="w-[105px]" />
                  <col className="w-[165px]" />
                  <col className="w-[200px]" />
                </colgroup>
                <thead className="sticky top-0 z-10 bg-slate-50 text-xs text-slate-500">
                  <tr>
                    <th className="border-b border-border px-4 py-3 text-left">
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-slate-300"
                        checked={allFilteredSelected}
                        onChange={toggleAllFiltered}
                      />
                    </th>
                    <th className="whitespace-nowrap border-b border-border px-2 py-3 text-left font-medium">编号</th>
                    <th className="border-b border-border px-3 py-3 text-left font-medium">分组</th>
                    <th className="border-b border-border px-3 py-3 text-left font-medium">名称</th>
                    <th className="border-b border-border px-3 py-3 text-left font-medium">IP / 代理</th>
                    <th className="border-b border-border px-3 py-3 text-left font-medium">最近状态</th>
                    <th className="border-b border-border px-3 py-3 text-left font-medium">备注</th>
                    <th className="border-b border-border px-3 py-3 text-left font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={8} className="px-4 py-16 text-center text-sm text-slate-400">
                        {profiles.length === 0 ? "还没有浏览器，点击左侧新建浏览器开始。" : "没有匹配的浏览器。"}
                      </td>
                    </tr>
                  )}
                  {filtered.map((profile, index) => (
                    <tr key={profile.id} className="group hover:bg-slate-50">
                      <td className="border-b border-border px-4 py-3 align-middle">
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-slate-300"
                          checked={selectedIds.has(profile.id)}
                          onChange={() => toggleSelected(profile.id)}
                        />
                      </td>
                      <td className="border-b border-border px-2 py-3 align-middle text-slate-600">
                        {index + 1}
                      </td>
                      <td className="border-b border-border px-3 py-3 align-middle">
                        <button
                          className="max-w-full truncate rounded px-1.5 py-1 text-left text-slate-700 hover:bg-slate-100 hover:text-accent"
                          onClick={() => onEdit(profile.id)}
                          title="编辑分组"
                        >
                          {profile.group_name || "未分组"}
                        </button>
                      </td>
                      <td className="border-b border-border px-3 py-3 align-middle">
                        <div className="flex min-w-0 items-center gap-3">
                          <div className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-600">
                            <Laptop className="h-4 w-4" />
                            <span className="absolute -bottom-0.5 -right-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full border-2 border-white bg-white">
                              <StatusIndicator status={profile.status} size="md" />
                            </span>
                          </div>
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              <button
                                className="block max-w-[180px] truncate text-left font-semibold text-slate-900 hover:text-accent"
                                onClick={() => onEdit(profile.id)}
                                title={profile.name}
                              >
                                {profile.name}
                              </button>
                              {profile.disposable && (
                                <span className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                                  一次性
                                </span>
                              )}
                            </div>
                            <button
                              className="mt-1 inline-flex items-center gap-1 text-xs text-slate-400 hover:text-accent"
                              onClick={() => onEdit(profile.id)}
                              title="编辑名称"
                            >
                              <Pencil className="h-3 w-3" />
                              <span className="truncate">{engineLabel(profile)}</span>
                            </button>
                          </div>
                        </div>
                      </td>
                      <td className="border-b border-border px-3 py-3 align-middle">
                        <div
                          className="truncate font-semibold text-slate-900"
                          title={proxyHost(profile)}
                        >
                          {proxyHost(profile)}
                        </div>
                        <div className="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-slate-500">
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 font-medium">{proxyType(profile)}</span>
                          <MapPin className="h-3 w-3 shrink-0 text-slate-400" />
                          <span className="truncate" title={locationText(profile)}>{locationText(profile)}</span>
                        </div>
                      </td>
                      <td className="border-b border-border px-3 py-3 align-middle">
                        <div className={`inline-flex items-center gap-1.5 ${hasLaunchFailure(profile) ? "text-amber-700" : "text-slate-600"}`}>
                          {hasLaunchFailure(profile) ? (
                            <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-500" />
                          ) : (
                            <Clock3 className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                          )}
                          <span title={hasLaunchFailure(profile) ? launchFailureReason(profile) : undefined}>
                            {lastOpenedText(profile)}
                          </span>
                        </div>
                      </td>
                      <td className="border-b border-border px-3 py-3 align-middle">
                        <div className="group/note relative">
                          <StickyNote className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                          <input
                            className="h-9 w-full rounded-md border border-transparent bg-slate-50 pl-8 pr-14 text-sm text-slate-700 outline-none transition focus:border-accent focus:bg-white focus:ring-2 focus:ring-accent/10"
                            value={noteValue(profile)}
                            onChange={(event) => updateNoteDraft(profile.id, event.target.value)}
                            onBlur={(event) => void saveNote(profile, event.currentTarget.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault();
                                event.currentTarget.blur();
                              }
                            }}
                            placeholder="添加备注"
                            title={noteText(profile)}
                          />
                          <span className={`pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] transition ${
                            noteErrorId === profile.id
                              ? "text-red-500 opacity-100"
                              : "text-slate-400"
                          } ${
                            savingNoteId === profile.id || noteErrorId === profile.id
                              ? "opacity-100"
                              : "opacity-0 group-focus-within/note:opacity-100"
                          }`}>
                            {savingNoteId === profile.id ? "保存中" : noteErrorId === profile.id ? "保存失败" : "自动保存"}
                          </span>
                        </div>
                      </td>
                      <td className="relative border-b border-border px-3 py-3 align-middle">
                        <div className="flex items-center gap-2">
                          {profile.status === "running" ? (
                            <button
                              className="btn-danger flex h-9 min-w-16 items-center justify-center gap-1.5 whitespace-nowrap px-3"
                              disabled={busyId === profile.id}
                              onClick={() => void runRowAction(profile.id, () => onStop(profile.id))}
                            >
                              <Square className="h-3.5 w-3.5" />
                              <span>关闭</span>
                            </button>
                          ) : (
                            <button
                              className="btn-primary flex h-9 min-w-16 items-center justify-center gap-1.5 whitespace-nowrap px-3"
                              disabled={busyId === profile.id}
                              onClick={() => void runRowAction(profile.id, () => onLaunch(profile.id, "manual"))}
                            >
                              <Play className="h-3.5 w-3.5" />
                              <span>打开</span>
                            </button>
                          )}
                          {profile.status !== "running" && (
                            <button
                              className="btn-secondary flex h-9 w-9 items-center justify-center px-0"
                              disabled={busyId === profile.id}
                              title="调试启动（开启本机 CDP）"
                              aria-label="调试启动"
                              onClick={() => void runRowAction(profile.id, () => onLaunch(profile.id, "debug"))}
                            >
                              <Bug className="h-3.5 w-3.5" />
                            </button>
                          )}
                          <button
                            className="btn-secondary flex h-9 w-9 items-center justify-center px-0"
                            title="编辑"
                            onClick={() => onEdit(profile.id)}
                          >
                            <Edit3 className="h-3.5 w-3.5" />
                          </button>
                          <button
                            className="btn-secondary flex h-9 w-9 items-center justify-center px-0"
                            title="更多"
                            data-row-menu-trigger="true"
                            onClick={() => setMenuOpenId((current) => current === profile.id ? null : profile.id)}
                          >
                            <MoreVertical className="h-3.5 w-3.5" />
                          </button>
                        </div>

                        {menuOpenId === profile.id && (
                          <div className="absolute right-3 top-12 z-20 w-44 rounded-md border border-blue-200 bg-white p-1 shadow-xl" data-row-menu-panel="true">
                            <button
                              className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm text-accent hover:bg-accent/10"
                              onClick={() => {
                                setMenuOpenId(null);
                                onEdit(profile.id);
                              }}
                            >
                              <Edit3 className="h-4 w-4" />
                              <span>编辑</span>
                            </button>
                            <button
                              className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
                              onClick={() => {
                                setMenuOpenId(null);
                                void runRowAction(profile.id, () => onDuplicate(profile));
                              }}
                            >
                              <Copy className="h-4 w-4" />
                              <span>复制</span>
                            </button>
                            <button
                              className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50"
                              onClick={() => {
                                setMenuOpenId(null);
                                void handleDelete(profile);
                              }}
                            >
                              <Trash2 className="h-4 w-4" />
                              <span>删除</span>
                            </button>
                            {profile.disposable && (
                              <button
                                className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm font-medium text-red-700 hover:bg-red-50"
                                onClick={() => {
                                  setMenuOpenId(null);
                                  void handleBurn(profile);
                                }}
                              >
                                <Flame className="h-4 w-4" />
                                <span>焚毁（彻底删除）</span>
                              </button>
                            )}
                            <div className="my-1 border-t border-border" />
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
            <span>共 {filtered.length} 条</span>
            <span>50 条/页</span>
          </div>
        </section>
        )}

        {section === "groups" && (
          <GroupsPanel groups={groups} profiles={profiles} onCreateGroup={onCreateGroup} onDeleteGroup={onDeleteGroup} />
        )}

        {section === "proxies" && (
          <ProxyPresetsPanel
            proxyPresets={proxyPresets}
            onCreateProxyPreset={onCreateProxyPreset}
            onCreateProxyPresets={onCreateProxyPresets}
            onDeleteProxyPreset={onDeleteProxyPreset}
          />
        )}

        {section === "trash" && (
          <TrashPanel trashProfiles={trashProfiles} onRestoreProfile={onRestoreProfile} onPurgeProfile={onPurgeProfile} />
        )}

        {section === "kernel" && <KernelPanel runningCount={runningCount} />}
        {section === "ai" && <LlmSettingsCard />}
        {section === "checks" && <SiteCheckPanel profiles={profiles} onRefresh={onRefresh} />}
        {section === "links" && <LinkabilityPanel />}
        {section === "backup" && <BackupPanel runningCount={runningCount} onRefresh={onRefresh} />}
      </main>

      {sentenceDraft && (
        <SentenceProfileDialog
          sentence={sentenceText.trim()}
          draft={sentenceDraft}
          options={sentenceOptions}
          templates={sentenceTemplates}
          confirming={sentenceConfirming}
          error={sentenceConfirmError}
          onCancel={() => setSentenceDraft(null)}
          onConfirm={(assembled) => void handleConfirmSentence(assembled)}
        />
      )}
    </div>
  );
}
