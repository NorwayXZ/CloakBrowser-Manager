import { useQueryClient } from "@tanstack/react-query";
import { Eye, MailCheck, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Banner, Button, CopyField, ErrorState, FormField, IconButton, Input, Section, Skeleton, Table, TD, TH, THead, TR, useConfirm, useToast } from "../../ui";
import { useProfiles } from "../profiles/api";
import {
  message,
  settingsApi,
  settingsKeys,
  useAgentTokens,
  useMailAddresses,
  useMailSettings,
  useVault,
  type MailSettings,
  type VaultEntry,
  type VaultStatus,
} from "./api";

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

/** 设置 › 邮箱与保险库: the domain mailbox AI agents sign up with, and the passwords they generated. */
export function MailSection() {
  return (
    <div className="flex flex-col gap-6">
      <MailConfigSection />
      <VaultSection />
      <AddressSection />
    </div>
  );
}

function MailConfigSection() {
  const settings = useMailSettings();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState({ domain: "", worker_url: "", token: "", max_new_per_day: "30", retention_days: "7" });
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const title = "域名邮箱";
  const description = "AI 注册网站时用你自己域名下的随机地址收验证邮件。收信靠一个 Cloudflare Email Worker（部署步骤见 docs/MAIL.md）。";

  useEffect(() => {
    if (!settings.data) return;
    setDraft((current) => ({
      ...current,
      domain: settings.data.domain,
      worker_url: settings.data.worker_url,
      max_new_per_day: String(settings.data.max_new_per_day),
      retention_days: String(settings.data.retention_days),
    }));
  }, [settings.data]);

  if (settings.isPending) {
    return (
      <Section id="mail-config" title={title} description={description}>
        <Skeleton className="h-40 w-full" />
      </Section>
    );
  }
  if (settings.isError) {
    return (
      <Section id="mail-config" title={title} description={description}>
        <ErrorState title="邮箱设置没有读出来" message={settings.error.message} onRetry={() => void settings.refetch()} retrying={settings.isFetching} />
      </Section>
    );
  }
  const saved: MailSettings = settings.data;

  const save = async (clearToken = false) => {
    setBusy("save");
    setError(null);
    try {
      const next = await settingsApi.saveMailSettings({
        domain: draft.domain.trim(),
        worker_url: draft.worker_url.trim(),
        token: !clearToken && draft.token.trim() ? draft.token.trim() : undefined,
        clear_token: clearToken || undefined,
        max_new_per_day: Number(draft.max_new_per_day) || undefined,
        retention_days: Number(draft.retention_days) || undefined,
      });
      queryClient.setQueryData(settingsKeys.mail, next);
      setDraft((current) => ({ ...current, token: "" }));
      toast.show({ tone: "success", title: clearToken ? "令牌已清除" : "邮箱设置已保存" });
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    setBusy("test");
    setError(null);
    try {
      const result = await settingsApi.testMail();
      toast.show({ tone: "success", title: "连接正常", description: `Worker 在线，域名 ${result.domain}。` });
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(null);
    }
  };

  const changed =
    draft.domain.trim() !== saved.domain ||
    draft.worker_url.trim() !== saved.worker_url ||
    draft.token.trim() !== "" ||
    draft.max_new_per_day !== String(saved.max_new_per_day) ||
    draft.retention_days !== String(saved.retention_days);

  return (
    <Section id="mail-config" title={title} description={description} actions={<MailCheck className="h-4 w-4 text-fg-3" aria-hidden />}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        {!saved.configured && <Banner tone="info">还没配置完整：填好域名、Worker 地址和令牌，AI 才能新建邮箱地址。</Banner>}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField label="域名" description="收信的域名，如 example.com（DNS 要在 Cloudflare）">
            <Input value={draft.domain} placeholder="example.com" onChange={(event) => setDraft({ ...draft, domain: event.target.value })} />
          </FormField>
          <FormField label="Worker 地址" description="部署后得到的 workers.dev 地址">
            <Input value={draft.worker_url} placeholder="https://cloakbrowser-mail.<你>.workers.dev" onChange={(event) => setDraft({ ...draft, worker_url: event.target.value })} />
          </FormField>
          <FormField label="令牌" description={saved.has_token ? "已配置（留空表示不修改）；只写不读" : "和 Worker 的 API_TOKEN 一致"}>
            <Input
              type="password"
              autoComplete="new-password"
              value={draft.token}
              placeholder={saved.has_token ? "已配置" : "API_TOKEN"}
              onChange={(event) => setDraft({ ...draft, token: event.target.value })}
            />
          </FormField>
          <div className="grid grid-cols-2 gap-4">
            <FormField label="每天最多新建" description="地址和保险库条目各算">
              <Input type="number" min={1} max={500} value={draft.max_new_per_day} onChange={(event) => setDraft({ ...draft, max_new_per_day: event.target.value })} />
            </FormField>
            <FormField label="邮件保留天数" description="之后自动删除">
              <Input type="number" min={1} max={90} value={draft.retention_days} onChange={(event) => setDraft({ ...draft, retention_days: event.target.value })} />
            </FormField>
          </div>
        </div>
        {error && <Banner tone="danger" title="没有成功">{error}</Banner>}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="primary" loading={busy === "save"} disabled={busy !== null || !changed}>
            保存设置
          </Button>
          <Button type="button" loading={busy === "test"} disabled={busy !== null || !saved.configured || changed} onClick={() => void test()}>
            测试连接
          </Button>
          {saved.has_token && (
            <Button type="button" variant="danger-ghost" disabled={busy !== null} onClick={() => void save(true)}>
              清除令牌
            </Button>
          )}
        </div>
      </form>
    </Section>
  );
}

function VaultSection() {
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
                  <TD className="truncate text-fg-2">{names.get(entry.profile_id) ?? "（已删除）"}</TD>
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

function AddressSection() {
  const addresses = useMailAddresses();
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const title = "已分配的邮箱地址";

  const remove = async (address: string) => {
    const ok = await confirm({
      title: `删除 ${address}？`,
      description: "这个地址会停止收信，里面已收到的邮件也会一起删除。",
      confirmLabel: "删除",
      danger: true,
    });
    if (!ok) return;
    setBusy(address);
    setError(null);
    try {
      await settingsApi.deleteMailAddress(address);
      await queryClient.invalidateQueries({ queryKey: settingsKeys.mailAddresses });
      toast.show({ tone: "success", title: "地址已删除" });
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(null);
    }
  };

  if (addresses.isPending) {
    return (
      <Section id="mail-addresses" title={title}>
        <Skeleton className="h-16 w-full" />
      </Section>
    );
  }
  if (addresses.isError) {
    return (
      <Section id="mail-addresses" title={title}>
        <ErrorState title="地址列表没有读出来" message={addresses.error.message} onRetry={() => void addresses.refetch()} retrying={addresses.isFetching} />
      </Section>
    );
  }
  const list = addresses.data.addresses;
  return (
    <Section id="mail-addresses" title={title} description="AI 新建的每个地址都登记在 Worker 里；没登记的地址发来的邮件会被直接拒收。">
      <div className="flex flex-col gap-3">
        {error && <Banner tone="danger" title="操作没有成功">{error}</Banner>}
        {list.length === 0 ? (
          <p className="text-sm text-fg-2">还没有分配过地址。</p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {list.map((item) => (
              <li key={item.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                <span className="min-w-0 flex-1 truncate font-mono text-xs text-fg" title={item.address}>
                  {item.address}
                </span>
                {item.site && <Badge>{item.site}</Badge>}
                <span className="shrink-0 text-xs text-fg-3">{formatTime(item.created_at)}</span>
                <IconButton
                  size="sm"
                  variant="danger-ghost"
                  label={`删除 ${item.address}`}
                  icon={<Trash2 className="h-3.5 w-3.5" />}
                  disabled={busy === item.address}
                  onClick={() => void remove(item.address)}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </Section>
  );
}
