import { useQueryClient } from "@tanstack/react-query";
import { Eye, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge, Banner, Button, CopyField, ErrorState, IconButton, Section, Skeleton, Table, TD, TH, THead, TR, useConfirm, useToast } from "../../ui";
import { useProfiles } from "../profiles/api";
import { message, settingsApi, settingsKeys, useAgentTokens, useVault, type VaultEntry, type VaultStatus } from "./api";

const STATUS: Record<VaultStatus, { label: string; tone: "neutral" | "info" | "success" | "danger" }> = {
  new: { label: "新建", tone: "neutral" },
  registered: { label: "已提交注册", tone: "info" },
  verified: { label: "已验证", tone: "success" },
  failed: { label: "失败", tone: "danger" },
};

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** 设置 › 保险库: the accounts AI agents signed up for. Passwords are readable only here, on request. */
export function VaultSection() {
  const vault = useVault();
  const profiles = useProfiles();
  const tokens = useAgentTokens();
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();
  const [revealed, setRevealed] = useState<{ entry: VaultEntry; password: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const title = "保险库";
  const description = "AI 注册账号时生成的用户名和密码。密码加密保存，AI 只拿到引用、看不到明文；只有你在这里点「查看密码」才会显示。";
  const names = new Map((profiles.data ?? []).map((profile) => [profile.id, profile.name]));

  const reveal = async (entry: VaultEntry) => {
    setBusy(entry.id);
    setError(null);
    try {
      const result = await settingsApi.revealVault(entry.id);
      setRevealed({ entry, password: result.password });
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(null);
    }
  };

  const remove = async (entry: VaultEntry) => {
    const ok = await confirm({
      title: `删除 ${entry.site} 的这条记录？`,
      description: "密码会从保险库里永久删除。已经注册好的网站账号不受影响，但你就找不回这个密码了。",
      confirmLabel: "删除",
      danger: true,
    });
    if (!ok) return;
    setBusy(entry.id);
    setError(null);
    try {
      await settingsApi.deleteVault(entry.id);
      if (revealed?.entry.id === entry.id) setRevealed(null);
      await queryClient.invalidateQueries({ queryKey: settingsKeys.vault });
      toast.show({ tone: "success", title: "已删除" });
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(null);
    }
  };

  if (vault.isPending) {
    return (
      <Section id="mail-vault" title={title} description={description}>
        <Skeleton className="h-24 w-full" />
      </Section>
    );
  }
  if (vault.isError) {
    return (
      <Section id="mail-vault" title={title} description={description}>
        <ErrorState title="保险库没有读出来" message={vault.error.message} onRetry={() => void vault.refetch()} retrying={vault.isFetching} />
      </Section>
    );
  }
  const entries = vault.data.entries;
  return (
    <Section id="mail-vault" title={title} description={description}>
      <div className="flex flex-col gap-4">
        {tokens.data && !tokens.data.enforced && (
          <Banner tone="warning" title="没有设置管理员密码">
            任何能访问本机接口的程序（包括有命令行权限的 AI）都能读出这里的密码。建议先在「账号与安全」里设置管理员密码。
          </Banner>
        )}
        {revealed && (
          <Banner
            tone="info"
            title={`${revealed.entry.site} · ${revealed.entry.username ?? revealed.entry.email ?? ""}`}
            action={
              <Button size="sm" onClick={() => setRevealed(null)}>
                隐藏
              </Button>
            }
          >
            <CopyField label="密码" value={revealed.password} className="mt-1.5" />
          </Banner>
        )}
        {error && <Banner tone="danger" title="操作没有成功">{error}</Banner>}
        {entries.length === 0 ? (
          <p className="text-sm text-fg-2">还没有记录。AI 用 account_prepare 注册网站后，会出现在这里。</p>
        ) : (
          <Table label="保险库">
            <THead>
              <TR>
                <TH>网站</TH>
                <TH>用户名 / 邮箱</TH>
                <TH>环境</TH>
                <TH>状态</TH>
                <TH>创建时间</TH>
                <TH className="w-24 text-right">操作</TH>
              </TR>
            </THead>
            <tbody>
              {entries.map((entry) => (
                <TR key={entry.id}>
                  <TD className="font-medium text-fg">{entry.site}</TD>
                  <TD className="min-w-0 text-fg-2">
                    <div className="truncate" title={entry.username ?? ""}>{entry.username ?? "—"}</div>
                    <div className="truncate text-xs text-fg-3" title={entry.email ?? ""}>{entry.email ?? ""}</div>
                  </TD>
                  <TD className="truncate text-fg-2">{names.get(entry.profile_id) ?? (profiles.isPending ? "…" : "（已删除）")}</TD>
                  <TD>
                    <Badge tone={STATUS[entry.status]?.tone ?? "neutral"}>{STATUS[entry.status]?.label ?? entry.status}</Badge>
                  </TD>
                  <TD className="text-xs text-fg-3">{formatTime(entry.created_at)}</TD>
                  <TD>
                    <div className="flex justify-end gap-1">
                      <IconButton
                        size="sm"
                        label={`查看 ${entry.site} 的密码`}
                        icon={<Eye className="h-3.5 w-3.5" />}
                        disabled={busy === entry.id}
                        onClick={() => void reveal(entry)}
                      />
                      <IconButton
                        size="sm"
                        variant="danger-ghost"
                        label={`删除 ${entry.site} 的记录`}
                        icon={<Trash2 className="h-3.5 w-3.5" />}
                        disabled={busy === entry.id}
                        onClick={() => void remove(entry)}
                      />
                    </div>
                  </TD>
                </TR>
              ))}
            </tbody>
          </Table>
        )}
      </div>
    </Section>
  );
}
