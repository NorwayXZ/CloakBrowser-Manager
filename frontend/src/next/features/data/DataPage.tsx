import { useQueryClient } from "@tanstack/react-query";
import { Archive, Download, FileJson, FolderOpen, RotateCcw, Trash2, Upload } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router";
import { cn } from "../../shared/lib/cn";
import { log } from "../../shared/log/logger";
import {
  Badge,
  Banner,
  Button,
  buttonClass,
  Card,
  EmptyState,
  ErrorState,
  IconButton,
  PageHeader,
  Section,
  Skeleton,
  Table,
  TD,
  TH,
  THead,
  TR,
  useConfirm,
  useToast,
} from "../../ui";
import { useProfiles } from "../profiles/api";
import { isRunning } from "../profiles/format";
import { AutoBackupSection } from "./AutoBackupSection";
import { backupLabel, dataApi, dataKeys, formatBytes, formatTime, triggerDownload, useAutoBackup, useBackups, useTrash, type BackupItem, type RestoreResult } from "./api";
import { TrashTab } from "./TrashTab";

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

/** 数据: backups (full, automatic, configuration) and the trash, as two tabs. */
export function DataPage() {
  const location = useLocation();
  const trash = useTrash();
  const onTrash = location.pathname.endsWith("/trash");
  const tabs = [
    { to: "/data", label: "备份与恢复", active: !onTrash },
    { to: "/data/trash", label: "回收站", active: onTrash, count: trash.data?.length },
  ];

  return (
    <div className="flex flex-col gap-5 px-6 pb-8 pt-2 lg:px-10">
      <PageHeader title="数据" description="备份、恢复、导出配置，以及 7 天内删除的环境。" />
      <nav aria-label="数据分类" className="flex gap-1 border-b border-border">
        {tabs.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end
            aria-current={tab.active ? "page" : undefined}
            className={cn(
              "-mb-px flex h-9 items-center gap-1.5 border-b-2 px-3 text-sm font-medium transition-colors duration-fast",
              tab.active ? "border-accent text-fg" : "border-transparent text-fg-2 hover:text-fg",
            )}
          >
            {tab.label}
            {tab.count ? <Badge>{tab.count}</Badge> : null}
          </NavLink>
        ))}
      </nav>
      {onTrash ? <TrashTab /> : <BackupTab />}
    </div>
  );
}

