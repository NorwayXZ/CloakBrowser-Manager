import { useQueryClient } from "@tanstack/react-query";
import { Download, History, RefreshCw, X } from "lucide-react";
import { useState } from "react";
import { Badge, Banner, Button, buttonClass, IconButton, KeyValueList, ProgressBar, Section, Skeleton, useConfirm } from "../../ui";
import { LEGACY_PANEL_URL } from "../../app/nav";
import { page } from "../../shared/lib/page";
import { useManagerStatus } from "../app/api";
import { usePreferences } from "./preferences";
import { APP_UPDATE_ACTIVE, message, settingsApi, settingsKeys, useAppUpdate, useUpdateCheck, type AppUpdateState, type UpdateCheck } from "./api";
import { useRestartStalled } from "./updateWatcher";

/** 设置 › 关于与更新: versions, the update check and the packaged app's one-click update. */
export function AboutSection() {
  const status = useManagerStatus();
  const packaged = Boolean(status.data?.app_version);

  return (
    <div className="flex flex-col gap-5">
      <Section id="about" title="关于">
        {status.isPending ? (
          <Skeleton className="h-16 w-full" />
        ) : (
          <KeyValueList
            items={[
              { label: "Manager", value: status.data ? (status.data.app_version ? `v${status.data.app_version}` : "源码版（Git 安装）") : "读不到" },
              { label: "浏览器内核", value: <span className="font-mono">{status.data?.binary_version || "未下载"}</span> },
              { label: "这台电脑", value: status.data?.host_os === "macos" ? "macOS" : status.data?.host_os === "windows" ? "Windows" : (status.data?.host_os ?? "未知") },
            ]}
          />
        )}
      </Section>
      {status.data && <UpdateSection packaged={packaged} running={status.data.running_count} />}
      <LegacySwitch />
    </div>
  );
}

/** One release keeps the previous panel at /legacy/ as a way back. */
function LegacySwitch() {
  const confirm = useConfirm();
  const { setInterface } = usePreferences();
  const [busy, setBusy] = useState(false);

  const switchBack = async () => {
    const ok = await confirm({
      title: "切换回旧版界面？",
      description: "窗口会改用旧版界面，之后每次打开也是旧版，直到你在旧版里点“试用新界面”。数据和设置不受影响。",
      confirmLabel: "切换",
    });
    if (!ok) return;
    setBusy(true);
    try {
      await setInterface("legacy");
      page.assign(LEGACY_PANEL_URL);
    } catch {
      // The preference provider already told the user why it was not saved.
      setBusy(false);
    }
  };

  return (
    <Section id="interface" title="界面版本" description="新界面已经是默认界面。旧版界面只在这个版本里保留，用来应对新界面里遇到的问题；下个版本会删除。">
      <Button icon={<History className="h-4 w-4" />} loading={busy} disabled={busy} onClick={() => void switchBack()}>
        切换回旧版界面
      </Button>
    </Section>
  );
}

function UpdateSection({ packaged, running }: { packaged: boolean; running: number }) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const check = useUpdateCheck();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runCheck = async () => {
    if (running > 0) {
      const ok = await confirm({
        title: packaged ? "有浏览器正在运行，仍然检查更新？" : "有浏览器正在运行，仍然拉取更新？",
        description: packaged
          ? "检查时会顺便下载新内核；已经打开的浏览器要关掉重开才会用上。"
          : "会拉取新代码并重建面板，建议先关闭浏览器。",
        confirmLabel: "继续",
      });
      if (!ok) return;
    }
    setBusy(true);
    setError(null);
    queryClient.setQueryData(settingsKeys.updateCheck, null);
    try {
      const manager = await settingsApi.checkManager();
      let browser: UpdateCheck["browser"] = null;
      let browserError: string | null = null;
      try {
        browser = await settingsApi.updateBrowser();
      } catch (err) {
        browserError = message(err);
      }
      queryClient.setQueryData<UpdateCheck>(settingsKeys.updateCheck, { manager, browser, browserError });
      void queryClient.invalidateQueries({ queryKey: ["manager", "status"] });
      void queryClient.invalidateQueries({ queryKey: settingsKeys.kernel });
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section
      id="update"
      title="更新"
      description={
        packaged
          ? "检查 GitHub 上有没有新版本，同时检查并下载新的浏览器内核。"
          : "源码版：从 GitHub 拉取最新代码并重建面板，同时检查并下载新的浏览器内核。"
      }
      actions={
        <Button variant="primary" icon={<RefreshCw className="h-4 w-4" />} loading={busy} disabled={busy} onClick={() => void runCheck()}>
          {busy ? (packaged ? "检查中…" : "拉取中…") : packaged ? "检查更新" : "拉取更新"}
        </Button>
      }
    >
      <div className="flex flex-col gap-3">
        <AppUpdatePanel available={check.data?.manager.download_url ? (check.data.manager.after ?? null) : null} downloadUrl={check.data?.manager.download_url ?? null} running={running} />
        {error && <Banner tone="danger" title={packaged ? "检查更新失败" : "拉取更新失败"}>{error}</Banner>}
        {check.data && <CheckResult result={check.data} onDismiss={() => queryClient.setQueryData(settingsKeys.updateCheck, null)} />}
        {!check.data && !error && !busy && <p className="text-sm text-fg-2">还没有检查过。</p>}
      </div>
    </Section>
  );
}

