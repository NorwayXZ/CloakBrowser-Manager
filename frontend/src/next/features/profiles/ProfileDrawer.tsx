import { Activity, Bug, Copy, Flame, MonitorPlay, Pencil, Play, Square, Trash2, X } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { cn } from "../../shared/lib/cn";
import { Badge, Banner, Button, CopyField, IconButton, KeyValueList, StatusDot } from "../../ui";
import {
  engineLabel,
  formatDateTime,
  groupOf,
  hasLaunchFailure,
  isRunning,
  launchFailureReason,
  locationText,
  proxyHost,
  proxyType,
  seedDeviceLabel,
} from "./format";
import { ProxyIpActions } from "../proxies/ProxyIpActions";
import { NoteField } from "./NoteField";
import type { RowActions } from "./ProfileTable";
import type { Profile } from "./types";

const FingerprintReportDialog = lazy(() => import("./FingerprintReportDialog").then((m) => ({ default: m.FingerprintReportDialog })));

/**
 * Everything about one environment without leaving the list: what it is,
 * whether it runs and how (CDP address, self-check), its notes, and actions.
 * Docked beside the list on wide windows, floating over it otherwise.
 */
export function ProfileDrawer({
  profile,
  busy,
  overlay,
  onClose,
  onOpenViewer,
  actions,
}: {
  profile: Profile;
  busy: boolean;
  overlay: boolean;
  onClose: () => void;
  onOpenViewer: () => void;
  actions: RowActions;
}) {
  const running = isRunning(profile);
  const [selfCheck, setSelfCheck] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const cdpEndpoint = profile.cdp_url ? `${window.location.origin}${profile.cdp_url}` : null;
  const manual = profile.launch_mode === "manual" || !profile.cdp_url;

  // Move focus into the panel when it opens or shows another environment.
  useEffect(() => {
    headingRef.current?.focus();
  }, [profile.id]);

  return (
    <aside
      aria-labelledby="profile-drawer-title"
      onKeyDown={(event) => {
        if (event.key === "Escape" && !event.defaultPrevented) {
          event.stopPropagation();
          onClose();
        }
      }}
      className={cn(
        "flex w-drawer max-w-full shrink-0 flex-col border-l border-border bg-surface",
        overlay && "absolute inset-y-0 right-0 z-20 shadow-modal animate-[cbm-pop-in_160ms_ease-out]",
      )}
    >
      <header className="flex items-start gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 id="profile-drawer-title" ref={headingRef} tabIndex={-1} className="break-words text-md font-semibold text-fg focus:outline-none">
            {profile.name}
          </h2>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-fg-3">
            <span>{groupOf(profile)}</span>
            <span aria-hidden>·</span>
            <span>{engineLabel(profile)}</span>
            <span aria-hidden>·</span>
            <span>{profile.platform === "macos" ? "macOS" : profile.platform === "windows" ? "Windows" : profile.platform}</span>
            {profile.disposable && <Badge tone="warning">一次性</Badge>}
          </div>
        </div>
        <IconButton label="关闭详情" size="sm" icon={<X className="h-4 w-4" />} onClick={onClose} />
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="flex flex-wrap gap-2 px-4 py-3">
          {running ? (
            <Button icon={<Square className="h-3.5 w-3.5" />} loading={busy} onClick={() => actions.stop(profile)}>
              关闭浏览器
            </Button>
          ) : (
            <>
              <Button variant="primary" icon={<Play className="h-3.5 w-3.5" />} loading={busy} onClick={() => actions.launch(profile, "manual")}>
                打开
              </Button>
              <Button icon={<Bug className="h-3.5 w-3.5" />} disabled={busy} onClick={() => actions.launch(profile, "debug")}>
                调试启动
              </Button>
            </>
          )}
          <Button variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => actions.edit(profile)}>
            编辑配置
          </Button>
        </div>

        {hasLaunchFailure(profile) && (
          <div className="px-4 pb-3">
            <Banner tone="danger" title="上次启动失败">
              {launchFailureReason(profile)}
              {profile.last_exit_at && <span className="block text-xs text-fg-3">{formatDateTime(profile.last_exit_at)}</span>}
            </Banner>
          </div>
        )}

        {running && (
          <section aria-label="运行状态" className="mx-4 mb-3 flex flex-col gap-2.5 rounded-md border border-success/30 bg-success-soft p-3">
            <StatusDot status="running" label={profile.viewer_mode === "vnc" ? "运行中（远程画面）" : "运行中（原生窗口）"} />
            <p className="text-sm text-fg-2">
              {manual
                ? "日常模式：没有开启外部 CDP。"
                : "调试模式：可以通过 Manager 的 CDP 地址连接这个浏览器。"}
            </p>
            {!manual && cdpEndpoint && <CopyField label=" CDP 地址" value={cdpEndpoint} />}
            <div className="flex flex-wrap gap-2">
              {profile.viewer_mode === "vnc" && (
                <Button size="sm" variant="primary" icon={<MonitorPlay className="h-3.5 w-3.5" />} onClick={onOpenViewer}>
                  打开远程画面
                </Button>
              )}
              <Button size="sm" icon={<Activity className="h-3.5 w-3.5" />} onClick={() => setSelfCheck(true)}>
                指纹自检
              </Button>
            </div>
          </section>
        )}

        <div className="px-4 pb-4">
          {profile.proxy?.toLowerCase().startsWith("socks5://") && <div className="mb-3"><ProxyIpActions profileId={profile.id} /></div>}
          <KeyValueList
            items={[
              { label: "出口", value: <span className="break-all font-mono text-xs">{proxyHost(profile)}</span> },
              { label: "代理类型", value: proxyType(profile) },
              { label: "连接方式", value: profile.proxy_connection_mode === "relay" ? `经中转 · ${profile.relay_name ?? "已选择"}` : "直接连接" },
              { label: "出口地区", value: locationText(profile) },
              {
                label: "时区 / 语言",
                value: profile.geoip ? "跟随出口 IP" : [profile.timezone, profile.locale].filter(Boolean).join(" · ") || "未设置",
              },
              { label: "账号平台", value: profile.account_platform || "未设置" },
              {
                label: "屏幕",
                // A profile following the display launches with this computer's
                // screen, not the size stored with it.
                value: profile.browser_engine !== "system_chrome" && (profile.fingerprint_options?.screen ?? "real") === "real" && profile.platform === "macos"
                  ? "跟随电脑屏幕"
                  : <span className="tabular">{profile.screen_width} × {profile.screen_height}</span>,
              },
              ...(profile.seed_device?.applies
                ? [{ label: "设备（按种子生成）", value: seedDeviceLabel(profile) ?? "首次打开后显示" }]
                : profile.device_profile
                  ? [{ label: "设备画像", value: <span className="break-all">{profile.device_profile}</span> }]
                  : []),
              { label: "User-Agent", value: <span className="break-all text-xs">{profile.user_agent || "跟随真实浏览器"}</span> },
              { label: "最近打开", value: formatDateTime(profile.last_opened_at) },
              { label: "创建时间", value: formatDateTime(profile.created_at) },
            ]}
          />
        </div>

        <div className="border-t border-border px-4 py-3">
          <div className="mb-1.5 text-xs font-medium text-fg-3">备注</div>
          <NoteField profile={profile} multiline />
        </div>
      </div>

      <footer className="flex flex-wrap gap-1 border-t border-border px-3 py-2">
        <Button variant="ghost" size="sm" icon={<Copy className="h-3.5 w-3.5" />} onClick={() => actions.duplicate(profile)}>
          复制
        </Button>
        <Button variant="danger-ghost" size="sm" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => actions.trash(profile)}>
          移到回收站
        </Button>
        {profile.disposable && (
          <Button variant="danger-ghost" size="sm" icon={<Flame className="h-3.5 w-3.5" />} onClick={() => actions.burn(profile)}>
            焚毁
          </Button>
        )}
      </footer>

      {selfCheck && (
        <Suspense fallback={null}>
          <FingerprintReportDialog profileId={profile.id} profileName={profile.name} onClose={() => setSelfCheck(false)} />
        </Suspense>
      )}
    </aside>
  );
}