function BackupTab() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const backups = useBackups();
  const auto = useAutoBackup();
  const profiles = useProfiles();
  const running = (profiles.data ?? []).filter(isRunning).length;
  const [busy, setBusy] = useState<"full" | "restore" | "export" | "import" | null>(null);
  // The last success that is worth keeping on screen (where restored data went, what was imported).
  const [result, setResult] = useState<{ title: string; text: ReactNode } | null>(null);
  const restoreInput = useRef<HTMLInputElement>(null);
  const configInput = useRef<HTMLInputElement>(null);
  const blocked = running > 0;
  const stopFirst = blocked ? "请先关闭所有浏览器" : undefined;
  const latestFull = (backups.data?.backups ?? []).filter((item) => item.kind === "full").sort((a, b) => b.created_at.localeCompare(a.created_at))[0];

  const refreshAll = () => queryClient.invalidateQueries();

  const run = async (kind: typeof busy, task: () => Promise<void>, failTitle: string) => {
    setBusy(kind);
    setResult(null);
    try {
      await task();
    } catch (error) {
      log.warn(failTitle, { action: `backup.${kind}`, detail: error });
      toast.show({ tone: "error", title: failTitle, description: message(error) });
    } finally {
      setBusy(null);
      void queryClient.invalidateQueries({ queryKey: dataKeys.backups });
    }
  };

  const restored = (outcome: RestoreResult) => {
    setResult({
      title: `已恢复 ${outcome.profiles} 个环境`,
      text: (
        <>
          原来的数据保存在：<span className="break-all font-mono text-xs">{outcome.previous_data}</span>
        </>
      ),
    });
    toast.show({ tone: "success", title: "恢复完成" });
    void refreshAll();
  };

  const createFull = () =>
    run("full", async () => {
      const item = await dataApi.createBackup();
      triggerDownload(dataApi.downloadUrl(item.name), item.name);
      setResult({ title: `完整备份已生成（${formatBytes(item.size)}）`, text: "同时开始下载一份。建议把下载的文件再复制到移动硬盘或网盘。" });
      toast.show({ tone: "success", title: "完整备份已生成" });
    }, "备份没有完成");

  const restoreItem = async (item: BackupItem) => {
    const snapshot = item.kind === "auto";
    const ok = await confirm({
      title: snapshot ? "恢复这个自动快照？" : "恢复这个完整备份？",
      description: snapshot
        ? "自动快照只包含环境列表和设置，不包含 Cookie 等浏览器数据；浏览器数据保持现状。当前数据库会先移到备份文件夹保存。"
        : "会用备份替换当前所有环境、Cookie 和登录状态。当前数据会先移到备份文件夹里的 before-restore-… 目录保存，不会删除。",
      details: <p className="break-all font-mono text-xs text-fg-2">{item.name}</p>,
      confirmLabel: "恢复",
      danger: true,
    });
    if (!ok) return;
    await run("restore", async () => restored(await dataApi.restore(item)), "恢复没有完成");
  };

  const restoreFile = async (file: File | null) => {
    if (restoreInput.current) restoreInput.current.value = "";
    if (!file) return;
    const ok = await confirm({
      title: "从这个文件恢复？",
      description: "会用备份替换当前所有环境、Cookie 和登录状态。当前数据会先移到备份文件夹里的 before-restore-… 目录保存，不会删除。",
      details: <p className="break-all font-mono text-xs text-fg-2">{file.name}</p>,
      confirmLabel: "恢复",
      danger: true,
    });
    if (!ok) return;
    await run("restore", async () => restored(await dataApi.restoreFile(file)), "恢复没有完成");
  };

  const remove = async (item: BackupItem) => {
    const ok = await confirm({ title: `删除备份「${item.name}」？`, description: "删除后不能恢复。", confirmLabel: "删除", danger: true });
    if (!ok) return;
    await run(null, async () => {
      await dataApi.deleteBackup(item);
      toast.show({ tone: "success", title: "已删除备份" });
    }, "没有删除");
  };

  const exportConfig = () =>
    run("export", async () => {
      const backup = await dataApi.exportConfig();
      const url = URL.createObjectURL(new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" }));
      triggerDownload(url, `cloakbrowser-configuration-${new Date().toISOString().slice(0, 10)}.json`);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.show({ tone: "success", title: "配置备份已下载", description: "文件里有代理和 Cookie，请妥善保管。" });
    }, "导出没有完成");

  const importConfig = (file: File | null) => {
    if (configInput.current) configInput.current.value = "";
    if (!file) return;
    void run("import", async () => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(await file.text());
      } catch {
        throw new Error("这不是一个配置备份文件（无法读取 JSON）");
      }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("备份文件格式不正确");
      const outcome = await dataApi.importConfig(parsed as Record<string, unknown>);
      setResult({ title: "配置已导入", text: `新增 ${outcome.profiles} 个环境、${outcome.groups} 个分组、${outcome.proxy_presets} 个代理。` });
      toast.show({ tone: "success", title: "配置已导入" });
      void refreshAll();
    }, "导入没有完成");
  };

  return (
    <div className="flex max-w-form flex-col gap-5">
      <Card className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Stat label="最近完整备份" value={backups.isPending ? null : latestFull ? formatTime(latestFull.created_at) : "还没有"} />
        <Stat label="下次自动备份" value={auto.isPending ? null : auto.data?.enabled ? formatTime(auto.data.next_due_at) : "已关闭"} />
        <Stat label="备份文件夹" value={backups.isPending ? null : <span className="break-all font-mono text-xs">{backups.data?.location ?? "—"}</span>} />
      </Card>

      {blocked && (
        <Banner tone="warning" title={`有 ${running} 个浏览器正在运行`}>
          为了保证 Cookie 等数据完整，备份和恢复前请先关闭所有浏览器。
        </Banner>
      )}
      {result && (
        <Banner tone="success" title={result.title}>
          {result.text}
        </Banner>
      )}

      <Section id="full-backup" title="完整备份（推荐）" description="包含所有环境的 Cookie、登录状态、历史记录、本地存储、标签页，以及环境列表、分组、代理和加密密钥。网页缓存不备份。备份文件里有账号登录信息，不要发给别人。">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary" icon={<Archive className="h-4 w-4" />} loading={busy === "full"} disabled={busy !== null || blocked} title={stopFirst} onClick={() => void createFull()}>
            立即完整备份
          </Button>
          <input ref={restoreInput} type="file" accept="application/zip,.zip" className="hidden" aria-hidden tabIndex={-1} onChange={(event) => void restoreFile(event.target.files?.[0] ?? null)} />
          <Button icon={<Upload className="h-4 w-4" />} loading={busy === "restore"} disabled={busy !== null || blocked} title={stopFirst} onClick={() => restoreInput.current?.click()}>
            从备份文件恢复
          </Button>
          <Button variant="ghost" icon={<FolderOpen className="h-4 w-4" />} title={backups.data?.location} onClick={() => void dataApi.reveal().catch((error) => toast.show({ tone: "error", title: "没能打开文件夹", description: message(error) }))}>
            打开备份文件夹
          </Button>
        </div>
      </Section>

      <AutoBackupSection running={running} />

      <Section id="backup-history" title="备份记录" description="每次启动 Manager 会自动保存一份环境列表快照（保留最近 10 份）。">
        {backups.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : backups.isError ? (
          <ErrorState message={backups.error.message} onRetry={() => void backups.refetch()} />
        ) : backups.data.backups.length === 0 ? (
          <EmptyState icon={Archive} title="还没有备份" description="点上面的“立即完整备份”做第一份。" />
        ) : (
          <Table label="备份记录" minWidth={560}>
            <colgroup>
              <col />
              <col className="w-36" />
              <col className="w-24" />
              <col className="w-44" />
            </colgroup>
            <THead>
              <tr>
                <TH>备份</TH>
                <TH>时间</TH>
                <TH>大小</TH>
                <TH className="text-right">操作</TH>
              </tr>
            </THead>
            <tbody>
              {backups.data.backups.map((item) => (
                <TR key={`${item.kind}-${item.name}`}>
                  <TD className="py-2">
                    <div className="font-medium">{backupLabel(item)}</div>
                    <div className="truncate font-mono text-xs text-fg-3" title={item.name}>
                      {item.name}
                    </div>
                  </TD>
                  <TD className="text-fg-2">{formatTime(item.created_at)}</TD>
                  <TD className="tabular text-fg-2">{formatBytes(item.size)}</TD>
                  <TD className="text-right">
                    <div className="flex justify-end gap-1">
                      {item.kind === "full" && (
                        <a className={buttonClass("ghost", "sm")} href={dataApi.downloadUrl(item.name)} download={item.name} aria-label={`下载 ${item.name}`}>
                          <Download className="h-3.5 w-3.5" aria-hidden />
                          下载
                        </a>
                      )}
                      <Button size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} disabled={busy !== null || blocked} title={stopFirst} onClick={() => void restoreItem(item)} aria-label={`恢复到 ${item.name}`}>
                        恢复
                      </Button>
                      <IconButton size="sm" variant="danger-ghost" label={`删除备份 ${item.name}`} icon={<Trash2 className="h-3.5 w-3.5" />} disabled={busy !== null} onClick={() => void remove(item)} />
                    </div>
                  </TD>
                </TR>
              ))}
            </tbody>
          </Table>
        )}
      </Section>

      <Section id="config-backup" title="只导出配置（JSON）" description="只包含环境配置、分组、代理和 Cookie JSON，不含登录状态和浏览记录。适合把设置迁到另一台电脑；导入时会新建环境记录，同名代理会更新。">
        <div className="flex flex-wrap gap-2">
          <Button icon={<FileJson className="h-4 w-4" />} loading={busy === "export"} disabled={busy !== null} onClick={() => void exportConfig()}>
            下载配置备份
          </Button>
          <input ref={configInput} type="file" accept="application/json,.json" className="hidden" aria-hidden tabIndex={-1} onChange={(event) => importConfig(event.target.files?.[0] ?? null)} />
          <Button icon={<Upload className="h-4 w-4" />} loading={busy === "import"} disabled={busy !== null || blocked} title={stopFirst} onClick={() => configInput.current?.click()}>
            导入配置
          </Button>
        </div>
      </Section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: ReactNode | null }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-fg-3">{label}</div>
      <div className="mt-0.5 text-sm font-medium text-fg">{value === null ? <Skeleton className="mt-1 h-4 w-28" /> : value}</div>
    </div>
  );
}
