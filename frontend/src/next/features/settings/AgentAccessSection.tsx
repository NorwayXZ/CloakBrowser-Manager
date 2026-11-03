import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { cn } from "../../shared/lib/cn";
import { Banner, Button, CodeBlock, CopyField, ErrorState, Section, Skeleton, Table, TD, TH, THead, Tabs, TR, useToast } from "../../ui";
import {
  message,
  settingsApi,
  settingsKeys,
  useAgentTokens,
  useMcpAudit,
  useMcpMode,
  type McpMode,
} from "./api";

const MODES: { id: McpMode; title: string; text: string }[] = [
  { id: "off", title: "关闭", text: "拒绝所有 AI agent 请求。" },
  { id: "read-only", title: "只读", text: "agent 只能查看环境、预检、检测报告和各种状态，不能启动或关闭浏览器。" },
  { id: "full", title: "可启停", text: "只读 + 新建/修改环境、启动/关闭、跑指纹检测、养号和进化实验。不能操作页面，不能删除。" },
  { id: "automation", title: "全部开放（默认）", text: "没有限制：操作页面、读写 Cookie、执行脚本、删除环境、批准养号和进化提案，并交出 CDP 端点。" },
];

function formatTime(value: string | number): string {
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** 设置 › AI 接入: the addresses AI agents connect to, what they may do, and what they did. */
export function AgentAccessSection() {
  return (
    <div className="flex flex-col gap-6">
      <ConnectSection />
      <PermissionSection />
      <AuditSection />
    </div>
  );
}

function PermissionSection() {
  const mode = useMcpMode();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const title = "AI agent 权限";

  const change = async (next: McpMode) => {
    if (next === mode.data?.mode) return;
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
      description="默认全部开放，不用设置。只有想收紧时才需要改；你随时可以在「环境」列表里点「接管」把环境拿回来。"
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
        {error && <Banner tone="danger" title="没有保存">{error}</Banner>}
      </fieldset>
    </Section>
  );
}

// Only used when the Manager has login protection on: the admin token (AUTH_TOKEN) is the bearer.
const TOKEN_PLACEHOLDER = "<你的 AUTH_TOKEN>";

function connectionSnippets(origin: string, enforced: boolean) {
  const mcpUrl = `${origin}/api/agent/mcp`;
  const bearer = TOKEN_PLACEHOLDER;
  return [
    {
      id: "claude-code",
      label: "Claude Code",
      note: "在终端里执行一次即可。",
      code: enforced
        ? `claude mcp add --transport http cloakbrowser-manager ${mcpUrl} \\\n  --header "Authorization: Bearer ${bearer}"`
        : `claude mcp add --transport http cloakbrowser-manager ${mcpUrl}`,
    },
    {
      id: "codex",
      label: "Codex",
      note: enforced ? "写进 ~/.codex/config.toml，AUTH_TOKEN 放在环境变量里。" : "写进 ~/.codex/config.toml。",
      code: enforced
        ? `[mcp_servers.cloakbrowser-manager]\nurl = "${mcpUrl}"\nbearer_token_env_var = "CLOAK_AUTH_TOKEN"\n\n# 终端里：\nexport CLOAK_AUTH_TOKEN=${bearer}`
        : `[mcp_servers.cloakbrowser-manager]\nurl = "${mcpUrl}"`,
    },
    {
      id: "json",
      label: "Cursor / 通用 JSON",
      note: "Cursor 的 mcp.json，或任何支持 streamable HTTP 的 MCP 客户端。",
      code: JSON.stringify(
        { mcpServers: { "cloakbrowser-manager": { url: mcpUrl, ...(enforced ? { headers: { Authorization: `Bearer ${bearer}` } } : {}) } } },
        null,
        2,
      ),
    },
    {
      id: "rest",
      label: "命令行 / REST",
      note: "不支持 MCP 的 AI 工具，用函数调用或 shell 即可。",
      code: [
        `# 当前档位下可用的工具（OpenAI 函数格式）`,
        `curl -s ${origin}/api/agent/tools?format=openai${enforced ? ` \\\n  -H "Authorization: Bearer ${bearer}"` : ""}`,
        ``,
        `# 调用一个工具`,
        `curl -s -X POST ${origin}/api/agent/tools/list_profiles \\\n  -H "Content-Type: application/json"${enforced ? ` \\\n  -H "Authorization: Bearer ${bearer}"` : ""} -d '{}'`,
        ``,
        `# 仓库里的命令行`,
        `./bin/cloak profiles --json`,
      ].join("\n"),
    },
  ];
}

function ConnectSection() {
  const tokens = useAgentTokens();
  const origin = window.location.origin;
  const enforced = tokens.data?.enforced ?? false;
  const snippets = connectionSnippets(origin, enforced);
  const [snippetTab, setSnippetTab] = useState("claude-code");
  return (
    <Section
      id="agent-connect"
      title="连接 AI 工具"
      description="选一个客户端，复制下面的命令，地址已经填好，不需要令牌。"
    >
      <div className="flex flex-col gap-5">
        {enforced && <Banner tone="info">这个 Manager 开了登录保护：命令里的「{TOKEN_PLACEHOLDER}」换成你启动时设的 AUTH_TOKEN。</Banner>}
        <Tabs
          label="选择 AI 工具"
          value={snippetTab}
          onValueChange={setSnippetTab}
          tabs={snippets.map((item) => ({
            value: item.id,
            label: item.label,
            content: (
              <div className="flex flex-col gap-2">
                <p className="text-sm text-fg-2">{item.note}</p>
                <CodeBlock label={`${item.label}配置`} value={item.code} />
              </div>
            ),
          }))}
        />
        <div className="flex flex-col gap-2">
          <h3 className="m-0 text-base font-semibold text-fg">技能包（推荐）</h3>
          <p className="m-0 text-sm text-fg-2">
            让 AI 先学会怎么用再动手：什么时候用哪个工具、标准流程、红线、错误怎么处理。支持 Claude Code、Codex、Cursor 等。
          </p>
          <CodeBlock label="技能包安装命令" value={`npx skills add https://github.com/NorwayXZ/CloakBrowser-Manager --skill cloakbrowser-manager`} />
        </div>
        <dl className="grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-[6rem_minmax(0,1fr)] sm:items-center">
          <dt className="text-xs text-fg-3">HTTP MCP</dt>
          <dd className="m-0 min-w-0">
            <CopyField label="HTTP MCP 地址" value={`${origin}/api/agent/mcp`} />
          </dd>
          <dt className="text-xs text-fg-3">使用指南</dt>
          <dd className="m-0 min-w-0">
            <CopyField label="使用指南地址" value={`${origin}/api/agent/guide`} />
          </dd>
        </dl>
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
