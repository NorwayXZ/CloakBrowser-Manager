import {
  AlertTriangle,
  Archive,
  Bug,
  CheckCircle2,
  Clock3,
  Copy,
  Database,
  Download,
  Edit3,
  Folder,
  Globe2,
  KeyRound,
  Laptop,
  LayoutGrid,
  LogOut,
  MapPin,
  MoreVertical,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Search,
  Square,
  StickyNote,
  Trash2,
  Upload,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type BrowserUpdateResult, type LaunchMode, type ManagerUpdateResult, type Profile, type ProfileGroup, type ProxyPreset } from "../lib/api";
import { StatusIndicator } from "./StatusIndicator";

interface EnvironmentManagerProps {
  profiles: Profile[];
  groups: ProfileGroup[];
  proxyPresets: ProxyPreset[];
  trashProfiles: Profile[];
  error: string | null;
  authRequired: boolean;
  authUsername: string | null;
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

type ManagerSection = "profiles" | "groups" | "proxies" | "backup" | "trash";
type ProxyInputMode = "single" | "batch";
type ProxyMode = "http" | "https" | "socks5" | "vless" | "vmess" | "trojan" | "ss";
type UpdateNotice = {
  tone: "success" | "info" | "error";
  text: string;
  result?: ManagerUpdateResult;
  browser?: BrowserUpdateResult;
};

const navItems: { id: ManagerSection; label: string; icon: typeof LayoutGrid }[] = [
  { id: "profiles", label: "环境管理", icon: LayoutGrid },
  { id: "groups", label: "分组管理", icon: Folder },
  { id: "proxies", label: "代理管理", icon: Globe2 },
  { id: "backup", label: "数据备份", icon: Database },
  { id: "trash", label: "回收站", icon: Archive },
];

const DIRECT_PROXY_MODES: ProxyMode[] = ["http", "https", "socks5"];
const LINK_PROXY_MODES: ProxyMode[] = ["vless", "vmess", "trojan", "ss"];

function isDirectProxyMode(mode: string): mode is ProxyMode {
  return DIRECT_PROXY_MODES.includes(mode as ProxyMode);
}

function normalizeProxyHost(host: string) {
  let value = host.trim();
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) {
    try {
      value = new URL(value).hostname;
    } catch {
      // Keep the original value and let backend validation report the error.
    }
  }
  if (value.includes(":") && !value.startsWith("[") && !value.endsWith("]")) {
    return `[${value}]`;
  }
  return value;
}

function buildDirectProxyUrl(
  mode: ProxyMode,
  host: string,
  port: string,
  username = "",
  password = "",
) {
  const cleanHost = normalizeProxyHost(host);
  const cleanPort = port.trim();
  if (!cleanHost || !cleanPort) return "";
  const user = username.trim();
  const pass = password.trim();
  const auth = user || pass
    ? `${encodeURIComponent(user)}:${encodeURIComponent(pass)}@`
    : "";
  return `${mode}://${auth}${cleanHost}:${cleanPort}`;
}

