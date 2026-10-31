import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Settings2, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { cn } from "../../../shared/lib/cn";
import { Badge, Banner, Button, Checkbox, FormField, Hint, IconButton, Input, Section, Select, Skeleton, Textarea } from "../../../ui";
import { editorApi, editorKeys, useAutomationHours, useWarmupInfo, useWarmupScripts, useWarmupTargets } from "../api";
import { extensionPaths } from "../model";
import type { HostOS, WarmupScriptBatch } from "../types";
import type { Editor } from "../useEditor";

export function AdvancedSection({ editor, profileId, hostOS }: { editor: Editor; profileId: string | null; hostOS: HostOS | null }) {
  const { form, set } = editor;
  const [argInput, setArgInput] = useState("");

  const addArg = () => {
    if (editor.addLaunchArg(argInput)) setArgInput("");
  };

  return (
    <Section id="form-advanced" title="高级设置" description="默认已经按日常本地使用调好；启动参数属于工程级选项，不清楚用途就保持为空。">
      <div className="flex max-w-form flex-col gap-5">
        <fieldset className="flex flex-col gap-4">
          <legend className="mb-2 text-sm font-medium text-fg">行为与启动</legend>
          <Checkbox
            checked={form.humanize ?? false}
            onCheckedChange={(value) => set("humanize", value)}
            label="模拟真人鼠标、键盘和滚动行为"
            description="新建环境默认开启，让 Manager 控制和远程操作更自然；它不等于保证通过网站风控。"
          />
          {form.humanize && (
            <FormField label="行为速度" className="ml-7 max-w-xs">
              <Select value={form.human_preset} onChange={(event) => set("human_preset", event.target.value)}>
                <option value="default">默认（正常速度）</option>
                <option value="careful">谨慎（更慢、更稳）</option>
              </Select>
            </FormField>
          )}
          <Checkbox
            checked={form.clipboard_sync ?? true}
            onCheckedChange={(value) => set("clipboard_sync", value)}
            label="默认启用远程画面剪贴板同步"
            description="使用远程（VNC）画面时，可以在本机和浏览器之间复制粘贴文本；本机原生窗口基本无感，保持开启即可。"
          />
          <Checkbox
            checked={form.auto_launch ?? false}
            onCheckedChange={(value) => set("auto_launch", value)}
            label="Manager 启动后自动打开"
            description="只建议常用的固定环境开启；否则 Manager 每次启动都会把它拉起来。"
          />
          <Checkbox
            checked={form.warmup_enabled ?? false}
            onCheckedChange={(value) => set("warmup_enabled", value)}
            label="养号（定时自动浏览养护）"
            description={
              <Hint>
                开启后，Manager 会按计划在后台无头打开这个环境（不弹窗、不打扰你），像真人一样浏览与它地区相符的站点和下面勾选的目标平台，让第一方 Cookie 自然积累年龄。全程不登录、不下单、不发帖，只浏览与搜索；浏览器正在使用或授权并发已满时自动跳过。
              </Hint>
            }
          />
          {form.warmup_enabled && <WarmupPanel editor={editor} profileId={profileId} />}
        </fieldset>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <FormField label="颜色偏好" description="网页里的 prefers-color-scheme；不确定就选跟随系统。">
            <Select value={form.color_scheme ?? ""} onChange={(event) => set("color_scheme", event.target.value || null)}>
              <option value="">跟随系统</option>
              <option value="light">浅色</option>
              <option value="dark">深色</option>
              <option value="no-preference">无偏好</option>
            </Select>
          </FormField>
        </div>

        <FormField label="扩展目录" description="每行一个已经解压的 Chrome 扩展目录，Manager 会自动生成启动参数；目录移动或删除后要在这里同步修改。">
          <Textarea
            mono
            rows={3}
            className="text-xs"
            spellCheck={false}
            value={extensionPaths(form.launch_args).join("\n")}
            placeholder={hostOS === "windows" ? "每行一个目录，例如 C:\\Extensions\\MyExtension" : "每行一个目录，例如 /Users/name/Extensions/MyExtension"}
            onChange={(event) => editor.setExtensionPaths(event.target.value)}
          />
        </FormField>

        <details className="group rounded-md border border-border" open={editor.state.launchArgsOpen} onToggle={(event) => editor.setLaunchArgsOpen(event.currentTarget.open)}>
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-sm font-medium text-fg">
            <span className="flex items-center gap-1.5">
              <Settings2 className="h-4 w-4 text-fg-3" aria-hidden />
              启动参数
              {(form.launch_args ?? []).length > 0 && <Badge>{(form.launch_args ?? []).length}</Badge>}
            </span>
            <span className="text-xs font-normal text-fg-3 group-open:hidden">展开</span>
            <span className="hidden text-xs font-normal text-fg-3 group-open:inline">收起</span>
          </summary>
          <div className="flex flex-col gap-3 border-t border-border p-3">
            {(form.launch_args ?? []).length > 0 && (
              <ul className="flex flex-wrap gap-1.5" aria-label="已添加的启动参数">
                {(form.launch_args ?? []).map((arg, index) => (
                  <li key={`${arg}-${index}`} className="inline-flex max-w-full items-center gap-1 rounded-sm bg-surface-2 py-0.5 pl-2 pr-0.5 font-mono text-xs text-fg">
                    <span className="break-all">{arg}</span>
                    <IconButton size="sm" className="h-5 w-5" label={`移除启动参数 ${arg}`} icon={<X className="h-3 w-3" />} onClick={() => editor.removeLaunchArg(index)} />
                  </li>
                ))}
              </ul>
            )}
            <div className="flex gap-2">
              <Input
                mono
                aria-label="新的启动参数"
                value={argInput}
                placeholder="--load-extension=/path/to/extension"
                onChange={(event) => setArgInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    addArg();
                  }
                }}
              />
              <IconButton label="添加启动参数" variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={addArg} />
            </div>
            <p className="text-xs text-fg-3">参数直接追加给 Chrome，常见用途是加载本地扩展或临时实验开关；普通使用留空最稳。</p>
          </div>
        </details>
      </div>
    </Section>
  );
}

