import { Bot, Save } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type LlmSettings } from "../lib/api";

type Notice = { tone: "success" | "error"; text: string };

export function LlmSettingsCard() {
  const [status, setStatus] = useState<LlmSettings | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const apply = useCallback((next: LlmSettings) => {
    setStatus(next);
    setBaseUrl(next.base_url ?? "");
    setModel(next.model ?? "");
    setApiKey("");
  }, []);

  const load = useCallback(async () => {
    try {
      apply(await api.getLlmSettings());
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "读取 LLM 设置失败" });
    }
  }, [apply]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!status) return null;

  const changed =
    baseUrl !== (status.base_url ?? "") || model !== (status.model ?? "") || apiKey.trim() !== "";

  const handleSave = async () => {
    setBusy(true);
    setNotice(null);
    try {
      apply(
        await api.updateLlmSettings({
          base_url: baseUrl.trim(),
          model: model.trim(),
          api_key: apiKey.trim() ? apiKey : null,
        }),
      );
      setNotice({ tone: "success", text: "LLM 设置已保存。" });
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "保存失败" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-4xl overflow-hidden rounded-md border border-border bg-white">
      <div className="flex items-start gap-3 border-b border-border px-5 py-4">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-sky-50 text-sky-700">
          <Bot className="h-4 w-4" />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-slate-900">LLM 接口（AI 功能共用）</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            自备密钥（BYOK）：填写任意 OpenAI 兼容接口（如 OpenAI、DeepSeek、本地 Ollama 的兼容端点）。
            密钥加密保存在本机，永不回显；没有配置时所有 AI 入口自动隐藏，其余功能不受影响。
            目前用于「AI 养号编排」：按画像人格离线生成一周的浏览剧本，人工批准后才生效。
          </p>
        </div>
      </div>

      <div className="grid max-w-3xl grid-cols-[120px_minmax(0,1fr)] items-start gap-x-5 gap-y-4 p-5">
        <label className="pt-2 text-right text-sm font-medium text-slate-600">接口地址</label>
        <div>
          <input
            className="input w-full max-w-xl font-mono text-xs"
            aria-label="LLM 接口地址"
            value={baseUrl}
            placeholder="https://api.openai.com/v1"
            onChange={(e) => setBaseUrl(e.target.value)}
          />
          <div className="mt-1 text-xs leading-5 text-slate-500">
            填到版本根路径即可，Manager 会在其后拼接 /chat/completions。
          </div>
        </div>

        <label className="pt-2 text-right text-sm font-medium text-slate-600">模型</label>
        <input
          className="input w-full max-w-xl font-mono text-xs"
          aria-label="LLM 模型"
          value={model}
          placeholder="gpt-4o-mini"
          onChange={(e) => setModel(e.target.value)}
        />

        <label className="pt-2 text-right text-sm font-medium text-slate-600">API 密钥</label>
        <div>
          <input
            className="input w-full max-w-xl font-mono text-xs"
            type="password"
            aria-label="LLM API 密钥"
            value={apiKey}
            placeholder={status.has_api_key ? "已配置（留空表示不修改）" : "sk-…"}
            autoComplete="new-password"
            onChange={(e) => setApiKey(e.target.value)}
          />
          <div className="mt-1 text-xs leading-5 text-slate-500">
            密钥只写不读：保存后这里不会再显示它。
          </div>
        </div>

        <label className="text-right text-sm font-medium text-slate-600">状态</label>
        <div className="text-xs leading-5 text-slate-600">
          {status.configured ? (
            <span className="text-emerald-700">已配置，AI 功能可用。</span>
          ) : (
            <span>未配置完整（接口地址、模型、密钥缺一不可），AI 入口处于隐藏状态。</span>
          )}
        </div>

        <div />
        <div className="flex flex-wrap gap-2">
          <button
            className="btn-primary flex items-center gap-1.5 px-4 disabled:opacity-60"
            disabled={busy || !changed}
            onClick={() => void handleSave()}
          >
            <Save className="h-4 w-4" />
            <span>{busy ? "保存中..." : "保存设置"}</span>
          </button>
        </div>
      </div>

      {notice && (
        <div
          className={`whitespace-pre-line break-all border-t px-5 py-3 text-sm ${
            notice.tone === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-red-200 bg-red-50 text-red-800"
          }`}
        >
          {notice.text}
        </div>
      )}
    </div>
  );
}
