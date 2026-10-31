import { Activity, ArrowLeft, ClipboardCopy, Maximize2, Minimize2, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { log } from "../../shared/log/logger";
import { Button, CopyField, EmptyState, ErrorState, IconButton, Spinner, StatusDot, useToast } from "../../ui";
import { profilesApi, useProfiles } from "./api";
import { FingerprintReportDialog } from "./FingerprintReportDialog";
import { isRunning } from "./format";
import { useLaunch } from "./launch";

// X11 keysyms: the full Ctrl+V sequence is replayed after the clipboard is pushed.
const XK_CONTROL_L = 0xffe3;
const XK_V = 0x0076;

/** Minimal surface of noVNC's RFB object that this page uses. */
interface Rfb {
  scaleViewport: boolean;
  resizeSession: boolean;
  showDotCursor: boolean;
  disconnect: () => void;
  sendKey: (keysym: number, code: string, down: boolean) => void;
  addEventListener: (type: string, listener: (event: CustomEvent) => void) => void;
  removeEventListener: (type: string, listener: (event: CustomEvent) => void) => void;
}

/**
 * The remote screen of a browser running in the Docker deployment (KasmVNC),
 * with two-way clipboard sync. Leaves for the list when the browser stops.
 */
export function ViewerPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { stop, busy } = useLaunch();
  const profiles = useProfiles();
  const profile = profiles.data?.find((item) => item.id === id);
  const running = profile ? isRunning(profile) : false;
  const [selfCheck, setSelfCheck] = useState(false);
  const stoppedHere = useRef(false);

  const back = useCallback(() => navigate(`/profiles?p=${encodeURIComponent(id)}`), [id, navigate]);

  // The browser went away (closed, crashed, or deleted): go back to the list.
  useEffect(() => {
    if (profiles.isSuccess && (!profile || !running)) {
      // Stopping from this page already says so; only report a close that happened elsewhere.
      if (!stoppedHere.current) toast.show({ tone: "info", title: profile ? `「${profile.name}」已关闭` : "这个环境已不存在" });
      back();
    }
  }, [back, profile, profiles.isSuccess, running, toast]);

  if (profiles.isPending) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-fg-2">
        <Spinner label="正在读取" /> 正在读取…
      </div>
    );
  }
  if (profiles.isError) return <ErrorState message={profiles.error.message} onRetry={() => void profiles.refetch()} />;
  if (!profile || !running) return null;
  if (profile.viewer_mode !== "vnc") {
    return (
      <EmptyState
        title="这个浏览器在原生窗口里运行"
        description="请在电脑上弹出的浏览器窗口里使用它；远程画面只用于服务器部署。"
        action={<Button onClick={back}>回到列表</Button>}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border/40 bg-surface/60 px-3 py-1.5 backdrop-blur-xl">
        <IconButton label="回到列表" icon={<ArrowLeft className="h-4 w-4" />} onClick={back} />
        <span className="min-w-0 truncate text-sm font-medium text-fg">{profile.name}</span>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {profile.cdp_url && <CopyField className="w-64" label=" CDP 地址" value={`${window.location.origin}${profile.cdp_url}`} />}
          <Button size="sm" icon={<Activity className="h-3.5 w-3.5" />} disabled={!profile.cdp_url} title={profile.cdp_url ? undefined : "先用调试模式启动，才能运行指纹自检"} onClick={() => setSelfCheck(true)}>
            指纹自检
          </Button>
          <Button size="sm" icon={<Square className="h-3 w-3" />} loading={busy.has(profile.id)} onClick={() => {
              stoppedHere.current = true;
              void stop([profile]);
            }}>
            关闭浏览器
          </Button>
        </div>
      </div>
      <VncScreen key={profile.id} profileId={profile.id} initialClipboardSync={profile.clipboard_sync} onDisconnect={back} />
      {selfCheck && <FingerprintReportDialog profileId={profile.id} profileName={profile.name} onClose={() => setSelfCheck(false)} />}
    </div>
  );
}