function WarmupPanel({ editor, profileId }: { editor: Editor; profileId: string | null }) {
  const { form, set } = editor;
  const targets = useWarmupTargets();
  const selected = form.warmup_targets ?? [];

  return (
    <div className="ml-7 flex flex-col gap-4 rounded-md border border-border bg-surface-2 p-3">
      <FormField label="每天最多" className="max-w-40">
        <Select value={form.warmup_daily_max ?? 1} onChange={(event) => set("warmup_daily_max", Number(event.target.value))}>
          {[1, 2, 3].map((n) => (
            <option key={n} value={n}>
              {n} 次
            </option>
          ))}
        </Select>
      </FormField>
      <FormField label="画像人格（可选）" description="一句话描述这个环境的人设；AI 养号会按它编写一周剧本的主题和搜索词，不填则按地区和语言生成通用剧本。">
        <Input maxLength={200} value={form.warmup_persona ?? ""} placeholder="如：32 岁，台北，喜欢摄影和手冲咖啡" onChange={(event) => set("warmup_persona", event.target.value)} />
      </FormField>
      <fieldset>
        <legend className="text-sm font-medium text-fg">定向养护平台</legend>
        <p className="mb-2 mt-0.5 text-xs text-fg-3">定向养护：在目标平台留下并积累第一方 Cookie 年龄（如 Facebook 的 datr、Amazon 的 session-id），让后续正式使用时不像全新设备。</p>
        <div className="flex flex-wrap gap-1.5">
          {targets.isPending && <Skeleton className="h-6 w-40" />}
          {targets.isError && <span className="text-xs text-danger">平台目录没有加载出来：{targets.error.message}</span>}
          {(targets.data ?? []).map((target) => {
            const active = selected.includes(target.id);
            return (
              <button
                key={target.id}
                type="button"
                aria-pressed={active}
                onClick={() => set("warmup_targets", active ? selected.filter((id) => id !== target.id) : [...selected, target.id])}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-xs transition-colors duration-fast",
                  active ? "border-accent-fill bg-accent-fill text-accent-on" : "border-border-strong bg-surface text-fg-2 hover:bg-surface-3",
                )}
              >
                {target.name}
              </button>
            );
          })}
        </div>
      </fieldset>
      {profileId && <WarmupStatus profileId={profileId} />}
    </div>
  );
}

const RUN_STATUS: Record<string, string> = { ok: "完成", skipped: "跳过" };

