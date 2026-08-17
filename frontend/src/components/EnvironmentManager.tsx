import {
  Archive,
  Bell,
  Bug,
  Copy,
  Edit3,
  Folder,
  Globe2,
  KeyRound,
  LayoutGrid,
  ListChecks,
  LogOut,
  MoreVertical,
  Play,
  Plus,
  RefreshCw,
  Search,
  Shield,
  Square,
  Tags,
  Trash2,
  Wifi,
} from "lucide-react";
import { useMemo, useState } from "react";
import type { LaunchMode, Profile } from "../lib/api";
import { StatusIndicator } from "./StatusIndicator";

interface EnvironmentManagerProps {
  profiles: Profile[];
  error: string | null;
  authRequired: boolean;
  authUsername: string | null;
  onNew: () => void;
  onEdit: (id: string) => void;
  onDuplicate: (profile: Profile) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onLaunch: (id: string, mode: LaunchMode) => Promise<void>;
  onStop: (id: string) => Promise<void>;
  onRefresh: () => Promise<void>;
  onAccount: () => void;
  onLogout: () => void;
}

const navItems = [
  { label: "环境管理", icon: LayoutGrid, active: true },
  { label: "分组管理", icon: Folder },
  { label: "代理管理", icon: Globe2 },
  { label: "应用中心", icon: Shield },
  { label: "回收站", icon: Archive },
];

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
  if (!geo) return profile.geoip ? "启动后检测" : "未检测";
  return [geo.country_code, geo.country].filter(Boolean).join(" / ") || "未知地区";
}

function engineLabel(profile: Profile) {
  return profile.browser_engine === "cloakbrowser" ? "伪装画像" : "稳定原生";
}

function platformIcon(profile: Profile) {
  if (profile.platform === "macos") return "●";
  if (profile.platform === "windows") return "■";
  return "◆";
}