function VncScreen({ profileId, initialClipboardSync, onDisconnect }: { profileId: string; initialClipboardSync: boolean; onDisconnect: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<Rfb | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [clipboardSync, setClipboardSync] = useState(initialClipboardSync);

  useEffect(() => {
    let rfb: Rfb | null = null;
    let cancelled = false;
    void (async () => {
      try {
        const { default: RFB } = await import("@novnc/novnc/core/rfb.js");
        if (cancelled || !containerRef.current) return;
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        rfb = new RFB(containerRef.current, `${protocol}//${window.location.host}/api/profiles/${profileId}/vnc`, {
          wsProtocols: ["binary"],
        }) as unknown as Rfb;
        rfbRef.current = rfb;
        rfb.scaleViewport = true;
        rfb.resizeSession = false;
        rfb.showDotCursor = true;
        rfb.addEventListener("connect", () => !cancelled && setConnected(true));
        rfb.addEventListener("disconnect", () => {
          if (cancelled) return;
          setConnected(false);
          onDisconnect();
        });
        rfb.addEventListener("securityfailure", (event) => setError(`安全校验失败：${(event.detail as { reason?: string })?.reason ?? "未知原因"}`));
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "连接失败");
      }
    })();
    return () => {
      cancelled = true;
      try {
        rfb?.disconnect();
      } catch {
        // already closed
      }
      rfbRef.current = null;
    };
  }, [profileId, onDisconnect]);

  // Host → browser: intercept paste before noVNC sends the keystroke, push the
  // clipboard first, then replay the whole Ctrl+V (the user may have released Ctrl).
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !clipboardSync || !connected) return;
    const onKeyDown = async (event: KeyboardEvent) => {
      const paste = event.key === "v" && (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey;
      if (!paste) return;
      event.stopPropagation();
      event.preventDefault();
      const rfb = rfbRef.current;
      if (!rfb) return;
      try {
        const text = await navigator.clipboard.readText();
        if (text) await profilesApi.setClipboard(profileId, text);
      } catch (err) {
        log.warn("剪贴板同步失败，已关闭", { action: "vnc.clipboard.paste", detail: err });
        setClipboardSync(false);
        return;
      }
      rfb.sendKey(XK_CONTROL_L, "ControlLeft", true);
      rfb.sendKey(XK_V, "KeyV", true);
      rfb.sendKey(XK_V, "KeyV", false);
      rfb.sendKey(XK_CONTROL_L, "ControlLeft", false);
    };
    container.addEventListener("keydown", onKeyDown, true);
    return () => container.removeEventListener("keydown", onKeyDown, true);
  }, [profileId, clipboardSync, connected]);

  // Browser → host: KasmVNC clipboard events (converted by the backend proxy) ...
  useEffect(() => {
    const rfb = rfbRef.current;
    if (!rfb || !clipboardSync || !connected) return;
    const onClipboard = (event: CustomEvent) => {
      const text = (event.detail as { text?: string })?.text;
      if (text) navigator.clipboard.writeText(text).catch(() => undefined);
    };
    rfb.addEventListener("clipboard", onClipboard);
    return () => rfb.removeEventListener("clipboard", onClipboard);
  }, [clipboardSync, connected]);

  // ... plus polling, because Chrome copies do not reach the X11 clipboard under KasmVNC.
  useEffect(() => {
    if (!clipboardSync || !connected) return;
    let cancelled = false;
    let last = "";
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (cancelled) return;
      try {
        const { text } = await profilesApi.getClipboard(profileId);
        if (text && text !== last) {
          last = text;
          await navigator.clipboard.writeText(text).catch(() => undefined);
        }
      } catch {
        return; // stop polling; the user can toggle sync to retry
      }
      if (!cancelled) timer = setTimeout(() => void poll(), 2000);
    };
    timer = setTimeout(() => void poll(), 2000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [profileId, clipboardSync, connected]);

  useEffect(() => {
    const onChange = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const onWheel = (event: WheelEvent) => event.preventDefault();
    container.addEventListener("wheel", onWheel, { passive: false });
    return () => container.removeEventListener("wheel", onWheel);
  }, []);

  const toggleFullscreen = () => {
    if (!frameRef.current) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void frameRef.current.requestFullscreen();
  };

  if (error) return <ErrorState title="远程画面连接失败" message={error} onRetry={onDisconnect} retryLabel="回到列表" />;

  return (
    <div ref={frameRef} className="flex min-h-0 flex-1 flex-col bg-canvas">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border/40 bg-surface/60 px-3 py-1 backdrop-blur-xl">
        <StatusDot status={connected ? "running" : "busy"} label={connected ? "已连接" : "连接中…"} />
        <div className="flex items-center gap-1">
          <IconButton
            size="sm"
            label={clipboardSync ? "关闭剪贴板同步" : "开启剪贴板同步"}
            aria-pressed={clipboardSync}
            className="aria-pressed:bg-accent-soft aria-pressed:text-accent"
            icon={<ClipboardCopy className="h-3.5 w-3.5" />}
            disabled={!connected}
            onClick={() => setClipboardSync((value) => !value)}
          />
          <IconButton
            size="sm"
            label={fullscreen ? "退出全屏" : "全屏"}
            icon={fullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
            onClick={toggleFullscreen}
          />
        </div>
      </div>
      <div ref={containerRef} className="min-h-0 flex-1 overflow-hidden bg-black" />
    </div>
  );
}
