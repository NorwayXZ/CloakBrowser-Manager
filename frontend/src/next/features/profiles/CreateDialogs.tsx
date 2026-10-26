import { AlertTriangle, Sparkles } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { isApiError } from "../../shared/api/client";
import { cn } from "../../shared/lib/cn";
import { Badge, Banner, Button, Checkbox, Dialog, FormField, Input, Select, Textarea, useToast } from "../../ui";
import { useQueryClient } from "@tanstack/react-query";
import { profileKeys, profilesApi, useDeviceTemplates, useInvalidateProfiles, useSentenceOptions } from "./api";
import { DISPOSABLE_REGIONS } from "./format";
import type { DeviceTemplate, SentenceAssembled, SentenceDraft, SentenceOptions } from "./types";

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

// ── 一次性身份 ───────────────────────────────────────────────────────────────

export function DisposableDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const toast = useToast();
  const invalidate = useInvalidateProfiles();
  const [region, setRegion] = useState("US");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const profile = await profilesApi.createDisposable(region);
      await invalidate();
      toast.show({ tone: "success", title: `已创建「${profile.name}」`, description: "用完可以在详情里焚毁。" });
      onCreated(profile.id);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      dismissible={!busy}
      size="sm"
      title="新建一次性身份"
      description="全新的独立设备画像，时区和语言按地区配好。用完可以焚毁，不进回收站。"
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button variant="primary" loading={busy} onClick={() => void create()}>
            创建
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <FormField label="地区" description="决定时区与语言。代理请在创建后按需设置。">
          <Select value={region} onChange={(event) => setRegion(event.target.value)}>
            {DISPOSABLE_REGIONS.map((item) => (
              <option key={item.code} value={item.code}>
                {item.label}（{item.code}）
              </option>
            ))}
          </Select>
        </FormField>
        {error && <Banner tone="danger" title="没有创建成功">{error}</Banner>}
      </div>
    </Dialog>
  );
}

// ── 一句话建号 ───────────────────────────────────────────────────────────────

const MAX_INTERESTS = 6;
const MAX_TARGETS = 4;

/**
 * Two steps in one dialog: type a sentence and parse it; then review and edit
 * the draft before anything is created. Closing while parsing discards it.
 */
export function SentenceDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const [sentence, setSentence] = useState("");
  const [draft, setDraft] = useState<SentenceDraft | null>(null);
  const [parsing, setParsing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const queryClient = useQueryClient();
  // Start loading the pickers' choices right away; the preview waits for them.
  const options = useSentenceOptions(true);
  const templates = useDeviceTemplates(true);

  const parse = async () => {
    const text = sentence.trim();
    if (!text || parsing) return;
    controller.current = new AbortController();
    setParsing(true);
    setError(null);
    try {
      const [result] = await Promise.all([
        profilesApi.sentenceDraft(text, controller.current.signal),
        // Missing choices are not fatal: the preview then shows the draft's own values.
        queryClient.fetchQuery({ queryKey: profileKeys.sentenceOptions, queryFn: profilesApi.sentenceOptions, staleTime: Infinity }).catch(() => null),
        queryClient.fetchQuery({ queryKey: profileKeys.deviceTemplates, queryFn: profilesApi.deviceTemplates, staleTime: Infinity }).catch(() => null),
      ]);
      if (controller.current?.signal.aborted) return;
      setDraft(result);
    } catch (err) {
      if (!controller.current?.signal.aborted) setError(message(err));
    } finally {
      setParsing(false);
    }
  };

  const close = () => {
    controller.current?.abort();
    onClose();
  };

  if (draft) {
    return (
      <SentencePreview
        sentence={sentence.trim()}
        draft={draft}
        options={options.data ?? null}
        templates={templates.data ?? []}
        onBack={() => setDraft(null)}
        onClose={close}
        onCreated={onCreated}
      />
    );
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && close()}
      title="一句话建号"
      description="用一句话描述这个号，先生成一份草案给你看，可以修改，确认后才创建。"
      footer={
        <>
          <Button onClick={close}>{parsing ? "取消解析" : "取消"}</Button>
          <Button variant="primary" icon={<Sparkles className="h-4 w-4" />} loading={parsing} disabled={!sentence.trim()} onClick={() => void parse()}>
            {parsing ? "解析中…" : "解析"}
          </Button>
        </>
      }
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void parse();
        }}
        className="flex flex-col gap-3"
      >
        <FormField label="一句话描述" error={error ?? undefined} description="例如：建个美国号，西雅图，喜欢露营摄影。写上“一次性”会勾选一次性身份。">
          <Textarea
            autoFocus
            rows={3}
            value={sentence}
            disabled={parsing}
            onChange={(event) => {
              setSentence(event.target.value);
              setError(null);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void parse();
              }
            }}
          />
        </FormField>
      </form>
    </Dialog>
  );
}

