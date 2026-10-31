import { ChevronDown, Copy, Inbox, Pencil, Play, RefreshCw, Search, SearchX, Sparkles, Square, Trash2, UserRoundPlus, X } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { formatShortcut, useHotkeys, useMediaQuery } from "../../shared/lib/hotkeys";
import { Button, EmptyState, ErrorState, IconButton, Input, Kbd, Menu, MenuItem, Select, Skeleton } from "../../ui";
import { NARROW_QUERY } from "../../app/nav";
import { useGroups, useProfiles } from "./api";
import { useProfileActions } from "./actions";
import { ALL_GROUPS, countByGroup, filterProfiles, isRunning, UNGROUPED } from "./format";
import { GroupRail } from "./GroupRail";
import { useLaunch } from "./launch";
import { ProfileDrawer } from "./ProfileDrawer";
import { ProfileTable, type RowActions } from "./ProfileTable";

const WIDE_QUERY = "(min-width: 1440px)";

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

export function ProfilesPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const group = params.get("g") ?? ALL_GROUPS;
  const activeId = params.get("p");
  const creating = params.get("create");

  const profiles = useProfiles();
  const groups = useGroups();
  const { launch, stop, busy } = useLaunch();
  const { duplicate, trash, burn } = useProfileActions();
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const searchRef = useRef<HTMLInputElement>(null);
  const narrow = useMediaQuery(NARROW_QUERY);
  const wide = useMediaQuery(WIDE_QUERY);
  const [tableRef, tableWidth] = useWidth<HTMLDivElement>();

  const all = useMemo(() => profiles.data ?? [], [profiles.data]);
  const visible = useMemo(() => filterProfiles(all, query, group), [all, query, group]);
  const counts = useMemo(() => countByGroup(all), [all]);
  const active = activeId ? all.find((p) => p.id === activeId) ?? null : null;
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

  const open = (id: string | null) => setParam("p", id);

  const actions: RowActions = {
    launch: (profile, mode) => void launch([profile], mode),
    stop: (profile) => void stop([profile]),
    edit: (profile) => navigate(`/profiles/${profile.id}/edit`),
    duplicate: (profile) => void duplicate([profile]),
    trash: (profile) =>
      void trash([profile]).then((done) => {
        if (done && activeId === profile.id) open(null);
      }),
    burn: (profile) =>
      void burn(profile).then((done) => {
        if (done && activeId === profile.id) open(null);
      }),
  };

  useHotkeys([
    { combo: "mod+f", handler: () => searchRef.current?.focus() },
    { combo: "/", handler: () => searchRef.current?.focus() },
    { combo: "mod+n", handler: () => navigate("/profiles/new") },
    {
      combo: "escape",
      handler: () => {
        if (overlayOpen()) return;
        if (activeId) open(null);
        else if (selected.size) setSelected(new Set());
      },
    },
  ]);

  const showNotes = tableWidth === 0 || tableWidth >= 900;
  const showGroup = group === ALL_GROUPS && (tableWidth === 0 || tableWidth >= 1040);
  const filtered = query.trim() !== "" || group !== ALL_GROUPS;

  return (
    <div className="flex h-full min-h-0">
      {!narrow && (
        <GroupRail groups={groups.data ?? []} loading={groups.isPending} counts={counts} total={all.length} value={group} onChange={(value) => setParam("g", value === ALL_GROUPS ? null : value)} />
      )}

      <div className="relative flex min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 flex-col gap-3 px-6 pb-3 pt-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <h1 className="text-lg font-semibold text-fg">环境</h1>
              <p className="text-sm text-fg-2">
                {profiles.isSuccess ? `共 ${all.length} 个 · 运行中 ${runningCount}` : "正在读取…"}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <IconButton label="刷新" variant="secondary" icon={<RefreshCw className="h-4 w-4" />} loading={profiles.isFetching && !profiles.isPending} onClick={() => void profiles.refetch()} />
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
            </div>
          </div>

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
              {narrow && (
                <Select aria-label="按分组筛选" className="w-40" value={group} onChange={(event) => setParam("g", event.target.value === ALL_GROUPS ? null : event.target.value)}>
                  <option value={ALL_GROUPS}>全部分组（{all.length}）</option>
                  <option value={UNGROUPED}>未分组（{counts.get(UNGROUPED) ?? 0}）</option>
                  {(groups.data ?? []).filter((g) => g.name !== UNGROUPED).map((g) => (
                    <option key={g.id} value={g.name}>
                      {g.name}（{counts.get(g.name) ?? 0}）
                    </option>
                  ))}
                </Select>
              )}
            </div>
          )}
        </div>

        <div ref={tableRef} className="min-h-0 flex-1 px-6 pb-6">
          {profiles.isPending ? (
            <ListSkeleton />
          ) : profiles.isError ? (
            <ErrorState title="环境列表没有加载出来" message={profiles.error.message} onRetry={() => void profiles.refetch()} retrying={profiles.isFetching} />
          ) : all.length === 0 ? (
            <div className="rounded-md border border-dashed border-border-strong bg-surface">
              <EmptyState
                icon={Inbox}
                title="还没有环境"
                description="每个环境是一个独立的浏览器身份：设备型号、代理、时区语言和 Cookie 都各自独立。"
                action={
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
                }
              />
            </div>
          ) : visible.length === 0 ? (
            <div className="rounded-md border border-border bg-surface">
              <EmptyState
                icon={SearchX}
                title="没有匹配的环境"
                description={query ? `没有名称、代理、备注或 UA 包含“${query}”的环境${group !== ALL_GROUPS ? `（在“${group}”里）` : ""}。` : `“${group}”里还没有环境。`}
                action={
                  filtered && (
                    <Button
                      onClick={() =>
                        setParams((current) => {
                          const next = new URLSearchParams(current);
                          next.delete("q");
                          next.delete("g");
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
              showNotes={showNotes}
              onToggle={toggle}
              onToggleAll={toggleAll}
              onOpen={(id) => open(id)}
              actions={actions}
            />
          )}
        </div>

        {active && !wide && (
          <ProfileDrawer profile={active} busy={busy.has(active.id)} overlay onClose={() => open(null)} onOpenViewer={() => navigate(`/profiles/${active.id}/viewer`)} actions={actions} />
        )}
      </div>

      {active && wide && (
        <ProfileDrawer profile={active} busy={busy.has(active.id)} overlay={false} onClose={() => open(null)} onOpenViewer={() => navigate(`/profiles/${active.id}/viewer`)} actions={actions} />
      )}

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

