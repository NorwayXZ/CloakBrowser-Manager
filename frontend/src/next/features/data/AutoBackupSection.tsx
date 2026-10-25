import { useQueryClient } from "@tanstack/react-query";
import { Play, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { Banner, Button, Checkbox, ErrorState, FormField, Input, KeyValueList, Section, Select, Skeleton, Switch, useToast } from "../../ui";
import { dataApi, dataKeys, formatTime, useAutoBackup, type AutoBackupSettings, type AutoBackupStatus } from "./api";

const INTERVALS: [number, string][] = [
  [1, "每天"],
  [3, "每 3 天"],
  [7, "每周（推荐）"],
  [14, "每两周"],
  [30, "每月"],
];

function settingsOf(status: AutoBackupStatus): AutoBackupSettings {
  return { enabled: status.enabled, interval_days: status.interval_days, keep: status.keep, copy_dir: status.copy_dir };
}

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Scheduled full backups, with a second copy outside the data directory (app
 * cleaners delete the data directory together with the app).
 */
export function AutoBackupSection({ running }: { running: number }) {
  const auto = useAutoBackup();
  if (auto.isPending) {
    return (
      <Section id="auto-backup" title="自动完整备份">
        <Skeleton className="h-32 w-full" />
      </Section>
    );
  }
  if (auto.isError) {
    return (
      <Section id="auto-backup" title="自动完整备份">
        <ErrorState title="自动备份设置没有读出来" message={auto.error.message} onRetry={() => void auto.refetch()} />
      </Section>
    );
  }
  return <AutoBackupForm status={auto.data} running={running} />;
}

function AutoBackupForm({ status, running }: { status: AutoBackupStatus; running: number }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState(() => settingsOf(status));
  const [copyEnabled, setCopyEnabled] = useState(Boolean(status.copy_dir));
  const [busy, setBusy] = useState<"save" | "run" | null>(null);
  const [notice, setNotice] = useState<{ tone: "success" | "danger"; text: string } | null>(null);

  // Take the server's values whenever they change (after saving or running).
  useEffect(() => {
    setDraft(settingsOf(status));
    setCopyEnabled(Boolean(status.copy_dir));
  }, [status]);

  const effective: AutoBackupSettings = { ...draft, copy_dir: copyEnabled ? draft.copy_dir?.trim() || status.default_copy_dir : null };
  const changed = JSON.stringify(effective) !== JSON.stringify(settingsOf(status));

  const apply = (next: AutoBackupStatus) => queryClient.setQueryData(dataKeys.auto, next);

  const save = async () => {
    setBusy("save");
    setNotice(null);
    try {
      apply(await dataApi.saveAuto(effective));
      toast.show({ tone: "success", title: "自动备份设置已保存。" });
    } catch (error) {
      setNotice({ tone: "danger", text: message(error) });
    } finally {
      setBusy(null);
    }
  };

  const runNow = async () => {
    setBusy("run");
    setNotice(null);
    try {
      const result = await dataApi.runAuto();
      apply(result.status);
      void queryClient.invalidateQueries({ queryKey: dataKeys.backups });
      setNotice(result.copy_error ? { tone: "danger", text: result.copy_error } : { tone: "success", text: `已备份：${result.name}${result.copy ? `\n另存一份在：${result.copy}` : ""}` });
    } catch (error) {
      setNotice({ tone: "danger", text: message(error) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <Section id="auto-backup" title="自动完整备份" description="按计划做完整备份，并另存一份到数据目录之外：清理软件删除应用时会连数据目录一起删掉，里面的备份也会没了。">
      <div className="flex flex-col gap-4">
        <Switch checked={draft.enabled} onCheckedChange={(enabled) => setDraft({ ...draft, enabled })} label="自动备份" description="到时间时如果有浏览器在运行，会等它们全部关闭后再开始。" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField label="备份频率">
            <Select value={draft.interval_days} disabled={!draft.enabled} onChange={(event) => setDraft({ ...draft, interval_days: Number(event.target.value) })}>
              {INTERVALS.map(([days, label]) => (
                <option key={days} value={days}>
                  {label}
                </option>
              ))}
              {!INTERVALS.some(([days]) => days === draft.interval_days) && <option value={draft.interval_days}>每 {draft.interval_days} 天</option>}
            </Select>
          </FormField>
          <FormField label="保留份数" description="只自动清理自动备份，手动备份不会被删。">
            <Input type="number" min={1} max={100} inputMode="numeric" value={draft.keep} onChange={(event) => setDraft({ ...draft, keep: Math.max(1, Number(event.target.value) || 1) })} />
          </FormField>
        </div>
        <Checkbox checked={copyEnabled} onCheckedChange={setCopyEnabled} label="复制到数据目录之外" description="每次自动备份都在这个文件夹里另存一份。" />
        {copyEnabled && (
          <FormField label="另存目录" description="留空使用默认文件夹。">
            <Input mono value={draft.copy_dir ?? ""} placeholder={status.default_copy_dir} onChange={(event) => setDraft({ ...draft, copy_dir: event.target.value })} />
          </FormField>
        )}
        <div className="rounded-md bg-surface-2 p-3">
          <KeyValueList
            items={[
              { label: "上次自动备份", value: formatTime(status.last_at) },
              {
                label: "下次",
                value: status.enabled ? (
                  <>
                    {formatTime(status.next_due_at)}
                    {status.waiting_for_browsers && <span className="ml-2 text-warning">（已到时间，等浏览器全部关闭后开始）</span>}
                  </>
                ) : (
                  "已关闭"
                ),
              },
              ...(status.last_copy ? [{ label: "最近一份另存在", value: <span className="break-all font-mono text-xs">{status.last_copy}</span> }] : []),
            ]}
          />
          {status.last_error && <p className="mt-2 break-all text-sm text-danger">{status.last_error}</p>}
        </div>
        {notice && (
          <Banner tone={notice.tone}>
            <span className="whitespace-pre-line break-all">{notice.text}</span>
          </Banner>
        )}
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" icon={<Save className="h-4 w-4" />} loading={busy === "save"} disabled={busy !== null || !changed} onClick={() => void save()}>
            保存设置
          </Button>
          <Button icon={<Play className="h-4 w-4" />} loading={busy === "run"} disabled={busy !== null || running > 0} title={running > 0 ? "请先关闭所有浏览器" : undefined} onClick={() => void runNow()}>
            立即备份一次
          </Button>
        </div>
      </div>
    </Section>
  );
}
