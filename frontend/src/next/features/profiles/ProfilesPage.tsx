import { useQueryClient } from "@tanstack/react-query";
import { pinnedFirst, usePinnedProfiles } from "./pins";
import { CheckCircle2, ChevronDown, Copy, Inbox, Laptop, Pencil, Play, RefreshCw, Search, SearchX, Smartphone, Sparkles, Sprout, Square, Trash2, UserRoundPlus, X } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { request } from "../../shared/api/client";
import { cn } from "../../shared/lib/cn";
import { formatShortcut, useHotkeys } from "../../shared/lib/hotkeys";
import { Button, EmptyState, ErrorState, IconButton, Input, Kbd, Menu, MenuItem, Skeleton, useToast } from "../../ui";
import { useGroups, useProfiles } from "./api";
import { useProfileActions } from "./actions";
import { ALL_GROUPS, countByGroup, filterProfiles, isNurseryGroupName, isNurseryProfile, isRunning } from "./format";
import { GroupBar } from "./GroupBar";
import { useLaunch } from "./launch";
import { computeNurseryBadge, useNurseryWarmupMap, type NurseryBadgeInfo } from "./nurseryStatus";
import { ProfileTable, type RowActions } from "./ProfileTable";
import type { Profile } from "./types";

// Only needed after a click: kept out of the first load.
const SentenceDialog = lazy(() => import("./CreateDialogs").then((m) => ({ default: m.SentenceDialog })));
const DisposableDialog = lazy(() => import("./CreateDialogs").then((m) => ({ default: m.DisposableDialog })));