function SentencePreview({
  sentence,
  draft,
  options,
  templates,
  onBack,
  onClose,
  onCreated,
}: {
  sentence: string;
  draft: SentenceDraft;
  options: SentenceOptions | null;
  templates: DeviceTemplate[];
  onBack: () => void;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const toast = useToast();
  const invalidate = useInvalidateProfiles();
  const { spec, assembled } = draft;
  const [name, setName] = useState(assembled.name);
  const [country, setCountry] = useState(spec.country);
  const [city, setCity] = useState(spec.city ?? "");
  const [timezone, setTimezone] = useState(assembled.timezone);
  const [locale, setLocale] = useState(assembled.locale);
  const [templateId, setTemplateId] = useState(assembled.device_profile);
  const [interests, setInterests] = useState<string[]>(spec.interests);
  const [targets, setTargets] = useState<string[]>(assembled.warmup_targets);
  const [persona, setPersona] = useState(assembled.warmup_persona ?? "");
  const [notes, setNotes] = useState(assembled.notes ?? "");
  const [warmupEnabled, setWarmupEnabled] = useState(assembled.warmup_enabled);
  const [disposable, setDisposable] = useState(assembled.disposable);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cities = options?.cities[country] ?? [];
  const countryOption = options?.countries.find((item) => item.code === country);
  const timezoneOptions = useMemo(() => {
    const values = new Set<string>([timezone]);
    options?.countries.forEach((item) => item.timezone && values.add(item.timezone));
    Object.values(options?.cities ?? {}).forEach((list) => list.forEach((item) => values.add(item.timezone)));
    return [...values].sort();
  }, [options, timezone]);
  const template = templates.find((item) => item.id === templateId);

  const changeCountry = (code: string) => {
    setCountry(code);
    setCity("");
    const next = options?.countries.find((item) => item.code === code);
    if (next?.locale) setLocale(next.locale);
    if (next?.timezone) setTimezone(next.timezone);
  };

  const changeCity = (value: string) => {
    setCity(value);
    const hit = cities.find((item) => item.name === value);
    if (hit) setTimezone(hit.timezone);
  };

  const toggle = (list: string[], set: (next: string[]) => void, id: string, max: number) => {
    if (list.includes(id)) set(list.filter((item) => item !== id));
    else if (list.length < max) set([...list, id]);
  };

  const confirm = async () => {
    if (!name.trim()) {
      setError("请填写名称");
      return;
    }
    const payload: SentenceAssembled = {
      ...assembled,
      name: name.trim(),
      device_profile: templateId,
      screen_width: template?.screen_width ?? assembled.screen_width,
      screen_height: template?.screen_height ?? assembled.screen_height,
      gpu_vendor: template?.gpu_vendor ?? assembled.gpu_vendor,
      gpu_renderer: template?.gpu_renderer ?? assembled.gpu_renderer,
      hardware_concurrency: template?.hardware_concurrency ?? assembled.hardware_concurrency,
      device_memory: template?.device_memory ?? assembled.device_memory,
      timezone,
      locale: locale.trim(),
      warmup_targets: targets,
      warmup_enabled: warmupEnabled,
      warmup_persona: persona.trim() || null,
      notes: notes.trim() || null,
      disposable,
    };
    setCreating(true);
    setError(null);
    try {
      const created = await profilesApi.sentenceCreate(sentence, payload);
      await invalidate();
      toast.show({
        tone: "success",
        title: `已创建「${created.name}」`,
        description: created.warnings?.length ? created.warnings.join("；") : undefined,
      });
      onCreated(created.id);
    } catch (err) {
      setError(isApiError(err) ? err.message : message(err));
    } finally {
      setCreating(false);
    }
  };

  const chip = (active: boolean) =>
    cn(
      "rounded-full border px-2.5 py-1 text-xs transition-colors duration-fast",
      active ? "border-accent bg-accent-soft text-accent" : "border-border-strong bg-surface text-fg-2 hover:bg-surface-2",
    );

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      dismissible={!creating}
      size="lg"
      title={
        <span className="flex flex-wrap items-center gap-2">
          一句话建号预览
          <Badge tone={draft.source === "llm" ? "accent" : "neutral"}>{draft.source === "llm" ? "AI 解析" : "关键词解析"}</Badge>
        </span>
      }
      description={
        <>
          「{sentence}」
          {draft.source === "llm" && <span className="block text-xs text-fg-3">AI 解析会把这句话发送到你配置的模型接口。</span>}
        </>
      }
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-3">
          <Button variant="ghost" onClick={onBack} disabled={creating}>
            改写句子
          </Button>
          <div className="flex gap-2">
            <Button onClick={onClose} disabled={creating}>
              取消
            </Button>
            <Button variant="primary" loading={creating} onClick={() => void confirm()}>
              确认创建
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {draft.warnings.length > 0 && (
          <ul className="flex flex-col gap-1.5 rounded-md border border-warning/30 bg-warning-soft px-3 py-2">
            {draft.warnings.map((warning) => (
              <li key={warning} className="flex gap-2 text-sm text-fg">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
                {warning}
              </li>
            ))}
          </ul>
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField label="名称" required className="sm:col-span-2">
            <Input value={name} onChange={(event) => setName(event.target.value)} />
          </FormField>
          <FormField label="国家">
            <Select value={country} onChange={(event) => changeCountry(event.target.value)}>
              {(options?.countries ?? [{ code: spec.country, name: spec.country, locale: null, timezone: null }]).map((item) => (
                <option key={item.code} value={item.code}>
                  {item.name}（{item.code}）
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="城市" description="决定时区，可以不选。">
            <Select value={city} onChange={(event) => changeCity(event.target.value)}>
              <option value="">不指定</option>
              {cities.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name_zh}（{item.name}）
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="时区">
            <Select value={timezone} onChange={(event) => setTimezone(event.target.value)}>
              {timezoneOptions.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="语言区域">
            <Input mono value={locale} onChange={(event) => setLocale(event.target.value)} />
          </FormField>
          <FormField
            label="设备模板"
            className="sm:col-span-2"
            description={template ? `${template.screen_width}×${template.screen_height} · ${template.gpu_renderer}` : undefined}
          >
            <Select value={templateId} onChange={(event) => setTemplateId(event.target.value)}>
              {templates.length === 0 && <option value={templateId}>{templateId}</option>}
              {templates.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} · {item.cpu}
                </option>
              ))}
            </Select>
          </FormField>
        </div>

        <fieldset>
          <legend className="mb-1.5 text-sm font-medium text-fg">兴趣（最多 {MAX_INTERESTS} 个，只影响养号内容与人设）</legend>
          <div className="flex flex-wrap gap-1.5">
            {(options?.interests ?? []).map((item) => (
              <button key={item.id} type="button" aria-pressed={interests.includes(item.id)} className={chip(interests.includes(item.id))} onClick={() => toggle(interests, setInterests, item.id, MAX_INTERESTS)}>
                {item.name}
              </button>
            ))}
            {(options?.interests ?? []).length === 0 && <span className="text-sm text-fg-3">{interests.join("、") || "无"}</span>}
          </div>
        </fieldset>

        <fieldset>
          <legend className="mb-1.5 text-sm font-medium text-fg">养号目标（最多 {MAX_TARGETS} 个）</legend>
          <div className="flex flex-wrap items-center gap-1.5">
            {(options?.targets ?? []).map((item) => (
              <button key={item.id} type="button" aria-pressed={targets.includes(item.id)} className={chip(targets.includes(item.id))} onClick={() => toggle(targets, setTargets, item.id, MAX_TARGETS)}>
                {item.name}
              </button>
            ))}
          </div>
          <div className="mt-2">
            <Checkbox checked={warmupEnabled} onCheckedChange={setWarmupEnabled} label="建号后自动养号" />
          </div>
        </fieldset>

        <FormField label="人设" description="喂给 AI 养号剧本。">
          <Textarea rows={2} maxLength={200} value={persona} onChange={(event) => setPersona(event.target.value)} />
        </FormField>
        <FormField label="备注" description="原句会存进这里，可以删改。">
          <Textarea rows={2} value={notes} onChange={(event) => setNotes(event.target.value)} />
        </FormField>
        <Checkbox checked={disposable} onCheckedChange={setDisposable} label="一次性身份（用完可焚毁，不进回收站）" />
        {countryOption && (
          <p className="text-xs text-fg-3">
            国家默认：{countryOption.timezone ?? "—"} · {countryOption.locale ?? "—"}（城市和手动选择优先）
          </p>
        )}
        {error && <Banner tone="danger" title="没有创建成功">{error}</Banner>}
      </div>
    </Dialog>
  );
}