function proxyNameFromUrl(proxy: string, fallbackMode: string, index: number) {
  try {
    const url = new URL(proxy);
    const fragment = decodeURIComponent(url.hash.replace(/^#/, "")).trim();
    if (fragment) return fragment.slice(0, 64);
    if (url.hostname) return `${fallbackMode.toUpperCase()} ${url.hostname}${url.port ? `:${url.port}` : ""}`.slice(0, 64);
  } catch {
    // Fall through to generic name.
  }
  return `${fallbackMode.toUpperCase()} 代理 ${index}`;
}

function parseProxyBatchLine(line: string, defaultMode: ProxyMode, index: number) {
  const value = line.trim();
  if (!value || value.startsWith("#")) return null;

  const scheme = value.split(":", 1)[0]?.toLowerCase() as ProxyMode;
  if ([...DIRECT_PROXY_MODES, ...LINK_PROXY_MODES].includes(scheme)) {
    return {
      name: proxyNameFromUrl(value, scheme, index),
      proxy: value,
      mode: scheme,
    };
  }

  const parts = value.split(":");
  if (parts.length === 2 || parts.length >= 4) {
    const [host, port, username = "", password = ""] = parts;
    const proxy = buildDirectProxyUrl(defaultMode, host ?? "", port ?? "", username, password);
    if (!proxy) return null;
    return {
      name: `${defaultMode.toUpperCase()} ${host}:${port}`.slice(0, 64),
      proxy,
      mode: defaultMode,
    };
  }

  return null;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function proxyType(profile: Profile) {
  const value = profile.proxy?.trim();
  if (!value) return "未配置";
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
  if (profile.proxy_geo?.ip) return profile.proxy_geo.ip;
  const value = profile.proxy?.trim();
  if (!value) return "-";
  try {
    const url = new URL(value);
    return `${url.hostname}${url.port ? `:${url.port}` : ""}`;
  } catch {
    return value.includes("://") ? value.split("://", 2)[1]?.split(/[?#]/, 1)[0] ?? "已配置" : value;
  }
}

function locationText(profile: Profile) {
  const geo = profile.proxy_geo;
  if (!profile.proxy) return "未配置代理";
  if (!geo) return "打开后检测";
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
  if (profile.last_exit_reason?.startsWith("异常退出")) return profile.last_exit_reason;
  return formatDate(profile.last_opened_at || profile.updated_at);
}

export function EnvironmentManager({
  profiles,
  groups,
  proxyPresets,
  trashProfiles,
  error,
  authRequired,
  authUsername,
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
  const [groupName, setGroupName] = useState("");
  const [proxyName, setProxyName] = useState("");
  const [proxyInputMode, setProxyInputMode] = useState<ProxyInputMode>("single");
  const [proxyMode, setProxyMode] = useState<ProxyMode>("socks5");
  const [proxyHostInput, setProxyHostInput] = useState("");
  const [proxyPortInput, setProxyPortInput] = useState("");
  const [proxyUsernameInput, setProxyUsernameInput] = useState("");
  const [proxyPasswordInput, setProxyPasswordInput] = useState("");
  const [proxyValue, setProxyValue] = useState("");
  const [proxyBatchText, setProxyBatchText] = useState("");
  const [proxyError, setProxyError] = useState<string | null>(null);
  const [proxySaving, setProxySaving] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [updateNotice, setUpdateNotice] = useState<UpdateNotice | null>(null);
  const [backupBusy, setBackupBusy] = useState<"export" | "import" | null>(null);
  const [backupNotice, setBackupNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const backupInputRef = useRef<HTMLInputElement>(null);

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
    backup: "数据备份",
    trash: "回收站",
  }[section];
  const sectionSubtitle = {
    profiles: `总数 ${profiles.length} · 已打开 ${runningCount}`,
    groups: `共 ${groups.length} 个分组`,
    proxies: `共 ${proxyPresets.length} 个保存代理`,
    backup: "导出或恢复浏览器配置、分组和代理库",
    trash: `共 ${trashProfiles.length} 个待清理浏览器 · 7 天后自动清理`,
  }[section];

  const handleExportConfiguration = async () => {
    setBackupBusy("export");
    setBackupNotice(null);
    try {
      const backup = await api.exportConfiguration();
      const blob = new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `cloakbrowser-configuration-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setBackupNotice({ tone: "success", text: "配置备份已下载。文件包含代理和 Cookie，请妥善保管。" });
    } catch (err) {
      setBackupNotice({ tone: "error", text: err instanceof Error ? err.message : "导出失败" });
    } finally {
      setBackupBusy(null);
    }
  };

  const handleImportConfiguration = async (file: File | null) => {
    if (!file) return;
    setBackupBusy("import");
    setBackupNotice(null);
    try {
      const parsed: unknown = JSON.parse(await file.text());
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("备份文件格式不正确");
      }
      const result = await api.importConfiguration(parsed as Record<string, unknown>);
      await onRefresh();
      setBackupNotice({
        tone: "success",
        text: `已导入 ${result.profiles} 个浏览器配置、${result.groups} 个新分组、${result.proxy_presets} 个代理。`,
      });
    } catch (err) {
      setBackupNotice({ tone: "error", text: err instanceof Error ? err.message : "导入失败" });
    } finally {
      setBackupBusy(null);
      if (backupInputRef.current) backupInputRef.current.value = "";
    }
  };

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

  const handleDeleteGroup = async (group: ProfileGroup) => {
    const count = profiles.filter((profile) => profile.group_name === group.name).length;
    const detail = count > 0 ? `其中 ${count} 个浏览器会回到“未分组”。` : "";
    if (!confirm(`确定删除分组「${group.name}」吗？${detail}`)) return;
    await onDeleteGroup(group.id);
  };

  const handleDeleteProxyPreset = async (preset: ProxyPreset) => {
    if (!confirm(`确定删除保存代理「${preset.name}」吗？不会影响已经使用这个代理的浏览器。`)) return;
    await onDeleteProxyPreset(preset.id);
  };

  const handlePurgeProfile = async (profile: Profile) => {
    if (!confirm(`确定彻底删除「${profile.name}」吗？此操作不可恢复。`)) return;
    await onPurgeProfile(profile.id);
  };

  const handleCreateGroup = async () => {
    const name = groupName.trim();
    if (!name) return;
    await onCreateGroup(name);
    setGroupName("");
  };

  const handleCreateProxyPreset = async () => {
    setProxyError(null);
    const name = proxyName.trim();
    if (!name) {
      setProxyError("请先填写代理名称");
      return;
    }

    const proxy = isDirectProxyMode(proxyMode)
      ? buildDirectProxyUrl(proxyMode, proxyHostInput, proxyPortInput, proxyUsernameInput, proxyPasswordInput)
      : proxyValue.trim();
    if (!proxy) {
      setProxyError(isDirectProxyMode(proxyMode) ? "请填写主机和端口" : "请粘贴代理链接");
      return;
    }

    setProxySaving(true);
    try {
      await onCreateProxyPreset({ name, proxy, mode: proxyMode });
      setProxyName("");
      setProxyHostInput("");
      setProxyPortInput("");
      setProxyUsernameInput("");
      setProxyPasswordInput("");
      setProxyValue("");
    } catch (err) {
      setProxyError(err instanceof Error ? err.message : "保存代理失败");
    } finally {
      setProxySaving(false);
    }
  };

  const handleCreateProxyBatch = async () => {
    setProxyError(null);
    const items = proxyBatchText
      .split(/\r?\n/)
      .reduce<{ name: string; proxy: string; mode: string }[]>((acc, line, index) => {
        const item = parseProxyBatchLine(line, proxyMode, index + 1);
        if (item) acc.push(item);
        return acc;
      }, []);
    if (items.length === 0) {
      setProxyError("没有识别到可保存的代理，请检查格式");
      return;
    }
    setProxySaving(true);
    try {
      await onCreateProxyPresets(items);
      setProxyBatchText("");
    } catch (err) {
      setProxyError(err instanceof Error ? err.message : "批量保存代理失败");
    } finally {
      setProxySaving(false);
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
                  {updateNotice.tone === "error" ? "升级失败" : updateNotice.result?.restart_required ? "升级完成，需要重启" : "升级检查完成"}
                </div>
                <div className="mt-0.5 whitespace-pre-wrap break-words text-xs leading-5">{updateNotice.text}</div>
                {updateNotice.result?.restart_required && (
                  <div className="mt-1 text-xs font-medium">请关闭当前终端里的 Manager，然后重新运行启动命令。</div>
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
                    <th className="border-b border-border px-3 py-3 text-left font-medium">最近打开</th>
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
                            <button
                              className="block max-w-[180px] truncate text-left font-semibold text-slate-900 hover:text-accent"
                              onClick={() => onEdit(profile.id)}
                              title={profile.name}
                            >
                              {profile.name}
                            </button>
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
                        <div className="inline-flex items-center gap-1.5 text-slate-600">
                          <Clock3 className="h-3.5 w-3.5 text-slate-400" />
                          <span>{lastOpenedText(profile)}</span>
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
          <section className="flex min-h-0 flex-1 flex-col p-4">
            <div className="mb-4 rounded-md border border-border bg-white p-4">
              <div className="grid grid-cols-[minmax(220px,360px)_auto] gap-3">
                <input
                  className="input h-11"
                  value={groupName}
                  onChange={(event) => setGroupName(event.target.value)}
                  placeholder="输入分组名称，例如 美国账号"
                />
                <button
                  className="btn-primary px-5"
                  onClick={() => void handleCreateGroup()}
                  disabled={!groupName.trim()}
                >
                  新建分组
                </button>
              </div>
            </div>

            <div className="overflow-hidden rounded-md border border-border bg-white">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium">分组名称</th>
                    <th className="px-4 py-3 text-left font-medium">浏览器数量</th>
                    <th className="px-4 py-3 text-left font-medium">创建时间</th>
                    <th className="w-32 px-4 py-3 text-left font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="border-t border-border px-4 py-3 font-medium">未分组</td>
                    <td className="border-t border-border px-4 py-3 text-slate-600">
                      {profiles.filter((profile) => !profile.group_name || profile.group_name === "未分组").length}
                    </td>
                    <td className="border-t border-border px-4 py-3 text-slate-400">系统默认</td>
                    <td className="border-t border-border px-4 py-3 text-slate-400">不可删除</td>
                  </tr>
                  {groups.map((group) => (
                    <tr key={group.id} className="hover:bg-slate-50">
                      <td className="border-t border-border px-4 py-3 font-medium">{group.name}</td>
                      <td className="border-t border-border px-4 py-3 text-slate-600">
                        {profiles.filter((profile) => profile.group_name === group.name).length}
                      </td>
                      <td className="border-t border-border px-4 py-3 text-slate-600">{formatDate(group.created_at)}</td>
                      <td className="border-t border-border px-4 py-3">
                        <button
                          className="btn-secondary px-2.5 text-red-600"
                          onClick={() => void handleDeleteGroup(group)}
                        >
                          删除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {section === "proxies" && (
          <section className="flex min-h-0 flex-1 flex-col p-4">
            <div className="mb-4 overflow-hidden rounded-md border border-border bg-white">
              <div className="flex border-b border-border px-5">
                {[
                  ["single", "单个添加"],
                  ["batch", "批量导入"],
                ].map(([id, label]) => (
                  <button
                    key={id}
                    className={`mr-8 h-12 border-b-2 text-sm font-semibold ${
                      proxyInputMode === id
                        ? "border-accent text-accent"
                        : "border-transparent text-slate-500 hover:text-slate-900"
                    }`}
                    onClick={() => {
                      setProxyInputMode(id as ProxyInputMode);
                      setProxyError(null);
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>

              <div className="grid gap-5 p-5 xl:grid-cols-[390px_minmax(0,1fr)]">
                <div className="rounded-md border border-blue-100 bg-blue-50 p-4 text-sm leading-6 text-slate-700">
                  <div className="mb-2 font-semibold text-slate-900">支持的代理格式</div>
                  <div>HTTP / HTTPS / SOCKS5 可分开填写主机、端口、账号、密码。</div>
                  <div className="mt-3 font-mono text-xs leading-6 text-blue-700">
                    <div>192.168.0.1:8000</div>
                    <div>192.168.0.1:8000:user:pass</div>
                    <div>socks5://user:pass@192.168.0.1:8000</div>
                    <div>http://[2001:db8::1]:8000</div>
                    <div>vless://... / vmess://... / trojan://... / ss://...</div>
                  </div>
                  <div className="mt-3 text-xs text-slate-500">
                    同名代理会更新原记录；保存后可在创建/编辑浏览器时直接选择。
                  </div>
                </div>

                <div>
                  <div className="mb-4 grid gap-3 lg:grid-cols-[minmax(180px,260px)_180px_minmax(180px,1fr)]">
                    <div>
                      <label className="label">代理名称</label>
                      <input
                        className="input h-11"
                        value={proxyName}
                        onChange={(event) => setProxyName(event.target.value)}
                        placeholder="例如 美国 SOCKS5"
                        disabled={proxyInputMode === "batch"}
                      />
                    </div>
                    <div>
                      <label className="label">代理类型</label>
                      <select
                        className="input h-11"
                        value={proxyMode}
                        onChange={(event) => {
                          setProxyMode(event.target.value as ProxyMode);
                          setProxyError(null);
                        }}
                      >
                        <option value="socks5">SOCKS5</option>
                        <option value="http">HTTP</option>
                        <option value="https">HTTPS</option>
                        <option value="vless">VLESS</option>
                        <option value="vmess">VMESS</option>
                        <option value="trojan">TROJAN</option>
                        <option value="ss">Shadowsocks</option>
                      </select>
                    </div>
                    <div>
                      <label className="label">检测方式</label>
                      <div className="flex h-11 items-center rounded-md border border-slate-300 bg-slate-50 px-3 text-sm text-slate-500">
                        浏览器启动时自动检测出口 IP / 地区
                      </div>
                    </div>
                  </div>

                  {proxyInputMode === "single" && isDirectProxyMode(proxyMode) && (
                    <div className="space-y-4">
                      <div className="grid gap-3 lg:grid-cols-[minmax(220px,1fr)_140px]">
                        <div>
                          <label className="label">主机</label>
                          <input
                            className="input h-11"
                            value={proxyHostInput}
                            onChange={(event) => setProxyHostInput(event.target.value)}
                            placeholder="192.168.100.1 或 proxy.example.com"
                          />
                        </div>
                        <div>
                          <label className="label">端口</label>
                          <input
                            className="input h-11 no-spin"
                            value={proxyPortInput}
                            onChange={(event) => setProxyPortInput(event.target.value)}
                            placeholder="1090"
                          />
                        </div>
                      </div>
                      <div className="grid gap-3 lg:grid-cols-2">
                        <div>
                          <label className="label">代理账号</label>
                          <input
                            className="input h-11"
                            value={proxyUsernameInput}
                            onChange={(event) => setProxyUsernameInput(event.target.value)}
                            placeholder="没有账号就留空"
                          />
                        </div>
                        <div>
                          <label className="label">代理密码</label>
                          <input
                            className="input h-11"
                            type="password"
                            value={proxyPasswordInput}
                            onChange={(event) => setProxyPasswordInput(event.target.value)}
                            placeholder="没有密码就留空"
                          />
                        </div>
                      </div>
                      <div className="rounded-md bg-slate-50 px-3 py-2 font-mono text-xs text-slate-500">
                        {buildDirectProxyUrl(proxyMode, proxyHostInput, proxyPortInput, proxyUsernameInput, proxyPasswordInput) || "代理地址会自动拼接显示在这里"}
                      </div>
                    </div>
                  )}

                  {proxyInputMode === "single" && LINK_PROXY_MODES.includes(proxyMode) && (
                    <div>
                      <label className="label">代理链接</label>
                      <textarea
                        className="input min-h-32 resize-y font-mono text-xs"
                        value={proxyValue}
                        onChange={(event) => setProxyValue(event.target.value)}
                        placeholder="粘贴 vless://、vmess://、trojan:// 或 ss:// 链接"
                        spellCheck={false}
                      />
                    </div>
                  )}

                  {proxyInputMode === "batch" && (
                    <div>
                      <label className="label">批量代理</label>
                      <textarea
                        className="input min-h-48 resize-y font-mono text-xs"
                        value={proxyBatchText}
                        onChange={(event) => setProxyBatchText(event.target.value)}
                        placeholder={"一行一个代理，例如：\n192.168.0.1:8000\n192.168.0.1:8000:user:pass\nsocks5://user:pass@192.168.0.1:8000\nvless://..."}
                        spellCheck={false}
                      />
                      <div className="mt-2 text-xs text-slate-500">
                        裸 host:port 格式会按上方选择的代理类型保存；完整链接会按链接自己的协议保存。
                      </div>
                    </div>
                  )}

                  {proxyError && (
                    <div className="mt-4 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
                      <XCircle className="h-4 w-4" />
                      <span>{proxyError}</span>
                    </div>
                  )}

                  <div className="mt-4 flex items-center gap-3">
                    {proxyInputMode === "single" ? (
                      <button
                        className="btn-primary flex h-10 items-center gap-1.5 px-5"
                        onClick={() => void handleCreateProxyPreset()}
                        disabled={proxySaving}
                      >
                        <Plus className="h-4 w-4" />
                        <span>{proxySaving ? "保存中..." : "保存代理"}</span>
                      </button>
                    ) : (
                      <button
                        className="btn-primary flex h-10 items-center gap-1.5 px-5"
                        onClick={() => void handleCreateProxyBatch()}
                        disabled={proxySaving}
                      >
                        <Plus className="h-4 w-4" />
                        <span>{proxySaving ? "保存中..." : "批量保存"}</span>
                      </button>
                    )}
                    <div className="flex items-center gap-1.5 text-xs text-emerald-700">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      <span>支持带账号密码的 SOCKS5</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="overflow-hidden rounded-md border border-border bg-white">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium">名称</th>
                    <th className="px-4 py-3 text-left font-medium">代理模式</th>
                    <th className="px-4 py-3 text-left font-medium">代理地址</th>
                    <th className="px-4 py-3 text-left font-medium">创建时间</th>
                    <th className="w-32 px-4 py-3 text-left font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {proxyPresets.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-4 py-12 text-center text-slate-400">
                        暂无保存代理。可以保存“美国 SOCKS5”“香港 VLESS”这类常用代理。
                      </td>
                    </tr>
                  )}
                  {proxyPresets.map((preset) => (
                    <tr key={preset.id} className="hover:bg-slate-50">
                      <td className="border-t border-border px-4 py-3 font-medium">{preset.name}</td>
                      <td className="border-t border-border px-4 py-3">
                        <span className="rounded bg-slate-100 px-2 py-1 text-xs font-medium uppercase text-slate-700">
                          {preset.mode}
                        </span>
                      </td>
                      <td className="max-w-xl truncate border-t border-border px-4 py-3 font-mono text-xs text-slate-600" title={preset.proxy}>
                        {preset.proxy}
                      </td>
                      <td className="border-t border-border px-4 py-3 text-slate-600">{formatDate(preset.created_at)}</td>
                      <td className="border-t border-border px-4 py-3">
                        <button
                          className="btn-secondary px-2.5 text-red-600"
                          onClick={() => void handleDeleteProxyPreset(preset)}
                        >
                          删除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {section === "trash" && (
          <section className="flex min-h-0 flex-1 flex-col p-4">
            <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              删除后的浏览器会进入回收站，保留 7 天；可以恢复，也可以彻底删除。
            </div>
            <div className="overflow-hidden rounded-md border border-border bg-white">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium">名称</th>
                    <th className="px-4 py-3 text-left font-medium">分组</th>
                    <th className="px-4 py-3 text-left font-medium">删除时间</th>
                    <th className="w-56 px-4 py-3 text-left font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {trashProfiles.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-4 py-12 text-center text-slate-400">回收站为空</td>
                    </tr>
                  )}
                  {trashProfiles.map((profile) => (
                    <tr key={profile.id} className="hover:bg-slate-50">
                      <td className="border-t border-border px-4 py-3 font-medium">{profile.name}</td>
                      <td className="border-t border-border px-4 py-3 text-slate-600">{profile.group_name || "未分组"}</td>
                      <td className="border-t border-border px-4 py-3 text-slate-600">{formatDate(profile.deleted_at)}</td>
                      <td className="border-t border-border px-4 py-3">
                        <div className="flex gap-2">
                          <button className="btn-secondary px-2.5" onClick={() => void onRestoreProfile(profile.id)}>
                            恢复
                          </button>
                          <button className="btn-danger px-2.5" onClick={() => void handlePurgeProfile(profile)}>
                            彻底删除
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {section === "backup" && (
          <section className="flex min-h-0 flex-1 flex-col p-4">
            <div className="max-w-4xl overflow-hidden rounded-md border border-border bg-white">
              <div className="border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-slate-900">配置备份与恢复</h2>
                <p className="mt-1 text-xs leading-5 text-slate-500">
                  备份包含浏览器配置、分组、代理、Cookie JSON 和启动设置。代理密码与 Cookie 属于敏感信息，不要公开上传备份文件。
                </p>
              </div>
              <div className="grid gap-0 md:grid-cols-2">
                <div className="border-b border-border p-5 md:border-b-0 md:border-r">
                  <div className="flex items-start gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-700">
                      <Download className="h-4 w-4" />
                    </div>
                    <div>
                      <div className="text-sm font-semibold text-slate-900">导出配置</div>
                      <div className="mt-1 text-xs leading-5 text-slate-500">生成 JSON 文件，适合迁移设置或在修改前保留一份配置快照。</div>
                    </div>
                  </div>
                  <button
                    className="btn-primary mt-4 flex items-center gap-1.5 px-4 disabled:opacity-60"
                    disabled={backupBusy !== null}
                    onClick={() => void handleExportConfiguration()}
                  >
                    <Download className="h-4 w-4" />
                    <span>{backupBusy === "export" ? "导出中..." : "下载配置备份"}</span>
                  </button>
                </div>
                <div className="p-5">
                  <div className="flex items-start gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-emerald-50 text-emerald-700">
                      <Upload className="h-4 w-4" />
                    </div>
                    <div>
                      <div className="text-sm font-semibold text-slate-900">导入配置</div>
                      <div className="mt-1 text-xs leading-5 text-slate-500">导入为新的浏览器记录；同名代理会更新，同名分组不会重复创建。</div>
                    </div>
                  </div>
                  <input
                    ref={backupInputRef}
                    type="file"
                    accept="application/json,.json"
                    className="hidden"
                    onChange={(event) => void handleImportConfiguration(event.target.files?.[0] ?? null)}
                  />
                  <button
                    className="btn-secondary mt-4 flex items-center gap-1.5 px-4 disabled:opacity-60"
                    disabled={backupBusy !== null || runningCount > 0}
                    title={runningCount > 0 ? "请先关闭所有浏览器" : "选择配置备份文件"}
                    onClick={() => backupInputRef.current?.click()}
                  >
                    <Upload className="h-4 w-4" />
                    <span>{backupBusy === "import" ? "导入中..." : "选择备份文件"}</span>
                  </button>
                </div>
              </div>
              <div className="border-t border-amber-200 bg-amber-50 px-5 py-3 text-xs leading-5 text-amber-800">
                这个按钮不复制 Chrome 用户数据目录，所以不会备份网站缓存、历史记录或已经登录的网站会话。完整迁移登录状态时，关闭所有浏览器后复制系统里的整个 `CloakBrowser Manager` 数据目录。
              </div>
            </div>
            {backupNotice && (
              <div className={`mt-3 max-w-4xl rounded-md border px-4 py-3 text-sm ${backupNotice.tone === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-red-200 bg-red-50 text-red-800"}`}>
                {backupNotice.text}
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}