/** Width of an element, following resizes. 0 until measured (and in jsdom). */
function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const observer = new ResizeObserver((entries) => setWidth(entries[0]?.contentRect.width ?? el.clientWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function overlayOpen() {
  return Boolean(document.querySelector('[role="dialog"], [role="menu"], [role="alertdialog"]'));
}

type NurseryKind = "all" | "desktop" | "ios";

export function NurseryPage() {
  return <ProfilesPage scope="nursery" />;
}

export function ProfilesPage({ scope = "regular" }: { scope?: "regular" | "nursery" }) {
  const isNursery = scope === "nursery";
  const basePath = isNursery ? "/nursery" : "/profiles";
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const group = params.get("g") ?? ALL_GROUPS;
  const kind = (params.get("k") as NurseryKind | null) ?? "all";
  const activeId = params.get("p");
  const creating = params.get("create");

  const profiles = useProfiles();
  const groups = useGroups();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { launch, stop, busy } = useLaunch();
  const { duplicate, trash, burn } = useProfileActions();
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [warmingBusyId, setWarmingBusyId] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [tableRef, tableWidth] = useWidth<HTMLDivElement>();

  const all = useMemo(
    () => (profiles.data ?? []).filter((p) => (isNursery ? isNurseryProfile(p) : !isNurseryProfile(p))),
    [isNursery, profiles.data],
  );
  const nurseryWarmupMap = useNurseryWarmupMap(all, isNursery);
  const nurseryBadges = useMemo(() => {
    if (!isNursery) return undefined;
    const map = new Map<string, NurseryBadgeInfo>();
    for (const p of all) map.set(p.id, computeNurseryBadge(p, nurseryWarmupMap.get(p.id)));
    return map;
  }, [all, isNursery, nurseryWarmupMap]);
  const readyCount = useMemo(
    () => (nurseryBadges ? [...nurseryBadges.values()].filter((b) => b.ready).length : 0),
    [nurseryBadges],
  );
  const warmOnce = useCallback(
    async (profile: Profile) => {
      setWarmingBusyId(profile.id);
      try {
        await request(`/api/profiles/${encodeURIComponent(profile.id)}/warmup/run`, { method: "POST", body: {} });
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["nursery", "warmup", profile.id] }),
          queryClient.invalidateQueries({ queryKey: ["manager", "status"] }),
        ]);
        toast.show({ tone: "success", title: `已开始暖床「${profile.name}」`, description: "后台无窗口静默浏览约 4～6 分钟后会自动停下。" });
      } catch (err) {
        toast.show({ tone: "error", title: "没能启动暖床", description: err instanceof Error ? err.message : String(err) });
      } finally {
        setWarmingBusyId(null);
      }
    },
    [queryClient, toast],
  );
  const regularGroups = useMemo(
    () => (groups.data ?? []).filter((g) => !isNurseryGroupName(g.name)),
    [groups.data],
  );
  const desktopCount = useMemo(() => all.filter((p) => p.platform !== "ios").length, [all]);
  const iosCount = useMemo(() => all.filter((p) => p.platform === "ios").length, [all]);
  const { pinned, toggle: togglePin } = usePinnedProfiles();
  const visible = useMemo(() => {
    const byGroupAndQuery = filterProfiles(all, query, group);
    const byKind = !isNursery || kind === "all"
      ? byGroupAndQuery
      : byGroupAndQuery.filter((p) => (kind === "ios" ? p.platform === "ios" : p.platform !== "ios"));
    return pinnedFirst(byKind, pinned);
  }, [all, group, isNursery, kind, pinned, query]);
  const counts = useMemo(() => countByGroup(all), [all]);
  const chosen = useMemo(() => all.filter((p) => selected.has(p.id)), [all, selected]);
  const runningCount = all.filter(isRunning).length;

  const setParam = useCallback(
    (key: string, value: string | null) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          if (value === null || value === "") next.delete(key);
          else next.set(key, value);
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  // Drop selections of profiles that no longer exist (deleted, burned).
  useEffect(() => {
    if (!profiles.data) return;
    const ids = new Set(profiles.data.map((p) => p.id));
    setSelected((current) => {
      const next = new Set([...current].filter((id) => ids.has(id)));
      return next.size === current.size ? current : next;
    });
  }, [profiles.data]);

  const toggle = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleAll = () =>
    setSelected((current) => {
      const everyVisible = visible.length > 0 && visible.every((p) => current.has(p.id));
      const next = new Set(current);
      visible.forEach((p) => (everyVisible ? next.delete(p.id) : next.add(p.id)));
      return next;
    });

  const actions: RowActions = {
    launch: (profile, mode) => void launch([profile], mode),
    stop: (profile) => void stop([profile]),
    edit: (profile) => navigate(`${basePath}/${profile.id}/edit`),
    openViewer: (profile) => navigate(`${basePath}/${profile.id}/viewer`),
    duplicate: (profile) => void duplicate([profile]),
    trash: (profile) => void trash([profile]),
    burn: (profile) => void burn(profile),
  };

  useHotkeys([
    { combo: "mod+f", handler: () => searchRef.current?.focus() },
    { combo: "/", handler: () => searchRef.current?.focus() },
    { combo: "mod+n", handler: () => navigate(`${basePath}/new`) },
    {
      combo: "escape",
      handler: () => {
        if (overlayOpen()) return;
        if (activeId) setParam("p", null);
        else if (selected.size) setSelected(new Set());
      },
    },
  ]);

  // Columns join as the window widens; 0 is jsdom, which shows everything.
  const showDevice = tableWidth === 0 || tableWidth >= 960;
  const showNotes = tableWidth === 0 || tableWidth >= 1160;
  const showGroup = !isNursery && group === ALL_GROUPS && (tableWidth === 0 || tableWidth >= 1280);
  const filtered = query.trim() !== "" || group !== ALL_GROUPS || (isNursery && kind !== "all");

  return (
    <div className="flex h-full min-h-0 flex-col pt-5">
        <div className="flex shrink-0 flex-col gap-3 pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <h1 className="text-xl font-semibold tracking-tight text-fg">{isNursery ? "产房" : "环境"}</h1>
              <p className="text-sm text-fg-2">
                {profiles.isSuccess
                  ? isNursery
                    ? `共 ${all.length} 个专用注册环境 · 已达标可注册 ${readyCount} 个 · 运行中 ${runningCount}`
                    : `共 ${all.length} 个 · 运行中 ${runningCount}`
                  : "正在读取…"}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <IconButton label="刷新" variant="secondary" icon={<RefreshCw className="h-4 w-4" />} loading={profiles.isFetching && !profiles.isPending} onClick={() => void profiles.refetch()} />
              {isNursery ? (
                <Button variant="primary" icon={<UserRoundPlus className="h-4 w-4" />} onClick={() => navigate("/nursery/new")}>
                  新建产房环境
                </Button>
              ) : (
                <Menu
                  trigger={
                    <Button variant="primary" icon={<UserRoundPlus className="h-4 w-4" />}>
                      新建
                      <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                    </Button>
                  }
                >
                  <MenuItem icon={<Pencil className="h-4 w-4" />} shortcut={formatShortcut("mod+n")} onSelect={() => navigate("/profiles/new")}>
                    自定义创建
                  </MenuItem>
                  <MenuItem icon={<Sparkles className="h-4 w-4" />} onSelect={() => setParam("create", "sentence")}>
                    一句话建号
                  </MenuItem>
                  <MenuItem icon={<UserRoundPlus className="h-4 w-4" />} onSelect={() => setParam("create", "disposable")}>
                    一次性身份
                  </MenuItem>
                </Menu>
              )}
            </div>
          </div>

          {isNursery ? (
            <>
              <NurseryFilterBar
                total={all.length}
                desktopCount={desktopCount}
                iosCount={iosCount}
                value={kind}
                onChange={(next) => setParam("k", next === "all" ? null : next)}
              />
              <div role="note" aria-label="产房养号计划表" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border bg-surface px-3 py-2 text-xs text-fg-2">
                <span className="font-semibold text-fg">养号与循环计划表：</span>
                <span>① 第 1 天点「暖一轮」跑 1 次</span>
                <span aria-hidden className="text-fg-3">→</span>
                <span>② 第 2～3 天再跑满共 3 轮（跨 2 天）</span>
                <span aria-hidden className="text-fg-3">→</span>
                <span className="inline-flex items-center gap-1 font-medium text-success">
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  亮绿标「可注册 Gmail」后点打开去联动入口建号
                </span>
                <span aria-hidden className="text-fg-3">→</span>
                <span>④ 建好号转走后点「新一轮」清空换新机，从 0/3 重新开始</span>
              </div>
            </>
          ) : (
            <GroupBar groups={regularGroups} loading={groups.isPending} counts={counts} total={all.length} value={group} onChange={(value) => setParam("g", value === ALL_GROUPS ? null : value)} />
          )}

          {selected.size > 0 ? (
            <div role="toolbar" aria-label="批量操作" className="flex min-h-10 flex-wrap items-center gap-2 rounded-md border border-accent/40 bg-accent-soft px-3 py-1">
              <span className="text-sm font-medium text-fg">已选 {selected.size} 个</span>
              <span className="mx-1 h-4 w-px bg-border-strong" aria-hidden />
              <Button size="sm" variant="primary" icon={<Play className="h-3 w-3" />} disabled={!chosen.some((p) => !isRunning(p))} onClick={() => void launch(chosen, "manual")}>
                打开 {chosen.filter((p) => !isRunning(p)).length || ""}
              </Button>
              <Button size="sm" icon={<Square className="h-3 w-3" />} disabled={!chosen.some(isRunning)} onClick={() => void stop(chosen)}>
                关闭 {chosen.filter(isRunning).length || ""}
              </Button>
              <Button size="sm" icon={<Copy className="h-3 w-3" />} onClick={() => void duplicate(chosen)}>
                复制
              </Button>
              <Button
                size="sm"
                variant="danger-ghost"
                icon={<Trash2 className="h-3 w-3" />}
                onClick={() =>
                  void trash(chosen).then((done) => {
                    if (done) setSelected(new Set());
                  })
                }
              >
                移到回收站
              </Button>
              <Button size="sm" variant="ghost" className="ml-auto" icon={<X className="h-3 w-3" />} onClick={() => setSelected(new Set())}>
                取消选择 <Kbd>Esc</Kbd>
              </Button>
            </div>
          ) : (
            <div className="flex min-h-10 flex-wrap items-center gap-2">
              <div role="search" className="relative min-w-48 max-w-md flex-1">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-3" aria-hidden />
                <Input
                  ref={searchRef}
                  aria-label="搜索环境"
                  placeholder="搜索名称、代理、备注、UA"
                  className="pl-8 pr-10"
                  value={query}
                  onChange={(event) => setParam("q", event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Escape" && query) {
                      event.preventDefault();
                      setParam("q", null);
                    } else if (event.key === "ArrowDown") {
                      event.preventDefault();
                      document.querySelector<HTMLElement>("tr[data-row]")?.focus();
                    }
                  }}
                />
                <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2">
                  <Kbd>/</Kbd>
                </span>
              </div>
            </div>
          )}
        </div>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div ref={tableRef} className="min-h-0 flex-1 pb-6">
          {profiles.isPending ? (
            <ListSkeleton />
          ) : profiles.isError ? (
            <ErrorState title="环境列表没有加载出来" message={profiles.error.message} onRetry={() => void profiles.refetch()} retrying={profiles.isFetching} />
          ) : all.length === 0 ? (
            <div className="rounded-md border border-dashed border-border-strong bg-surface">
              <EmptyState
                icon={isNursery ? Sprout : Inbox}
                title={isNursery ? "产房里还没有专用注册环境" : "还没有环境"}
                description={
                  isNursery
                    ? "专门用来注册新账号的独立环境池，不会混进「环境」主列表。注册好账号后把分组改成“未分组”即可转入正式环境。"
                    : "每个环境是一个独立的浏览器身份：设备型号、代理、时区语言和 Cookie 都各自独立。"
                }
                action={
                  isNursery ? (
                    <Button variant="primary" icon={<Pencil className="h-4 w-4" />} onClick={() => navigate("/nursery/new")}>
                      新建产房环境
                    </Button>
                  ) : (
                    <>
                      <Button variant="primary" icon={<Pencil className="h-4 w-4" />} onClick={() => navigate("/profiles/new")}>
                        自定义创建
                      </Button>
                      <Button icon={<Sparkles className="h-4 w-4" />} onClick={() => setParam("create", "sentence")}>
                        一句话建号
                      </Button>
                      <Button icon={<UserRoundPlus className="h-4 w-4" />} onClick={() => setParam("create", "disposable")}>
                        一次性身份
                      </Button>
                    </>
                  )
                }
              />
            </div>
          ) : visible.length === 0 ? (
            <div className="rounded-md border border-border bg-surface">
              <EmptyState
                icon={SearchX}
                title="没有匹配的环境"
                description={query ? `没有名称、代理、备注或 UA 包含“${query}”的环境${!isNursery && group !== ALL_GROUPS ? `（在“${group}”里）` : ""}。` : isNursery ? "当前类型下还没有产房环境。" : `“${group}”里还没有环境。`}
                action={
                  filtered && (
                    <Button
                      onClick={() =>
                        setParams((current) => {
                          const next = new URLSearchParams(current);
                          next.delete("q");
                          next.delete("g");
                          next.delete("k");
                          return next;
                        }, { replace: true })
                      }
                    >
                      清除筛选
                    </Button>
                  )
                }
              />
            </div>
          ) : (
            <ProfileTable
              profiles={visible}
              selected={selected}
              activeId={activeId}
              busy={busy}
              showGroup={showGroup}
              showDevice={showDevice}
              showNotes={showNotes}
              onToggle={toggle}
              onToggleAll={toggleAll}
              actions={actions}
              pinned={pinned}
              onTogglePin={togglePin}
              nurseryBadges={nurseryBadges}
              onWarmOnce={isNursery ? (p) => void warmOnce(p) : undefined}
              warmingBusyId={warmingBusyId}
            />
          )}
        </div>
      </div>

      <Suspense fallback={null}>
      {creating === "sentence" && (
        <SentenceDialog
          onClose={() => setParam("create", null)}
          onCreated={(id) =>
            setParams((current) => {
              const next = new URLSearchParams(current);
              next.delete("create");
              next.set("p", id);
              return next;
            }, { replace: true })
          }
        />
      )}
      {creating === "disposable" && (
        <DisposableDialog
          onClose={() => setParam("create", null)}
          onCreated={(id) =>
            setParams((current) => {
              const next = new URLSearchParams(current);
              next.delete("create");
              next.set("p", id);
              return next;
            }, { replace: true })
          }
        />
      )}
      </Suspense>
    </div>
  );
}

