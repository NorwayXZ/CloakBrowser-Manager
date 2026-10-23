import { AlertTriangle, Sparkles, X } from "lucide-react";
import { useMemo, useState } from "react";
import type {
  DeviceTemplateSummary,
  SentenceAssembled,
  SentenceDraftResult,
  SentenceOptions,
} from "../lib/api";

interface SentenceProfileDialogProps {
  sentence: string;
  draft: SentenceDraftResult;
  options: SentenceOptions | null;
  templates: DeviceTemplateSummary[];
  confirming: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: (assembled: SentenceAssembled) => void;
}

const MAX_INTERESTS = 6;
const MAX_TARGETS = 4;

export function SentenceProfileDialog({
  sentence,
  draft,
  options,
  templates,
  confirming,
  error,
  onCancel,
  onConfirm,
}: SentenceProfileDialogProps) {
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

  const cities = useMemo(() => options?.cities[country] ?? [], [options, country]);
  const countryOption = useMemo(
    () => options?.countries.find((item) => item.code === country),
    [options, country],
  );
  const timezoneOptions = useMemo(() => {
    const values = new Set<string>([timezone]);
    for (const item of options?.countries ?? []) {
      if (item.timezone) values.add(item.timezone);
    }
    for (const list of Object.values(options?.cities ?? {})) {
      for (const item of list) values.add(item.timezone);
    }
    return [...values].sort();
  }, [options, timezone]);
  const selectedTemplate = useMemo(
    () => templates.find((item) => item.id === templateId),
    [templates, templateId],
  );

  const handleCountryChange = (code: string) => {
    setCountry(code);
    setCity("");
    const next = options?.countries.find((item) => item.code === code);
    if (next?.locale) setLocale(next.locale);
    if (next?.timezone) setTimezone(next.timezone);
  };

  const handleCityChange = (value: string) => {
    setCity(value);
    const hit = cities.find((item) => item.name === value);
    if (hit) setTimezone(hit.timezone);
  };

  const toggleInterest = (id: string) => {
    setInterests((current) => {
      if (current.includes(id)) return current.filter((item) => item !== id);
      if (current.length >= MAX_INTERESTS) return current;
      return [...current, id];
    });
  };

  const toggleTarget = (id: string) => {
    setTargets((current) => {
      if (current.includes(id)) return current.filter((item) => item !== id);
      if (current.length >= MAX_TARGETS) return current;
      return [...current, id];
    });
  };

  const handleConfirm = () => {
    const tpl = selectedTemplate;
    onConfirm({
      ...assembled,
      name: name.trim(),
      device_profile: templateId,
      screen_width: tpl?.screen_width ?? assembled.screen_width,
      screen_height: tpl?.screen_height ?? assembled.screen_height,
      gpu_vendor: tpl?.gpu_vendor ?? assembled.gpu_vendor,
      gpu_renderer: tpl?.gpu_renderer ?? assembled.gpu_renderer,
      hardware_concurrency: tpl?.hardware_concurrency ?? assembled.hardware_concurrency,
      device_memory: tpl?.device_memory ?? assembled.device_memory,
      timezone,
      locale: locale.trim(),
      warmup_targets: targets,
      warmup_enabled: warmupEnabled,
      warmup_persona: persona.trim() || null,
      notes: notes.trim() || null,
      disposable,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 px-4 py-6">
      <section className="flex max-h-[min(820px,calc(100vh-48px))] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-border bg-white shadow-2xl">
        <header className="flex items-start justify-between border-b border-border px-5 py-4">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-violet-50 text-violet-700">
              <Sparkles className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-semibold text-slate-900">一句话建号预览</h2>
                <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${draft.source === "llm" ? "bg-violet-50 text-violet-700" : "bg-slate-100 text-slate-600"}`}>
                  {draft.source === "llm" ? "AI 解析" : "关键词解析"}
                </span>
              </div>
              <p className="mt-1 break-words text-xs leading-5 text-slate-500">「{sentence}」</p>
              {draft.source === "llm" && (
                <p className="mt-0.5 text-xs text-slate-400">AI 解析会将这句话发送到你配置的模型接口。</p>
              )}
            </div>
          </div>
          <button
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            onClick={onCancel}
            title="放弃这份草案"
            aria-label="关闭预览"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto bg-slate-50 p-5">
          {draft.warnings.length > 0 && (
            <ul className="space-y-1.5 rounded-md border border-amber-200 bg-amber-50 px-3 py-2.5">
              {draft.warnings.map((warning) => (
                <li key={warning} className="flex gap-2 text-xs leading-5 text-amber-800">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>{warning}</span>
                </li>
              ))}
            </ul>
          )}

          <div className="rounded-md border border-border bg-white p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block sm:col-span-2">
                <span className="mb-1 block text-xs font-medium text-slate-500">名称</span>
                <input
                  className="input h-9 w-full text-sm"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  aria-label="画像名称"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">国家</span>
                <select
                  className="input h-9 w-full text-sm"
                  value={country}
                  onChange={(event) => handleCountryChange(event.target.value)}
                  aria-label="国家"
                >
                  {(options?.countries ?? [{ code: spec.country, name: spec.country, locale: null, timezone: null }]).map((item) => (
                    <option key={item.code} value={item.code}>{item.name}（{item.code}）</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">城市（决定时区，可不选）</span>
                <select
                  className="input h-9 w-full text-sm"
                  value={city}
                  onChange={(event) => handleCityChange(event.target.value)}
                  aria-label="城市"
                >
                  <option value="">不指定</option>
                  {cities.map((item) => (
                    <option key={item.name} value={item.name}>{item.name_zh}（{item.name}）</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">时区</span>
                <select
                  className="input h-9 w-full text-sm"
                  value={timezone}
                  onChange={(event) => setTimezone(event.target.value)}
                  aria-label="时区"
                >
                  {timezoneOptions.map((value) => (
                    <option key={value} value={value}>{value}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">语言区域</span>
                <input
                  className="input h-9 w-full text-sm"
                  value={locale}
                  onChange={(event) => setLocale(event.target.value)}
                  aria-label="语言区域"
                />
              </label>
              <label className="block sm:col-span-2">
                <span className="mb-1 block text-xs font-medium text-slate-500">设备模板</span>
                <select
                  className="input h-9 w-full text-sm"
                  value={templateId}
                  onChange={(event) => setTemplateId(event.target.value)}
                  aria-label="设备模板"
                >
                  {templates.length === 0 && (
                    <option value={templateId}>{templateId}</option>
                  )}
                  {templates.map((item) => (
                    <option key={item.id} value={item.id}>{item.name} · {item.cpu}</option>
                  ))}
                </select>
                {selectedTemplate && (
                  <span className="mt-1 block truncate text-xs text-slate-400">
                    {selectedTemplate.screen_width}×{selectedTemplate.screen_height} · {selectedTemplate.gpu_renderer}
                  </span>
                )}
              </label>
            </div>

            <div className="mt-4">
              <span className="mb-1.5 block text-xs font-medium text-slate-500">兴趣（最多 {MAX_INTERESTS} 个，只影响养号内容与人设）</span>
              <div className="flex flex-wrap gap-1.5">
                {(options?.interests ?? []).map((item) => {
                  const active = interests.includes(item.id);
                  return (
                    <button
                      key={item.id}
                      type="button"
                      aria-pressed={active}
                      onClick={() => toggleInterest(item.id)}
                      className={`rounded-full border px-2.5 py-1 text-xs ${active ? "border-violet-300 bg-violet-50 text-violet-700" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"}`}
                    >
                      {item.name}
                    </button>
                  );
                })}
                {(options?.interests ?? []).length === 0 && (
                  <span className="text-xs text-slate-400">{interests.join("、") || "无"}</span>
                )}
              </div>
            </div>

            <div className="mt-4">
              <span className="mb-1.5 block text-xs font-medium text-slate-500">养号目标（最多 {MAX_TARGETS} 个）</span>
              <div className="flex flex-wrap items-center gap-1.5">
                {(options?.targets ?? []).map((item) => {
                  const active = targets.includes(item.id);
                  return (
                    <button
                      key={item.id}
                      type="button"
                      aria-pressed={active}
                      onClick={() => toggleTarget(item.id)}
                      className={`rounded-full border px-2.5 py-1 text-xs ${active ? "border-blue-300 bg-blue-50 text-blue-700" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"}`}
                    >
                      {item.name}
                    </button>
                  );
                })}
                <label className="ml-2 flex items-center gap-1.5 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-slate-300"
                    checked={warmupEnabled}
                    onChange={(event) => setWarmupEnabled(event.target.checked)}
                    aria-label="开启养号"
                  />
                  建号后自动养号
                </label>
              </div>
            </div>

            <label className="mt-4 block">
              <span className="mb-1 block text-xs font-medium text-slate-500">人设（喂给 AI 养号剧本）</span>
              <textarea
                className="input w-full text-sm"
                rows={2}
                maxLength={200}
                value={persona}
                onChange={(event) => setPersona(event.target.value)}
                aria-label="人设"
              />
            </label>
            <label className="mt-3 block">
              <span className="mb-1 block text-xs font-medium text-slate-500">备注（原句会存进这里，可删改）</span>
              <textarea
                className="input w-full text-sm"
                rows={2}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                aria-label="备注"
              />
            </label>
            <label className="mt-3 flex items-center gap-1.5 text-xs text-slate-600">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-300"
                checked={disposable}
                onChange={(event) => setDisposable(event.target.checked)}
                aria-label="一次性画像"
              />
              一次性画像（用完可焚毁，不进回收站）
            </label>
            {countryOption && (
              <p className="mt-3 text-xs text-slate-400">
                国家默认：{countryOption.timezone ?? "—"} · {countryOption.locale ?? "—"}（城市与手动选择优先）
              </p>
            )}
          </div>
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-border bg-white px-5 py-4">
          <div className="min-w-0 text-xs text-red-600">{error ?? ""}</div>
          <div className="flex shrink-0 gap-2">
            <button className="btn-secondary px-4" onClick={onCancel} disabled={confirming}>取消</button>
            <button
              className="btn-primary px-4 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={confirming}
              onClick={handleConfirm}
            >
              {confirming ? "创建中..." : "确认创建"}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
