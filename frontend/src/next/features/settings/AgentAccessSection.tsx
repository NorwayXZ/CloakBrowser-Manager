import { useQueryClient } from "@tanstack/react-query";
import { KeyRound, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { cn } from "../../shared/lib/cn";
import { Badge, Banner, Button, CopyField, ErrorState, FormField, IconButton, Input, Section, Select, Skeleton, Table, TD, TH, THead, TR, useConfirm, useToast } from "../../ui";
import {
  message,
  settingsApi,
  settingsKeys,
  useAgentTokens,
  useMcpAudit,
  useMcpMode,
  type AgentToken,
  type AgentTokenCreated,
  type AgentTokenScope,
  type McpMode,
} from "./api";

const MODES: { id: McpMode; title: string; text: string }[] = [
  { id: "off", title: "关闭", text: "拒绝所有 AI agent 请求。" },
  { id: "read-only", title: "只读（默认）", text: "agent 只能查看环境、预检、检测报告和各种状态，不能启动或关闭浏览器。" },
  { id: "full", title: "可启停", text: "只读 + 启动/关闭环境、跑指纹检测、养号和进化实验。只能以手动模式打开，不能操作页面。" },
  { id: "automation", title: "可操作页面", text: "可启停 + 打开网页、读取页面、点击、输入、截图，并交出 CDP 端点。" },
];

const SCOPES: { id: AgentTokenScope; title: string }[] = [
  { id: "read", title: "read · 只读" },
  { id: "control", title: "control · 可启停" },
  { id: "cdp", title: "cdp · 可操作页面" },
];

function formatTime(value: string | number): string {
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** 设置 › AI 接入: what AI agents may do, the addresses they connect to, their tokens and what they did. */
export function AgentAccessSection() {
  return (
    <div className="flex flex-col gap-6">
      <PermissionSection />
      <AddressSection />
      <TokenSection />
      <AuditSection />
    </div>
  );
}

function PermissionSection() {
  const mode = useMcpMode();
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const title = "AI agent 权限";

  const change = async (next: McpMode) => {
    if (next === mode.data?.mode) return;
    if (next === "automation") {
      const ok = await confirm({
        title: "允许 AI 操作页面？",
        description: "「可操作页面」会让 AI agent 接触环境里的登录状态：页面控制和 CDP 都能读到该环境的全部 Cookie。",
        details: "只在需要 agent 操作页面时开启，用完改回「可启停」或「只读」。",
        confirmLabel: "确定开启",
        danger: true,
      });
      if (!ok) return;
    }
    setSaving(true);
    setError(null);
    try {
      const saved = await settingsApi.saveMcpMode(next);
      queryClient.setQueryData(settingsKeys.mcp, saved);
      toast.show({ tone: "success", title: "AI agent 权限已保存", description: "已连接的 MCP 客户端需要重启才会看到新的工具列表。" });
    } catch (err) {
      setError(message(err));
    } finally {
      setSaving(false);
    }
  };

  if (mode.isPending) {
    return (
      <Section id="agent-permission" title={title}>
        <Skeleton className="h-32 w-full" />
      </Section>
    );
  }
  if (mode.isError) {
    return (
      <Section id="agent-permission" title={title}>
        <ErrorState title="AI 接入设置没有读出来" message={mode.error.message} onRetry={() => void mode.refetch()} retrying={mode.isFetching} />
      </Section>
    );
  }
  const current = mode.data.mode;
  return (
    <Section
      id="agent-permission"
      title={title}
      description="决定 Codex、Claude、DeepSeek harness 等 AI agent 能对环境做什么。你随时可以在「环境」列表里点「接管」把环境拿回来。"
    >
      <fieldset className="flex flex-col gap-4" disabled={saving}>
        <legend className="sr-only">AI agent 权限</legend>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {MODES.map((item) => {
            const checked = current === item.id;
            return (
              <label
                key={item.id}
                className={cn(
                  "flex cursor-pointer gap-2.5 rounded-md border p-3 transition-colors duration-fast",
                  "has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
                  checked ? "border-accent bg-accent-soft" : "border-border bg-surface hover:bg-surface-2",
                  saving && "cursor-not-allowed opacity-70",
                )}
              >
                <input
                  type="radio"
                  name="mcp-mode"
                  value={item.id}
                  checked={checked}
                  onChange={() => void change(item.id)}
                  aria-label={item.title}
                  aria-describedby={`mcp-mode-${item.id}`}
                  className="mt-0.5 accent-accent"
                />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-fg">{item.title}</span>
                  <span id={`mcp-mode-${item.id}`} className="mt-0.5 block text-xs text-fg-2">
                    {item.text}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
        {current === "automation" && (
          <Banner tone="warning">当前允许 AI 操作页面，包括读取环境的登录状态。不用时请改回「可启停」或「只读」。</Banner>
        )}
        {error && <Banner tone="danger" title="没有保存">{error}</Banner>}
      </fieldset>
    </Section>
  );
}

function AddressSection() {
  const origin = window.location.origin;
  const rows: { label: string; value: string }[] = [
    { label: "HTTP MCP", value: `${origin}/api/agent/mcp` },
    { label: "工具接口", value: `${origin}/api/agent/tools?format=openai` },
    { label: "使用指南", value: `${origin}/api/agent/guide` },
    { label: "stdio MCP", value: "python -m backend.mcp_server" },
    { label: "命令行", value: "./bin/cloak open <环境名称>" },
  ];
  return (
    <Section id="agent-addresses" title="接入地址" description="Codex、Claude Desktop 等客户端的具体配置写法见 docs/AGENT.md 和 docs/MCP.md。">
      <dl className="grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-[6rem_minmax(0,1fr)] sm:items-center">
        {rows.map((row) => (
          <div key={row.label} className="contents">
            <dt className="text-xs text-fg-3">{row.label}</dt>
            <dd className="m-0 min-w-0">
              <CopyField label={row.label} value={row.value} />
            </dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}

function TokenSection() {
  const tokens = useAgentTokens();
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();
  const [name, setName] = useState("");
  const [scope, setScope] = useState<AgentTokenScope>("control");
  const [created, setCreated] = useState<AgentTokenCreated | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: settingsKeys.agentTokens });

  const create = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      const result = await settingsApi.createAgentToken(trimmed, scope);
      setCreated(result);
      setName("");
      await refresh();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (token: AgentToken) => {
    const ok = await confirm({
      title: `撤销「${token.name}」？`,
      description: "使用它的 agent 会立刻失去访问权限。",
      confirmLabel: "撤销",
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    setError(null);
    try {
      await settingsApi.revokeAgentToken(token.id);
      if (created?.record.id === token.id) setCreated(null);
      await refresh();
      toast.show({ tone: "success", title: `已撤销「${token.name}」` });
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  const title = "Agent token";
  const description = "给 agent 单独签发的访问令牌，权限比管理员令牌小，并且只能使用已脱敏的 agent 接口，读不到 Cookie 和代理账密。";
  if (tokens.isPending) {
    return (
      <Section id="agent-tokens" title={title} description={description}>
        <Skeleton className="h-24 w-full" />
      </Section>
    );
  }
  if (tokens.isError) {
    return (
      <Section id="agent-tokens" title={title} description={description}>
        <ErrorState title="token 列表没有读出来" message={tokens.error.message} onRetry={() => void tokens.refetch()} retrying={tokens.isFetching} />
      </Section>
    );
  }

  const list = tokens.data;
  return (
    <Section id="agent-tokens" title={title} description={description} actions={<KeyRound className="h-4 w-4 text-fg-3" aria-hidden />}>
      <div className="flex flex-col gap-4">
        {!list.enforced && (
          <Banner tone="warning">
            这个 Manager 没有开启登录鉴权，token 不会被检查：本机任何进程本来就等同管理员。需要限制 agent 时，请先在「账号与安全」里设置管理员密码，或用 AUTH_TOKEN 启动。
          </Banner>
        )}
        {created && (
          <Banner
            tone="success"
            title={`「${created.record.name}」的 token 只显示这一次，请立刻保存`}
            action={
              <Button size="sm" onClick={() => setCreated(null)}>
                我已保存，关闭
              </Button>
            }
          >
            <CopyField label="token" value={created.token} className="mt-1.5" />
          </Banner>
        )}
        <form
          className="flex flex-wrap items-start gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            void create();
          }}
        >
          <FormField label="名称" className="w-full sm:w-56">
            <Input value={name} placeholder="如：codex 笔记本" maxLength={80} onChange={(event) => setName(event.target.value)} />
          </FormField>
          <FormField label="权限范围" className="w-full sm:w-52">
            <Select value={scope} onChange={(event) => setScope(event.target.value as AgentTokenScope)}>
              {SCOPES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </Select>
          </FormField>
          <Button type="submit" variant="primary" className="sm:mt-6" loading={busy} disabled={busy || !name.trim()}>
            签发 token
          </Button>
        </form>
        {error && <Banner tone="danger" title="操作没有成功">{error}</Banner>}
        {list.tokens.length === 0 ? (
          <p className="text-sm text-fg-2">还没有签发过 token。</p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {list.tokens.map((token) => (
              <li key={token.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                <span className="min-w-0 flex-1 truncate font-medium text-fg" title={token.name}>
                  {token.name}
                </span>
                <Badge className="font-mono">{token.scope}</Badge>
                <span className="shrink-0 text-xs text-fg-3">{formatTime(token.created_at)}</span>
                <IconButton
                  size="sm"
                  variant="danger-ghost"
                  label={`撤销 ${token.name}`}
                  icon={<Trash2 className="h-3.5 w-3.5" />}
                  disabled={busy}
                  onClick={() => void revoke(token)}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </Section>
  );
}

function AuditSection() {
  const audit = useMcpAudit();
  const title = "最近的 agent 操作";
  const refresh = (
    <Button size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={audit.isFetching} onClick={() => void audit.refetch()}>
      刷新
    </Button>
  );
  if (audit.isPending) {
    return (
      <Section id="agent-audit" title={title}>
        <Skeleton className="h-24 w-full" />
      </Section>
    );
  }
  if (audit.isError) {
    return (
      <Section id="agent-audit" title={title}>
        <ErrorState title="操作记录没有读出来" message={audit.error.message} onRetry={() => void audit.refetch()} retrying={audit.isFetching} />
      </Section>
    );
  }
  return (
    <Section id="agent-audit" title={title} actions={refresh}>
      {audit.data.length === 0 ? (
        <p className="text-sm text-fg-2">还没有 agent 调用记录。</p>
      ) : (
        <Table label="agent 操作记录" minWidth={520}>
          <colgroup>
            <col className="w-36" />
            <col className="w-24" />
            <col />
            <col className="w-28" />
            <col className="w-20" />
          </colgroup>
          <THead>
            <tr>
              <TH>时间</TH>
              <TH>客户端</TH>
              <TH>工具</TH>
              <TH>结果</TH>
              <TH className="text-right">耗时</TH>
            </tr>
          </THead>
          <tbody>
            {audit.data.map((entry) => (
              <TR key={entry.id}>
                <TD className="whitespace-nowrap text-xs text-fg-2">{formatTime(entry.ts)}</TD>
                <TD className="truncate">{entry.client_name ?? "—"}</TD>
                <TD className="truncate font-mono text-xs" title={entry.tool}>
                  {entry.tool}
                </TD>
                <TD className={cn("truncate text-xs", entry.ok ? "text-success" : "text-danger")}>{entry.ok ? "成功" : (entry.reason ?? "失败")}</TD>
                <TD className="tabular text-right text-xs text-fg-2">{entry.duration_ms != null ? `${entry.duration_ms} ms` : "—"}</TD>
              </TR>
            ))}
          </tbody>
        </Table>
      )}
    </Section>
  );
}
