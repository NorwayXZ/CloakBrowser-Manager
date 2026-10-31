import { Bug, Copy, Flame, Ghost, MapPin, MoreHorizontal, Pencil, Play, Square, Trash2 } from "lucide-react";
import { useRef, type KeyboardEvent, type MouseEvent } from "react";
import { cn } from "../../shared/lib/cn";
import { matchesCombo } from "../../shared/lib/hotkeys";
import { Badge, Button, Checkbox, IconButton, Menu, MenuItem, MenuSeparator, StatusDot, Tooltip } from "../../ui";
import { AgentLeaseBadge } from "./AgentLeaseBadge";
import { engineLabel, groupOf, isRunning, leaseOf, lastState, launchFailureReason, locationText, proxyHost, proxyType, UNGROUPED } from "./format";
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

// The avatar's color comes from the name, so an environment keeps its color everywhere.
const AVATARS = ["#ff9500", "#ff2d55", "#34a853", "#5a8bff", "#8e6bff", "#00a6a6", "#e5533d", "#d6479a"];

export function avatarColor(name: string): string {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.codePointAt(0)!) >>> 0;
  return AVATARS[hash % AVATARS.length]!;
}

/**
 * The environments as cards. A card is one keyboard stop: arrow keys move
 * between cards, Enter opens the details, Space selects, ⌘/Ctrl+Enter opens or
 * closes the browser. Clicking a card (outside its controls) opens the details.
 */
export function ProfileCards({
  profiles,
  selected,
  activeId,
  busy,
  onToggle,
  onOpen,
  actions,
}: {
  profiles: Profile[];
  selected: ReadonlySet<string>;
  activeId: string | null;
  busy: ReadonlySet<string>;
  onToggle: (id: string) => void;
  onOpen: (id: string) => void;
  actions: RowActions;
}) {
  const listRef = useRef<HTMLUListElement>(null);

  const focusCard = (index: number) => {
    const cards = listRef.current?.querySelectorAll<HTMLElement>("[data-row]");
    cards?.[Math.max(0, Math.min(index, cards.length - 1))]?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLElement>, profile: Profile, index: number) => {
    if (event.target !== event.currentTarget) return;
    if (matchesCombo(event.nativeEvent, "mod+enter")) {
      event.preventDefault();
      if (isRunning(profile)) actions.stop(profile);
      else actions.launch(profile, "manual");
    } else if (event.key === "Enter") {
      event.preventDefault();
      onOpen(profile.id);
    } else if (event.key === " ") {
      event.preventDefault();
      onToggle(profile.id);
    } else if (event.key === "ArrowDown" || event.key === "ArrowRight") {
      event.preventDefault();
      focusCard(index + 1);
    } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
      event.preventDefault();
      focusCard(index - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusCard(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusCard(Number.MAX_SAFE_INTEGER);
    }
  };

  const onClick = (event: MouseEvent<HTMLElement>, profile: Profile) => {
    if ((event.target as HTMLElement).closest(INTERACTIVE)) return;
    onOpen(profile.id);
  };

  return (
    <ul ref={listRef} aria-label="环境列表" className="grid list-none grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-5 p-0">
      {profiles.map((profile, index) => {
        const running = isRunning(profile);
        const state = lastState(profile);
        const isBusy = busy.has(profile.id);
        const isSelected = selected.has(profile.id);
        const lease = running ? leaseOf(profile) : null;
        const group = groupOf(profile);
        const meta = [engineLabel(profile), profile.account_platform, group === UNGROUPED ? null : group].filter(Boolean).join(" · ");
        return (
          <li key={profile.id}>
            <article
              data-row
              data-selected={isSelected || undefined}
              tabIndex={0}
              aria-label={profile.name}
              onKeyDown={(event) => onKeyDown(event, profile, index)}
              onClick={(event) => onClick(event, profile)}
              className={cn(
                "glass flex h-full cursor-default flex-col gap-4 rounded-lg p-5 transition-[box-shadow,transform,border-color] duration-base",
                "hover:-translate-y-0.5 focus-visible:outline-offset-2",
                isSelected && "!border-accent-fill shadow-[0_0_0_2px_rgb(var(--c-accent-fill)/0.55),var(--shadow-card)]",
                activeId === profile.id && !isSelected && "!border-accent/60",
              )}
            >
              <div className="flex items-center gap-3.5">
                <span
                  aria-hidden
                  className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[15px] text-lg font-bold text-accent-on shadow-raised"
                  style={{ background: avatarColor(profile.account_platform || profile.name) }}
                >
                  {profile.disposable ? <Ghost className="h-6 w-6" /> : [...profile.name][0]?.toUpperCase()}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center gap-1.5">
                    <div className="truncate text-md font-semibold tracking-tight text-fg" title={profile.name}>
                      {profile.name}
                    </div>
                    {profile.disposable && <Badge tone="warning">一次性</Badge>}
                  </div>
                  <div className="truncate text-sm text-fg-2" title={meta}>
                    {meta}
                  </div>
                </div>
                <Checkbox aria-label={`选择「${profile.name}」`} checked={isSelected} onCheckedChange={() => onToggle(profile.id)} />
              </div>

              {lease && <AgentLeaseBadge profile={profile} lease={lease} />}

              <div className="flex flex-col gap-1.5 text-sm">
                <div className="flex items-center justify-between gap-3">
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
                  <span className="min-w-0 truncate font-mono text-xs text-fg-2" title={proxyHost(profile)}>
                    {proxyHost(profile)}
                  </span>
                </div>
                <div className="flex min-w-0 items-center gap-1.5 text-xs text-fg-3">
                  <Badge className="h-5 px-2">{proxyType(profile)}</Badge>
                  {profile.proxy_connection_mode === "relay" && <Badge className="h-5 max-w-32 truncate px-2">中转 · {profile.relay_name ?? "已选择"}</Badge>}
                  <MapPin className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  <span className="truncate" title={locationText(profile)}>
                    {locationText(profile)}
                  </span>
                </div>
              </div>

              <div className="mt-auto flex items-center gap-2">
                {running ? (
                  <Button className="flex-1" icon={<Square className="h-3.5 w-3.5" />} loading={isBusy} onClick={() => actions.stop(profile)} aria-label={`关闭「${profile.name}」`}>
                    关闭
                  </Button>
                ) : (
                  <Button className="flex-1" variant="primary" icon={<Play className="h-3.5 w-3.5" />} loading={isBusy} onClick={() => actions.launch(profile, "manual")} aria-label={`打开「${profile.name}」`}>
                    打开
                  </Button>
                )}
                <Menu trigger={<IconButton variant="secondary" label={`「${profile.name}」的更多操作`} icon={<MoreHorizontal className="h-4 w-4" />} />}>
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
            </article>
          </li>
        );
      })}
    </ul>
  );
}
