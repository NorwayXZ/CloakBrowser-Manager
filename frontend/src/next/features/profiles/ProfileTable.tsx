import { Activity, Bug, Copy, Eraser, Flame, Link2, MapPin, MonitorPlay, MoreHorizontal, Pencil, Pin, Play, RefreshCw, Square, Trash2 } from "lucide-react";
import { lazy, Suspense, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { cn } from "../../shared/lib/cn";
import { matchesCombo } from "../../shared/lib/hotkeys";
import { Badge, Button, Checkbox, Dialog, IconButton, Menu, MenuItem, MenuSeparator, StatusDot, Table, TD, TH, THead, TR, useToast } from "../../ui";
import { ProxyIpActions } from "../proxies/ProxyIpActions";
import { AgentLeaseBadge } from "./AgentLeaseBadge";
import {
  deviceText,
  engineLabel,
  formatDateTime,
  groupOf,
  isRunning,
  leaseOf,
  lastState,
  launchFailureReason,
  locationText,
  locationTitle,
  platformLabel,
  proxyHost,
  proxyType,
  screenText,
  timezoneText,
} from "./format";
import { NoteField } from "./NoteField";
import type { LaunchMode, Profile } from "./types";

export interface RowActions {
  launch: (profile: Profile, mode: LaunchMode) => void;
  stop: (profile: Profile) => void;
  edit: (profile: Profile) => void;
  openViewer: (profile: Profile) => void;
  duplicate: (profile: Profile) => void;
  trash: (profile: Profile) => void;
  burn: (profile: Profile) => void;
}

const INTERACTIVE = "button, a, input, textarea, select, [role=checkbox], [role=menuitem]";

const FingerprintReportDialog = lazy(() => import("./FingerprintReportDialog").then((m) => ({ default: m.FingerprintReportDialog })));
const ResetProfileDialog = lazy(() => import("./ResetProfileDialog").then((m) => ({ default: m.ResetProfileDialog })));

/**
 * The environment table: each row says everything needed at a glance, and
 * the editor holds the rest. A row is one keyboard stop: ↑/↓ move between
 * rows, Enter (or a double click outside the controls) opens the editor,
 * Space selects, ⌘/Ctrl+Enter opens or closes the browser.
 */
export function ProfileTable({
  profiles,
  selected,
  activeId,
  busy,
  showGroup,
  showDevice,
  showNotes,
  onToggle,
  onToggleAll,
  actions,
  pinned,
  onTogglePin,
}: {
  profiles: Profile[];
  selected: ReadonlySet<string>;
  activeId: string | null;
  busy: ReadonlySet<string>;
  showGroup: boolean;
  showDevice: boolean;
  showNotes: boolean;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  actions: RowActions;
  pinned?: ReadonlySet<string>;
  onTogglePin?: (id: string) => void;
}) {
  const toast = useToast();
  const [selfCheck, setSelfCheck] = useState<Profile | null>(null);
  const [rotating, setRotating] = useState<Profile | null>(null);
  const [resetting, setResetting] = useState<Profile | null>(null);
  const bodyRef = useRef<HTMLTableSectionElement>(null);
  const allSelected = profiles.length > 0 && profiles.every((p) => selected.has(p.id));
  const someSelected = !allSelected && profiles.some((p) => selected.has(p.id));

  const focusRow = (index: number) => {
    const rows = bodyRef.current?.querySelectorAll<HTMLTableRowElement>("tr[data-row]");
    rows?.[Math.max(0, Math.min(index, rows.length - 1))]?.focus();
  };

  const onRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, profile: Profile, index: number) => {
    if (event.target !== event.currentTarget) return;
    const native = event.nativeEvent;
    if (matchesCombo(native, "mod+enter")) {
      event.preventDefault();
      if (isRunning(profile)) actions.stop(profile);
      else actions.launch(profile, "manual");
    } else if (event.key === "Enter") {
      event.preventDefault();
      actions.edit(profile);
    } else if (event.key === " ") {
      event.preventDefault();
      onToggle(profile.id);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      focusRow(index + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusRow(index - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusRow(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusRow(Number.MAX_SAFE_INTEGER);
    }
  };

  const onRowDoubleClick = (event: MouseEvent<HTMLTableRowElement>, profile: Profile) => {
    if ((event.target as HTMLElement).closest(INTERACTIVE)) return;
    actions.edit(profile);
  };

  const copyCdp = (profile: Profile) => {
    const value = `${window.location.origin}${profile.cdp_url}`;
    navigator.clipboard.writeText(value).then(
      () => toast.show({ tone: "success", title: "已复制 CDP 地址", description: value }),
      () => toast.show({ tone: "error", title: "没能复制", description: value }),
    );
  };

  return (
    <>
    <Table flat label="环境列表" className="max-h-full" minWidth={720}>
      <colgroup>
        <col className="w-10" />
        <col className="w-11" />
        <col />
        {showGroup && <col className="w-28" />}
        <col className="w-56" />
        {showDevice && <col className="w-60" />}
        <col className="w-36" />
        {showNotes && <col className="w-48" />}
        <col className="w-32" />
      </colgroup>
      <THead>
        <tr>
          <TH className="pl-3 pr-0">
            <Checkbox
              aria-label={allSelected ? "取消全选" : "全选当前列表"}
              checked={allSelected ? true : someSelected ? "indeterminate" : false}
              onCheckedChange={onToggleAll}
            />
          </TH>
          <TH className="px-1 text-right">#</TH>
          <TH>名称</TH>
          {showGroup && <TH>分组</TH>}
          <TH>出口</TH>
          {showDevice && <TH>设备</TH>}
          <TH>状态</TH>
          {showNotes && <TH>备注</TH>}
          <TH className="text-right">操作</TH>
        </tr>
      </THead>
      <tbody ref={bodyRef}>
        {profiles.map((profile, index) => {
          const running = isRunning(profile);
          const state = lastState(profile);
          const isBusy = busy.has(profile.id);
          const isSelected = selected.has(profile.id);
          const lease = running ? leaseOf(profile) : null;
          return (
            <TR
              key={profile.id}
              data-row
              tabIndex={0}
              aria-label={profile.name}
              selected={isSelected}
              className={cn(
                "cursor-default focus-visible:outline-offset-[-2px]",
                activeId === profile.id && !isSelected && "bg-surface-2",
              )}
              onKeyDown={(event) => onRowKeyDown(event, profile, index)}
              onDoubleClick={(event) => onRowDoubleClick(event, profile)}
            >
              <TD className="pl-3 pr-0">
                <Checkbox aria-label={`选择「${profile.name}」`} checked={isSelected} onCheckedChange={() => onToggle(profile.id)} />
              </TD>
              <TD className="tabular px-1 text-right text-xs text-fg-3">{index + 1}</TD>
              <TD className="py-2">
                <div className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate font-medium" title={profile.name}>
                    {profile.name}
                  </span>
                  {pinned?.has(profile.id) && <Pin aria-label="已置顶" className="h-3 w-3 shrink-0 text-accent" />}
                  {profile.disposable && <Badge tone="warning">一次性</Badge>}
                </div>
                <div className="truncate text-xs text-fg-3">
                  {[engineLabel(profile), profile.account_platform].filter(Boolean).join(" · ")}
                </div>
                {profile.tags && profile.tags.length > 0 && (
                  <div className="mt-0.5 flex min-w-0 gap-1 overflow-hidden">
                    {profile.tags.map((tag) => (
                      <Badge key={tag.tag} className="h-4 shrink-0 px-1 text-[11px]">
                        {tag.tag}
                      </Badge>
                    ))}
                  </div>
                )}
                {lease && <AgentLeaseBadge profile={profile} lease={lease} />}
              </TD>
              {showGroup && (
                <TD className="truncate text-fg-2" title={groupOf(profile)}>
                  {groupOf(profile)}
                </TD>
              )}
              <TD className="py-2">
                <div className="truncate font-mono text-xs text-fg" title={proxyHost(profile)}>
                  {proxyHost(profile)}
                </div>
                <div className="flex min-w-0 items-center gap-1.5 text-xs text-fg-3">
                  <Badge className="h-4 px-1 text-[11px]">{proxyType(profile)}</Badge>
                  {profile.proxy_connection_mode === "relay" && <Badge className="h-4 max-w-32 truncate px-1 text-[11px]">中转 · {profile.relay_name ?? "已选择"}</Badge>}
                  <MapPin className="h-3 w-3 shrink-0" aria-hidden />
                  <span className="truncate" title={locationTitle(profile)}>
                    {locationText(profile)}
                  </span>
                </div>
              </TD>
              {showDevice && (
                <TD className="py-2">
                  <div className="truncate text-xs text-fg" title={deviceText(profile)}>
                    {deviceText(profile)}
                  </div>
                  <div className="truncate text-xs text-fg-3" title={`时区 / 语言：${timezoneText(profile)}`}>
                    {[platformLabel(profile), screenText(profile), timezoneText(profile) === "跟随出口 IP" ? "时区跟随 IP" : timezoneText(profile)].join(" · ")}
                  </div>
                </TD>
              )}
              <TD className="py-2">
                {isBusy ? (
                  <StatusDot status="busy" label={running ? "正在关闭" : "正在启动"} />
                ) : state.kind === "failed" ? (
                  <StatusDot status="error" label={state.text} />
                ) : (
                  <StatusDot status={state.kind === "running" ? "running" : "stopped"} label={state.text} />
                )}
                <div className={cn("truncate text-xs", state.kind === "failed" && !isBusy ? "text-danger" : "text-fg-3")} title={state.kind === "failed" ? launchFailureReason(profile) : undefined}>
                  {state.kind === "failed" && !isBusy
                    ? launchFailureReason(profile)
                    : running
                      ? profile.launch_mode === "debug" ? "调试模式（CDP）" : "日常模式"
                      : `创建 ${formatDateTime(profile.created_at)}`}
                </div>
              </TD>
              {showNotes && (
                <TD className="py-1.5">
                  <NoteField profile={profile} />
                </TD>
              )}
              <TD className="text-right">
                <div className="flex items-center justify-end gap-1">
                  {running ? (
                    <Button size="sm" icon={<Square className="h-3 w-3" />} loading={isBusy} onClick={() => actions.stop(profile)} aria-label={`关闭「${profile.name}」`}>
                      关闭
                    </Button>
                  ) : (
                    <Button size="sm" icon={<Play className="h-3 w-3" />} loading={isBusy} onClick={() => actions.launch(profile, "manual")} aria-label={`打开「${profile.name}」`}>
                      打开
                    </Button>
                  )}
                  <Menu trigger={<IconButton size="sm" label={`「${profile.name}」的更多操作`} icon={<MoreHorizontal className="h-4 w-4" />} />}>
                    {running && profile.viewer_mode === "vnc" && (
                      <MenuItem icon={<MonitorPlay className="h-4 w-4" />} onSelect={() => actions.openViewer(profile)}>
                        打开远程画面
                      </MenuItem>
                    )}
                    {running && (
                      <MenuItem icon={<Activity className="h-4 w-4" />} onSelect={() => setSelfCheck(profile)}>
                        指纹自检
                      </MenuItem>
                    )}
                    {running && profile.launch_mode === "debug" && profile.cdp_url && (
                      <MenuItem icon={<Link2 className="h-4 w-4" />} onSelect={() => copyCdp(profile)}>
                        复制 CDP 地址
                      </MenuItem>
                    )}
                    {!running && (
                      <MenuItem icon={<Bug className="h-4 w-4" />} onSelect={() => actions.launch(profile, "debug")} disabled={isBusy}>
                        调试启动（开启 CDP）
                      </MenuItem>
                    )}
                    <MenuItem icon={<Pencil className="h-4 w-4" />} onSelect={() => actions.edit(profile)}>
                      编辑
                    </MenuItem>
                    {profile.proxy?.toLowerCase().startsWith("socks5://") && (
                      <MenuItem icon={<RefreshCw className="h-4 w-4" />} onSelect={() => setRotating(profile)}>
                        一键切换 IP
                      </MenuItem>
                    )}
                    {onTogglePin && (
                      <MenuItem icon={<Pin className="h-4 w-4" />} onSelect={() => onTogglePin(profile.id)}>
                        {pinned?.has(profile.id) ? "取消置顶" : "置顶"}
                      </MenuItem>
                    )}
                    <MenuItem icon={<Copy className="h-4 w-4" />} onSelect={() => actions.duplicate(profile)}>
                      复制
                    </MenuItem>
                    <MenuSeparator />
                    <MenuItem icon={<Eraser className="h-4 w-4" />} onSelect={() => setResetting(profile)} disabled={isBusy} danger>
                      一键重置环境
                    </MenuItem>
                    <MenuItem icon={<Trash2 className="h-4 w-4" />} onSelect={() => actions.trash(profile)} danger>
                      移到回收站
                    </MenuItem>
                    {profile.disposable && (
                      <MenuItem icon={<Flame className="h-4 w-4" />} onSelect={() => actions.burn(profile)} danger>
                        永久删除
                      </MenuItem>
                    )}
                  </Menu>
                </div>
              </TD>
            </TR>
          );
        })}
      </tbody>
    </Table>
    {selfCheck && (
      <Suspense fallback={null}>
        <FingerprintReportDialog profileId={selfCheck.id} profileName={selfCheck.name} onClose={() => setSelfCheck(null)} />
      </Suspense>
    )}
    {resetting && (
      <Suspense fallback={null}>
        <ResetProfileDialog profile={resetting} onClose={() => setResetting(null)} />
      </Suspense>
    )}
    {rotating && (
      <Dialog
        open
        onOpenChange={(open) => !open && setRotating(null)}
        title={`切换 IP · ${rotating.name}`}
        description={`当前出口 ${proxyHost(rotating)}`}
        footer={<Button onClick={() => setRotating(null)}>关闭</Button>}
      >
        <ProxyIpActions profileId={rotating.id} />
      </Dialog>
    )}
    </>
  );
}
