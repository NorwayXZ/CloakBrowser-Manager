import { Copy, KeyRound, Plug, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  type AgentToken,
  type AgentTokenList,
  type AgentTokenScope,
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

const SCOPES: { id: AgentTokenScope; title: string; text: string }[] = [
  { id: "read", title: "read · 只读", text: "只能用只读工具" },
  { id: "control", title: "control · 可启停", text: "只读 + 启停/检测/养号/进化" },
  { id: "cdp", title: "cdp · 可操作页面", text: "再加页面控制与 CDP 代理" },
];

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
 * Where a person controls what AI agents may do: the permission mode, scoped
 * agent tokens, and the audit trail of what agents actually called.
 */
export function AgentAccessPanel() {
  const [mode, setMode] = useState<McpMode | null>(null);
  const [tokens, setTokens] = useState<AgentTokenList | null>(null);
  const [audit, setAudit] = useState<McpAuditEntry[]>([]);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<AgentTokenScope>("control");
  const [created, setCreated] = useState<{ token: string; record: AgentToken } | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const fail = (err: unknown, fallback: string) =>
    setNotice({ tone: "error", text: err instanceof Error ? err.message : fallback });

  const load = useCallback(async () => {
    try {
      const [modeResult, tokenResult, auditResult] = await Promise.all([
        api.getMcpMode(),
        api.listAgentTokens(),
        api.listMcpAudit(30),
      ]);
      setMode(modeResult.mode);
      setTokens(tokenResult);
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

  const createToken = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    setNotice(null);
    try {
      const result = await api.createAgentToken(trimmed, scope);
      setCreated({ token: result.token, record: result.record });
      setName("");
      setTokens(await api.listAgentTokens());
    } catch (err) {
      fail(err, "创建 token 失败");
    } finally {
      setBusy(false);
    }
  };

  const revokeToken = async (token: AgentToken) => {
    if (!window.confirm(`撤销「${token.name}」？使用它的 agent 会立刻失去访问权限。`)) return;
    setBusy(true);
    setNotice(null);
    try {
      await api.revokeAgentToken(token.id);
      if (created?.record.id === token.id) setCreated(null);
      setTokens(await api.listAgentTokens());
    } catch (err) {
      fail(err, "撤销失败");
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
        <div className="flex items-start gap-3 border-b border-border px-5 py-3">
          <KeyRound className="mt-0.5 h-4 w-4 text-slate-500" />
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Agent token</h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              给 agent 单独签发的访问令牌，权限比管理员令牌小，并且只能使用已脱敏的 agent 接口，读不到 Cookie 和代理账密。
            </p>
          </div>
        </div>

        {tokens && !tokens.enforced && (
          <div className="border-b border-amber-200 bg-amber-50 px-5 py-2 text-xs leading-5 text-amber-700">
            这个 Manager 没有开启登录鉴权，token 不会被检查：本机任何进程本来就等同管理员。需要限制 agent 时，请先在「账号设置」里设置管理员密码，或用 AUTH_TOKEN 启动。
          </div>
        )}

        {created && (
          <div className="border-b border-emerald-200 bg-emerald-50 px-5 py-3 text-xs leading-5 text-emerald-800">
            <div>「{created.record.name}」的 token 只显示这一次，请立刻保存：</div>
            <div className="mt-1.5">
              <CopyLine label="token" value={created.token} />
            </div>
            <button type="button" className="mt-1.5 underline" onClick={() => setCreated(null)}>
              我已保存，关闭
            </button>
          </div>
        )}

        <div className="flex flex-wrap items-end gap-3 border-b border-border p-5">
          <div>
            <label className="block text-xs text-slate-500" htmlFor="agent-token-name">
              名称
            </label>
            <input
              id="agent-token-name"
              className="input mt-1 w-56"
              value={name}
              placeholder="如：codex 笔记本"
              maxLength={80}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500" htmlFor="agent-token-scope">
              权限范围
            </label>
            <select
              id="agent-token-scope"
              className="input mt-1 w-56"
              value={scope}
              onChange={(e) => setScope(e.target.value as AgentTokenScope)}
            >
              {SCOPES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="btn-primary h-9 px-4"
            disabled={busy || !name.trim()}
            onClick={() => void createToken()}
          >
            签发 token
          </button>
        </div>

        {tokens && tokens.tokens.length === 0 ? (
          <div className="px-5 py-4 text-xs text-slate-500">还没有签发过 token。</div>
        ) : (
          <ul className="divide-y divide-border">
            {tokens?.tokens.map((token) => (
              <li key={token.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
                <span className="min-w-0 flex-1 truncate font-medium text-slate-900">{token.name}</span>
                <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600">{token.scope}</span>
                <span className="text-xs text-slate-500">{formatTime(token.created_at)}</span>
                <button
                  type="button"
                  className="p-1 text-slate-400 hover:text-red-600"
                  title="撤销"
                  aria-label={`撤销 ${token.name}`}
                  disabled={busy}
                  onClick={() => void revokeToken(token)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
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