function WarmupStatus({ profileId }: { profileId: string }) {
  const queryClient = useQueryClient();
  const info = useWarmupInfo(profileId);
  const hours = useAutomationHours();
  const run = useMutation({
    mutationFn: () => editorApi.runWarmup(profileId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: editorKeys.warmup(profileId) }),
  });
  if (info.isPending) return <Skeleton className="h-16 w-full" />;
  if (info.isError || !info.data) return null;
  const { age, runs, warming } = info.data;

  return (
    <div className="flex flex-col gap-2 border-t border-border pt-3 text-sm text-fg-2">
      <p>
        创建于 {age.created_at?.slice(0, 10) ?? "—"}
        {age.age_days != null && `（${age.age_days} 天）`} · 已养号 {age.warmup_sessions} 次 · 最近活动{" "}
        {age.last_warmup_at ? age.last_warmup_at.slice(0, 16).replace("T", " ") : "暂无"}
      </p>
      {runs.length > 0 && (
        <ul className="flex flex-col gap-0.5 text-xs">
          {runs.slice(0, 5).map((item) => (
            <li key={item.id}>
              {item.started_at.slice(0, 16).replace("T", " ")} · {RUN_STATUS[item.status] ?? "失败"}
              {item.status === "ok" && ` · ${item.pages_visited} 页`}
              {item.reason && ` · ${item.reason}`}
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" loading={run.isPending} disabled={warming} onClick={() => run.mutate()}>
          {warming ? "正在养号…" : "立即养一次"}
        </Button>
        {run.isError && <span className="text-xs text-danger">没能开始：{run.error.message}</span>}
      </div>
      {hours.data?.hours && !hours.data.open_now && (
        <p className="text-xs text-warning" role="note">
          当前不在自动化时段（{hours.data.hours}）内：定时任务会推迟到时段内，手动触发不受影响，点按钮会立即开始。
        </p>
      )}
      <WarmupScripts profileId={profileId} />
    </div>
  );
}

const DWELL: Record<string, string> = { short: "短停", medium: "中停", long: "长停" };
const BATCH_STATUS: Record<string, { label: string; tone: "accent" | "success" | "neutral" | "danger" }> = {
  draft: { label: "待审核", tone: "accent" },
  approved: { label: "生效中", tone: "success" },
  rejected: { label: "已驳回", tone: "danger" },
  archived: { label: "已归档", tone: "neutral" },
};

function stepLine(step: WarmupScriptBatch["scripts"][number]["steps"][number]): string {
  const parts = [step.kind === "target" ? step.platform_name || step.platform || "目标平台" : "本地站点"];
  if (step.search_query) parts.push(`搜「${step.search_query}」`);
  parts.push(DWELL[step.dwell] ?? "中停");
  if (step.follow_link) parts.push("跟一条链接");
  return parts.join(" · ");
}

function WarmupScripts({ profileId }: { profileId: string }) {
  const queryClient = useQueryClient();
  const scripts = useWarmupScripts(profileId);
  const refresh = () => queryClient.invalidateQueries({ queryKey: editorKeys.scripts(profileId) });
  const generate = useMutation({ mutationFn: () => editorApi.generateScripts(profileId), onSettled: refresh });
  const decide = useMutation({ mutationFn: ({ batch, approve }: { batch: string; approve: boolean }) => editorApi.decideScripts(profileId, batch, approve), onSettled: refresh });
  const info = scripts.data;
  if (!info) return null;
  const error = generate.error ?? decide.error;

  return (
    <div className="mt-1 flex flex-col gap-2 border-t border-border pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-fg">AI 剧本（一周包）</span>
        {info.llm_configured && (
          <Button size="sm" icon={<Sparkles className="h-3.5 w-3.5" />} loading={info.generating || generate.isPending} disabled={decide.isPending} onClick={() => generate.mutate()}>
            {info.generating ? "生成中…" : "生成新剧本"}
          </Button>
        )}
      </div>
      <p className="text-xs text-fg-3">
        {info.llm_configured
          ? "剧本由 AI 离线编写，只包含访问和搜索意图，网址仍由 Manager 按平台目录生成；批准一批后，养号按天轮换其中的剧本，没有生效剧本时继续用随机计划。"
          : "还没有配置 AI 接口：在“设置 › AI 接口”填好接口地址、模型和密钥后，这里可以按画像人格生成一周的养号剧本，批准后自动按天轮换执行。"}
      </p>
      {info.last_generation?.status === "error" && <Banner tone="danger">上次生成失败：{info.last_generation.error}</Banner>}
      {error && <Banner tone="danger">{error.message}</Banner>}
      {info.llm_configured && info.batches.length === 0 && <p className="text-xs text-fg-3">还没有生成过剧本。</p>}
      {info.batches.map((batch) => {
        const status = BATCH_STATUS[batch.status] ?? { label: batch.status, tone: "neutral" as const };
        return (
          <div key={batch.batch_id} className="glass rounded-lg p-2.5 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-fg-2">
                {batch.created_at.slice(0, 16).replace("T", " ")}
                <Badge tone={status.tone}>{status.label}</Badge>
                {batch.model}
              </span>
              {batch.status === "draft" && (
                <span className="flex gap-1.5">
                  <Button size="sm" variant="primary" disabled={decide.isPending} onClick={() => decide.mutate({ batch: batch.batch_id, approve: true })}>
                    整批批准
                  </Button>
                  <Button size="sm" disabled={decide.isPending} onClick={() => decide.mutate({ batch: batch.batch_id, approve: false })}>
                    驳回
                  </Button>
                </span>
              )}
            </div>
            <div className="mt-1.5 flex flex-col gap-1.5">
              {batch.scripts.map((script) => (
                <div key={script.id}>
                  <div className="font-medium text-fg">{script.theme || "（无主题）"}</div>
                  <ul className="ml-4 list-disc text-fg-2">
                    {script.steps.map((step, index) => (
                      <li key={index}>{stepLine(step)}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
