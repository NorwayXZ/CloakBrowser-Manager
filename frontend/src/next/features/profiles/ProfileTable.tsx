import { Bug, Copy, Flame, MapPin, MoreHorizontal, Pencil, Play, Square, Trash2 } from "lucide-react";
import { useRef, type KeyboardEvent, type MouseEvent } from "react";
import { cn } from "../../shared/lib/cn";
import { matchesCombo } from "../../shared/lib/hotkeys";
import { Badge, Button, Checkbox, IconButton, Menu, MenuItem, MenuSeparator, StatusDot, Table, TD, TH, THead, TR, Tooltip } from "../../ui";
import { engineLabel, groupOf, isRunning, lastState, launchFailureReason, locationText, proxyHost, proxyType } from "./format";
import { NoteField } from "./NoteField";
import type { LaunchMode, Profile } from "./types";

export interface RowActions {
  launch: (profile: Profile, mode: LaunchMode) => void;
  stop: (profile: Profile) => void;
  edit: (profile: Profile) => void;
  duplicate: (profile: Profile) => void;
  trash: (profile: Profile) => void;
  burn: (profile: Profile) => void;
}

const INTERACTIVE = "button, a, input, textarea, select, [role=checkbox], [role=menuitem]";

/**
 * The environment table. A row is one keyboard stop: ↑/↓ move between rows,
 * Enter opens the details, Space selects, ⌘/Ctrl+Enter opens or closes the
 * browser. Clicking a row (outside its controls) opens the details too.
 */
export function ProfileTable({
  profiles,
  selected,
  activeId,
  busy,
  showGroup,
  showNotes,
  onToggle,
  onToggleAll,
  onOpen,
  actions,
}: {
  profiles: Profile[];
  selected: ReadonlySet<string>;
  activeId: string | null;
  busy: ReadonlySet<string>;
  showGroup: boolean;
  showNotes: boolean;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  onOpen: (id: string) => void;
  actions: RowActions;
}) {
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
      onOpen(profile.id);
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

  const onRowClick = (event: MouseEvent<HTMLTableRowElement>, profile: Profile) => {
    if ((event.target as HTMLElement).closest(INTERACTIVE)) return;
    onOpen(profile.id);
  };

  return (
    <Table label="环境列表" className="max-h-full" minWidth={720}>
      <colgroup>
        <col className="w-10" />
        <col className="w-11" />
        <col />
        {showGroup && <col className="w-28" />}
        <col className="w-52" />
        <col className="w-32" />
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
              onClick={(event) => onRowClick(event, profile)}
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
                  {profile.disposable && <Badge tone="warning">一次性</Badge>}
                </div>
                <div className="truncate text-xs text-fg-3">
                  {[engineLabel(profile), profile.account_platform].filter(Boolean).join(" · ")}
                </div>
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
                  <MapPin className="h-3 w-3 shrink-0" aria-hidden />
                  <span className="truncate" title={locationText(profile)}>
                    {locationText(profile)}
                  </span>
                </div>
              </TD>
              <TD>
                {isBusy ? (
                  <StatusDot status="busy" label={running ? "正在关闭" : "正在启动"} />
                ) : state.kind === "failed" ? (
                  <Tooltip content={launchFailureReason(profile)}>
                    <span tabIndex={0} className="inline-flex max-w-full rounded focus-visible:outline-offset-1">
                      <StatusDot status="error" label={state.text} />
                    </span>
                  </Tooltip>
                ) : (
                  <StatusDot status={state.kind === "running" ? "running" : "stopped"} label={state.text} />
                )}
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
                    <Button size="sm" variant="primary" icon={<Play className="h-3 w-3" />} loading={isBusy} onClick={() => actions.launch(profile, "manual")} aria-label={`打开「${profile.name}」`}>
                      打开
                    </Button>
                  )}
                  <Menu trigger={<IconButton size="sm" label={`「${profile.name}」的更多操作`} icon={<MoreHorizontal className="h-4 w-4" />} />}>
                    {!running && (
                      <MenuItem icon={<Bug className="h-4 w-4" />} onSelect={() => actions.launch(profile, "debug")} disabled={isBusy}>
                        调试启动（开启 CDP）
                      </MenuItem>
                    )}
                    <MenuItem icon={<Pencil className="h-4 w-4" />} onSelect={() => actions.edit(profile)}>
                      编辑
                    </MenuItem>
                    <MenuItem icon={<Copy className="h-4 w-4" />} onSelect={() => actions.duplicate(profile)}>
                      复制
                    </MenuItem>
                    <MenuSeparator />
                    <MenuItem icon={<Trash2 className="h-4 w-4" />} onSelect={() => actions.trash(profile)} danger>
                      移到回收站
                    </MenuItem>
                    {profile.disposable && (
                      <MenuItem icon={<Flame className="h-4 w-4" />} onSelect={() => actions.burn(profile)} danger>
                        焚毁（彻底删除）
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
  );
}