export function EnvironmentManager({
  profiles,
  error,
  authRequired,
  authUsername,
  onNew,
  onEdit,
  onDuplicate,
  onDelete,
  onLaunch,
  onStop,
  onRefresh,
  onAccount,
  onLogout,
}: EnvironmentManagerProps) {
  const [search, setSearch] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return profiles;
    return profiles.filter((profile) => {
      const haystack = [
        profile.name,
        profile.proxy ?? "",
        profile.user_agent ?? "",
        profile.locale ?? "",
        profile.timezone ?? "",
        profile.tags.map((tag) => tag.tag).join(" "),
      ].join(" ").toLowerCase();
      return haystack.includes(q);
    });
  }, [profiles, search]);

  const runningCount = profiles.filter((profile) => profile.status === "running").length;
  const allFilteredSelected = filtered.length > 0 && filtered.every((profile) => selectedIds.has(profile.id));

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

  const handleDelete = async (profile: Profile) => {
    if (!confirm(`确定删除「${profile.name}」吗？浏览器数据会被永久移除。`)) return;
    await runRowAction(profile.id, () => onDelete(profile.id));
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
                className={`flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm font-medium ${
                  item.active
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
            <h1 className="text-xl font-semibold tracking-tight">环境管理</h1>
            <div className="mt-0.5 text-xs text-slate-500">
              总数 {profiles.length} · 已打开 {runningCount}
            </div>
          </div>
          <div className="flex items-center gap-2">
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
            <button className="btn-secondary px-2.5" title="通知">
              <Bell className="h-4 w-4" />
            </button>
          </div>
        </header>

        {error && (
          <div className="border-b border-red-200 bg-red-50 px-5 py-2 text-sm text-red-600">
            {error}
          </div>
        )}

        <section className="flex min-h-0 flex-1 flex-col p-4">
          <div className="mb-3 grid grid-cols-[180px_minmax(260px,1fr)_auto] gap-3">
            <select className="input h-11">
              <option>全部分组</option>
              <option>未分组</option>
            </select>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
              <input
                className="input h-11 pl-10"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索名称、代理、UA、标签"
              />
            </div>
            <label className="flex h-11 items-center gap-2 rounded-md border border-border bg-white px-3 text-sm text-slate-600">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-300"
                checked={runningCount > 0}
                readOnly
              />
              <span>已打开 ({runningCount})</span>
            </label>
          </div>

          <div className="mb-3 flex flex-wrap items-center gap-2">
            <button
              className="btn-primary flex items-center gap-1.5 disabled:opacity-50"
              disabled={selectedIds.size === 0}
            >
              <Play className="h-4 w-4" />
              <span>打开</span>
            </button>
            <button className="btn-secondary flex items-center gap-1.5 disabled:opacity-50" disabled>
              <Wifi className="h-4 w-4" />
              <span>窗口同步</span>
            </button>
            <button className="btn-secondary flex items-center gap-1.5 disabled:opacity-50" disabled={selectedIds.size === 0}>
              <Square className="h-4 w-4" />
              <span>关闭</span>
            </button>
            <button className="btn-secondary flex items-center gap-1.5 disabled:opacity-50" disabled={selectedIds.size === 0}>
              <Tags className="h-4 w-4" />
              <span>标签</span>
            </button>
            <button className="btn-secondary px-2.5" title="更多">
              <MoreVertical className="h-4 w-4" />
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-hidden rounded-md border border-border bg-white">
            <div className="h-full overflow-auto">
              <table className="min-w-[1120px] w-full border-separate border-spacing-0 text-sm">
                <thead className="sticky top-0 z-10 bg-slate-50 text-xs text-slate-500">
                  <tr>
                    <th className="w-12 border-b border-border px-4 py-3 text-left">
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-slate-300"
                        checked={allFilteredSelected}
                        onChange={toggleAllFiltered}
                      />
                    </th>
                    <th className="w-20 border-b border-border px-3 py-3 text-left font-medium">编号</th>
                    <th className="w-28 border-b border-border px-3 py-3 text-left font-medium">分组</th>
                    <th className="border-b border-border px-3 py-3 text-left font-medium">名称</th>
                    <th className="w-56 border-b border-border px-3 py-3 text-left font-medium">IP / 代理</th>
                    <th className="w-32 border-b border-border px-3 py-3 text-left font-medium">最近打开</th>
                    <th className="w-36 border-b border-border px-3 py-3 text-left font-medium">账号平台</th>
                    <th className="w-40 border-b border-border px-3 py-3 text-left font-medium">标签</th>
                    <th className="w-64 border-b border-border px-3 py-3 text-left font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={9} className="px-4 py-16 text-center text-sm text-slate-400">
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
                      <td className="border-b border-border px-3 py-3 align-middle text-slate-600">
                        {index + 1}
                      </td>
                      <td className="border-b border-border px-3 py-3 align-middle text-slate-700">未分组</td>
                      <td className="border-b border-border px-3 py-3 align-middle">
                        <div className="flex min-w-0 items-center gap-2">
                          <StatusIndicator status={profile.status} />
                          <span className="text-blue-600">{platformIcon(profile)}</span>
                          <div className="min-w-0">
                            <button
                              className="block max-w-[240px] truncate text-left font-medium text-slate-900 hover:text-accent"
                              onClick={() => onEdit(profile.id)}
                              title={profile.name}
                            >
                              {profile.name}
                            </button>
                            <div className="text-xs text-slate-400">{engineLabel(profile)}</div>
                          </div>
                        </div>
                      </td>
                      <td className="border-b border-border px-3 py-3 align-middle">
                        <div className="font-medium text-slate-800">{proxyHost(profile)}</div>
                        <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
                          <span className="rounded bg-slate-100 px-1.5 py-0.5">{proxyType(profile)}</span>
                          <span>{locationText(profile)}</span>
                        </div>
                      </td>
                      <td className="border-b border-border px-3 py-3 align-middle text-slate-600">
                        {profile.status === "running" ? "运行中" : formatDate(profile.updated_at)}
                      </td>
                      <td className="border-b border-border px-3 py-3 align-middle text-slate-500">-</td>
                      <td className="border-b border-border px-3 py-3 align-middle">
                        <div className="flex flex-wrap gap-1">
                          {profile.tags.length === 0 ? (
                            <span className="text-slate-400">-</span>
                          ) : profile.tags.map((tag) => (
                            <span
                              key={tag.tag}
                              className="rounded px-1.5 py-0.5 text-xs"
                              style={tag.color ? { backgroundColor: `${tag.color}1f`, color: tag.color } : undefined}
                            >
                              {tag.tag}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="relative border-b border-border px-3 py-3 align-middle">
                        <div className="flex items-center gap-2">
                          {profile.status === "running" ? (
                            <button
                              className="btn-danger flex items-center gap-1.5 px-2.5"
                              disabled={busyId === profile.id}
                              onClick={() => void runRowAction(profile.id, () => onStop(profile.id))}
                            >
                              <Square className="h-3.5 w-3.5" />
                              <span>关闭</span>
                            </button>
                          ) : (
                            <button
                              className="btn-primary flex items-center gap-1.5 px-2.5"
                              disabled={busyId === profile.id}
                              onClick={() => void runRowAction(profile.id, () => onLaunch(profile.id, "manual"))}
                            >
                              <Play className="h-3.5 w-3.5" />
                              <span>打开</span>
                            </button>
                          )}
                          {profile.status !== "running" && profile.browser_engine !== "cloakbrowser" && (
                            <button
                              className="btn-secondary flex items-center gap-1.5 px-2.5"
                              disabled={busyId === profile.id}
                              title="带 CDP 打开，用于排查 console、cookie 和指纹自检"
                              onClick={() => void runRowAction(profile.id, () => onLaunch(profile.id, "debug"))}
                            >
                              <Bug className="h-3.5 w-3.5" />
                              <span>调试</span>
                            </button>
                          )}
                          <button
                            className="btn-secondary px-2.5"
                            title="编辑"
                            onClick={() => onEdit(profile.id)}
                          >
                            <Edit3 className="h-3.5 w-3.5" />
                          </button>
                          <button
                            className="btn-secondary px-2.5"
                            title="更多"
                            onClick={() => setMenuOpenId((current) => current === profile.id ? null : profile.id)}
                          >
                            <MoreVertical className="h-3.5 w-3.5" />
                          </button>
                        </div>

                        {menuOpenId === profile.id && (
                          <div className="absolute right-3 top-12 z-20 w-44 rounded-md border border-blue-200 bg-white p-1 shadow-xl">
                            <button
                              className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm text-accent hover:bg-accent/10"
                              onClick={() => onEdit(profile.id)}
                            >
                              <Edit3 className="h-4 w-4" />
                              <span>编辑</span>
                            </button>
                            <button
                              className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
                              onClick={() => void runRowAction(profile.id, () => onDuplicate(profile))}
                            >
                              <Copy className="h-4 w-4" />
                              <span>复制</span>
                            </button>
                            <button
                              className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50"
                              onClick={() => void handleDelete(profile)}
                            >
                              <Trash2 className="h-4 w-4" />
                              <span>删除</span>
                            </button>
                            <div className="my-1 border-t border-border" />
                            <button
                              className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
                              onClick={() => onEdit(profile.id)}
                            >
                              <Globe2 className="h-4 w-4" />
                              <span>修改代理</span>
                            </button>
                            <button
                              className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
                              onClick={() => onEdit(profile.id)}
                            >
                              <ListChecks className="h-4 w-4" />
                              <span>修改指纹</span>
                            </button>
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
      </main>
    </div>
  );
}