/** Says what the check found, without claiming an upgrade that only needs a download or a restart. */
function CheckResult({ result, onDismiss }: { result: UpdateCheck; onDismiss: () => void }) {
  const { manager, browser, browserError } = result;
  const restart = manager.restart_required;
  const title = manager.download_url
    ? `发现新版本${manager.after ? ` ${manager.after}` : ""}，需要下载安装`
    : restart || browser?.restart_required
      ? "已拉取更新，需要重启才生效"
      : manager.updated || browser?.updated
        ? "已更新"
        : "已是最新";
  const tone = manager.download_url || restart || browser?.restart_required ? "info" : "success";
  return (
    <Banner
      tone={tone}
      title={title}
      action={<IconButton label="关闭检查结果" size="sm" icon={<X className="h-4 w-4" />} onClick={onDismiss} />}
    >
      <div className="flex flex-col gap-2">
        <p className="whitespace-pre-line">{[manager.message, browser?.message].filter(Boolean).join("\n")}</p>
        {browserError && <p className="text-danger">内核检查失败：{browserError}</p>}
        {browser && (
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            <span>Wrapper：{browser.wrapper_version || "未知"}</span>
            <span>平台：{browser.platform || "未知"}</span>
            <span>已安装：{browser.installed_version || browser.available_version || "未知"}</span>
            <span className={browser.binary_verified ? "font-medium text-success" : "font-medium text-danger"}>内核：{browser.binary_verified ? "已验证" : "未验证"}</span>
          </div>
        )}
        {restart && <p className="font-medium text-fg">请关闭当前终端里的 Manager，然后重新运行启动命令（或 ./bin/cloak restart）。</p>}
        {!restart && browser?.restart_required && <p className="font-medium text-fg">请关闭正在运行的浏览器，重新打开后使用新内核。</p>}
        {manager.download_url && !manager.updated && (
          <a className={buttonClass("secondary", "sm")} href={manager.download_url} target="_blank" rel="noreferrer">
            <Download className="h-3.5 w-3.5" aria-hidden />
            手动下载安装包
          </a>
        )}
      </div>
    </Banner>
  );
}

function percent(state: AppUpdateState): number | null {
  if (!state.total) return null;
  return Math.min(100, Math.round(((state.done ?? 0) / state.total) * 100));
}

/** The packaged app's one-click update: offer, progress, and the last result. */
function AppUpdatePanel({ available, downloadUrl, running }: { available: string | null; downloadUrl: string | null; running: number }) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const update = useAppUpdate();
  const stalled = useRestartStalled();
  const [error, setError] = useState<string | null>(null);
  const state = update.data;
  if (!state) return null;

  const start = async () => {
    if (running > 0 || !available) return;
    const ok = await confirm({
      title: `更新到 ${available}？`,
      description: "会先做一次完整备份，下载校验后应用自动退出并重启，期间面板会断开几十秒。",
      confirmLabel: "开始更新",
    });
    if (!ok) return;
    setError(null);
    try {
      queryClient.setQueryData(settingsKeys.appUpdate, await settingsApi.startAppUpdate());
    } catch (err) {
      setError(message(err));
    }
  };

  const dismiss = async () => {
    await settingsApi.dismissAppUpdate().catch(() => undefined);
    await update.refetch();
  };

  const manual = downloadUrl ? (
    <a className="underline" href={downloadUrl} target="_blank" rel="noreferrer">
      手动下载
    </a>
  ) : null;

  if (APP_UPDATE_ACTIVE.has(state.phase)) {
    const value = state.phase === "downloading" ? percent(state) : null;
    return (
      <div className="flex flex-col gap-2 rounded-md border border-accent/30 bg-accent-soft p-3" role="status">
        <div className="text-sm font-medium text-fg">
          {state.label ?? "正在更新"}
          {state.target ? `（${state.target}）` : ""}
          {value !== null ? ` ${value}%` : ""}
        </div>
        <ProgressBar value={value} label="更新进度" />
        {state.phase === "restarting" && (
          <p className="text-xs text-fg-2">
            {stalled
              ? "等了 3 分钟还没看到新版本。请从菜单栏或托盘确认应用是否在运行，必要时手动重新打开。"
              : "应用正在退出并替换为新版本，新版本启动后这个页面会自动刷新。"}
          </p>
        )}
      </div>
    );
  }

  const result = state.last_result;
  return (
    <>
      {result && (
        <Banner
          tone={result.ok ? "success" : "danger"}
          title={result.ok ? `已更新到 ${result.to}` : `更新到 ${result.to} 没有成功，仍在使用 ${result.running}`}
          action={<IconButton label="关闭更新结果" size="sm" icon={<X className="h-4 w-4" />} onClick={() => void dismiss()} />}
        >
          {!result.ok && `${result.reason ? `原因：${result.reason}。` : ""}可以稍后再试，或手动下载安装包覆盖。`}
        </Banner>
      )}
      {available && state.supported && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-info/30 bg-info-soft p-3 text-sm">
          <Download className="h-4 w-4 shrink-0 text-info" aria-hidden />
          <span className="font-medium text-fg">新版本 {available} 可以一键更新</span>
          <Button size="sm" variant="primary" disabled={running > 0} title={running > 0 ? "请先关闭所有浏览器" : undefined} onClick={() => void start()}>
            立即更新
          </Button>
          {running > 0 && <Badge tone="warning">请先关闭所有浏览器</Badge>}
          {manual && <span className="text-xs text-fg-2">{manual}</span>}
        </div>
      )}
      {(error || state.phase === "failed") && (
        <Banner tone="danger" title="更新没有完成">
          {error || state.error} {manual}
        </Banner>
      )}
    </>
  );
}