function NurseryFilterBar({
  total,
  desktopCount,
  iosCount,
  value,
  onChange,
}: {
  total: number;
  desktopCount: number;
  iosCount: number;
  value: NurseryKind;
  onChange: (next: NurseryKind) => void;
}) {
  const options: { key: NurseryKind; label: string; count: number; icon?: typeof Laptop }[] = [
    { key: "all", label: "全部", count: total },
    { key: "desktop", label: "电脑版", count: desktopCount, icon: Laptop },
    { key: "ios", label: "手机版", count: iosCount, icon: Smartphone },
  ];
  return (
    <nav aria-label="产房分类" className="flex flex-wrap items-center gap-1.5">
      <ul className="flex flex-wrap items-center gap-1.5">
        {options.map((opt) => {
          const Icon = opt.icon;
          const active = value === opt.key;
          return (
            <li key={opt.key}>
              <button
                type="button"
                aria-current={active ? "true" : undefined}
                onClick={() => onChange(opt.key)}
                className={cn(
                  "flex h-7 items-center gap-1.5 rounded border px-2.5 text-sm transition-colors duration-fast",
                  active ? "border-accent/40 bg-accent-soft font-medium text-accent" : "border-border bg-surface text-fg-2 hover:bg-surface-2 hover:text-fg",
                )}
              >
                {Icon && <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />}
                <span>{opt.label}</span>
                <span className="tabular text-xs opacity-70">{opt.count}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function ListSkeleton() {
  return (
    <div className="flex flex-col gap-px overflow-hidden rounded-md border border-border bg-surface" aria-busy="true" aria-label="正在读取环境列表">
      <Skeleton className="h-9 rounded-none" />
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="flex items-center gap-4 border-t border-border px-3 py-3">
          <Skeleton className="h-4 w-4" />
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-4 w-32" />
          <Skeleton className="ml-auto h-7 w-16" />
        </div>
      ))}
    </div>
  );
}

