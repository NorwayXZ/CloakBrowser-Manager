import { Copy, Plug, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  type McpAuditEntry,
  type McpMode,
} from "../lib/api";

type Notice = { tone: "success" | "error"; text: string };

const MODES: { id: McpMode; title: string; text: string }[] = [
  { id: "off", title: "关闭", text: "拒绝所有 AI agent 请求。" },
  { id: "read-only", title: "只读（默认）", text: "agent 只能查看画像、预检、检测报告和各种状态，不能启动或关闭浏览器。" },
  { id: "full", title: "可启停", text: "只读 + 启动/关闭画像、跑指纹检测、养号和进化实验。只能以手动模式打开，不能操作页面。" },
  {
    id: "automation",
    title: "可操作页面",
    text: "可启停 + 打开网页、读取页面、点击、输入、截图，并交出 CDP 端点。",
  },
];

const AUTOMATION_WARNING =
  "「可操作页面」会让 AI agent 接触画像里的登录状态：页面控制和 CDP 都能读到该画像的全部 Cookie。\n只在需要 agent 操作页面时开启，用完改回「可启停」或「只读」。\n\n确定开启吗？";

function formatTime(value: string | number): string {
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function CopyLine({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard
      ?.writeText(value)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => undefined);
  };
  return (
    <div className="flex items-center gap-2">
      <span className="w-24 shrink-0 text-xs text-slate-500">{label}</span>
      <code className="min-w-0 flex-1 truncate rounded bg-slate-50 px-2 py-1 font-mono text-xs text-slate-700">
        {value}
      </code>
      <button
        type="button"
        className={`shrink-0 p-1 ${copied ? "text-emerald-600" : "text-slate-400 hover:text-slate-700"}`}
        title={copied ? "已复制" : "复制"}
        aria-label={`复制${label}`}
        onClick={copy}
      >
        <Copy className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

/**
 * Where a person controls what AI agents may do: the permission mode and the
 * audit trail of what agents actually called.
 */
export function AgentAccessPanel() {
  const [mode, setMode] = useState<McpMode | null>(null);
  const [audit, setAudit] = useState<McpAuditEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const fail = (err: unknown, fallback: string) =>
    setNotice({ tone: "error", text: err instanceof Error ? err.message : fallback });

  const load = useCallback(async () => {
    try {
      const [modeResult, auditResult] = await Promise.all([api.getMcpMode(), api.listMcpAudit(30)]);
      setMode(modeResult.mode);
      setAudit(auditResult);
    } catch (err) {
      fail(err, "读取 AI 接入设置失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const changeMode = async (next: McpMode) => {
    if (next === mode) return;
    if (next === "automation" && !window.confirm(AUTOMATION_WARNING)) return;
    setBusy(true);
    setNotice(null);
    try {
      const result = await api.setMcpMode(next);
      setMode(result.mode);
      setNotice({ tone: "success", text: "已保存。已连接的 MCP 客户端需要重启才会看到新的工具列表。" });
    } catch (err) {
      fail(err, "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const origin = window.location.origin;

  return (
    <div className="max-w-4xl space-y-4">
      {notice && (
        <div
          className={`rounded-md border px-4 py-2 text-sm ${
            notice.tone === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-red-200 bg-red-50 text-red-700"
          }`}
          role="status"
        >
          {notice.text}
        </div>
      )}

      <section className="overflow-hidden rounded-md border border-border bg-white">
        <div className="flex items-start gap-3 border-b border-border px-5 py-4">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-sky-50 text-sky-700">
            <Plug className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-slate-900">AI agent 权限</h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              决定 Codex、Claude、DeepSeek harness 等 AI agent 能对画像做什么。用户随时可以在「环境管理」里点「接管」把画像拿回来。
            </p>
          </div>
        </div>
        <div className="grid gap-2 p-5 sm:grid-cols-2">
          {MODES.map((item) => (
            <label
              key={item.id}
              className={`flex cursor-pointer gap-3 rounded-md border p-3 text-sm ${
                mode === item.id ? "border-blue-500 bg-blue-50" : "border-border hover:bg-slate-50"
              }`}
            >
              <input
                type="radio"
                name="mcp-mode"
                aria-label={item.title}
                className="mt-1"
                checked={mode === item.id}
                disabled={busy || mode === null}
                onChange={() => void changeMode(item.id)}
              />
              <span>
                <span className="block font-medium text-slate-900">{item.title}</span>
                <span className="mt-0.5 block text-xs leading-5 text-slate-500">{item.text}</span>
              </span>
            </label>
          ))}
        </div>
        {mode === "automation" && (
          <div className="border-t border-amber-200 bg-amber-50 px-5 py-2 text-xs leading-5 text-amber-700">
            当前允许 AI 操作页面，包括读取画像的登录状态。不用时请改回「可启停」或「只读」。
          </div>
        )}
      </section>

      <section className="overflow-hidden rounded-md border border-border bg-white">
        <div className="border-b border-border px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-900">接入地址</h2>
        </div>
        <div className="space-y-2 p-5">
          <CopyLine label="HTTP MCP" value={`${origin}/api/agent/mcp`} />
          <CopyLine label="工具接口" value={`${origin}/api/agent/tools?format=openai`} />
          <CopyLine label="使用指南" value={`${origin}/api/agent/guide`} />
          <CopyLine label="stdio MCP" value="python -m backend.mcp_server" />
          <CopyLine label="命令行" value="./bin/cloak open <画像名称>" />
          <p className="pt-1 text-xs leading-5 text-slate-500">
            Codex、Claude Desktop 等客户端的具体配置写法见 docs/AGENT.md。
          </p>
        </div>
      </section>

      <section className="overflow-hidden rounded-md border border-border bg-white">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-900">最近的 agent 操作</h2>
          <button
            type="button"
            className="btn-secondary flex h-8 items-center gap-1.5 px-2.5 text-xs"
            onClick={() => void load()}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            刷新
          </button>
        </div>
        {audit.length === 0 ? (
          <div className="px-5 py-4 text-xs text-slate-500">还没有 agent 调用记录。</div>
        ) : (
          <table className="w-full text-left text-xs">
            <thead className="text-slate-500">
              <tr>
                <th className="px-5 py-2 font-medium">时间</th>
                <th className="px-3 py-2 font-medium">客户端</th>
                <th className="px-3 py-2 font-medium">工具</th>
                <th className="px-3 py-2 font-medium">结果</th>
                <th className="px-3 py-2 font-medium">耗时</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {audit.map((entry) => (
                <tr key={entry.id}>
                  <td className="whitespace-nowrap px-5 py-2 text-slate-500">{formatTime(entry.ts)}</td>
                  <td className="px-3 py-2">{entry.client_name ?? "—"}</td>
                  <td className="px-3 py-2 font-mono">{entry.tool}</td>
                  <td className={`px-3 py-2 ${entry.ok ? "text-emerald-600" : "text-red-600"}`}>
                    {entry.ok ? "成功" : entry.reason ?? "失败"}
                  </td>
                  <td className="px-3 py-2 text-slate-500">
                    {entry.duration_ms != null ? `${entry.duration_ms} ms` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
