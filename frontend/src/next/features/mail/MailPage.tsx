import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Inbox, Mail, Plus, RefreshCw, Search, Server, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { cn } from "../../shared/lib/cn";
import {
  Badge,
  Banner,
  Button,
  Checkbox,
  CopyField,
  Dialog,
  EmptyState,
  ErrorState,
  FormField,
  IconButton,
  Input,
  PageHeader,
  Section,
  Select,
  Skeleton,
  Table,
  TD,
  TH,
  THead,
  TR,
  useConfirm,
  useToast,
} from "../../ui";
import { useProfiles } from "../profiles/api";
import { formatDateTime } from "../profiles/format";
import { mailApi, mailKeys, useMailAddresses, useMailMessages, useMailSettings, type MailAddress, type MailMessage, type MailSettings } from "./api";

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

const PAGE_DESCRIPTION = "给 AI 注册账号用的收信地址。AI 用 mail_get_address 给环境要一个地址，提交表单后用 mail_wait_code 直接拿到验证码，不用再找你要邮箱和验证码。";

export function MailPage() {
  const settings = useMailSettings();
  const [serverOpen, setServerOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const configured = settings.data?.configured === true;

  return (
    <div className="flex flex-col gap-6 p-6">
      <PageHeader
        title="邮箱"
        description={PAGE_DESCRIPTION}
        actions={
          configured && (
            <>
              <Button icon={<Server className="h-4 w-4" />} onClick={() => setServerOpen(true)}>
                服务器设置
              </Button>
              <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
                新地址
              </Button>
            </>
          )
        }
      />
      {settings.isPending ? (
        <Skeleton className="h-48 w-full" />
      ) : settings.isError ? (
        <ErrorState title="邮箱设置没有读出来" message={settings.error.message} onRetry={() => void settings.refetch()} retrying={settings.isFetching} />
      ) : !configured ? (
        <Section
          id="mail-server"
          title="连接邮箱服务器"
          description="填你的 Cloud Mail 邮箱后台地址和管理员账号。Manager 用它创建地址、读取发给这些地址的邮件；密码加密保存在这台电脑上。"
        >
          <ServerForm status={settings.data} />
        </Section>
      ) : (
        <Mailboxes selected={selected} onSelect={setSelected} onCreate={() => setCreating(true)} />
      )}
      {serverOpen && settings.data && (
        <Dialog open onOpenChange={(open) => !open && setServerOpen(false)} title="邮箱服务器" description="改完保存后会重新登录一次，确认能连上。" size="lg">
          <ServerForm status={settings.data} onDone={() => setServerOpen(false)} />
        </Dialog>
      )}
      {creating && <NewAddressDialog onClose={() => setCreating(false)} onCreated={setSelected} />}
    </div>
  );
}

// ── Server connection ────────────────────────────────────────────────────────

function ServerForm({ status, onDone }: { status: MailSettings; onDone?: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [baseUrl, setBaseUrl] = useState(status.base_url ?? "");
  const [adminEmail, setAdminEmail] = useState(status.admin_email ?? "");
  const [password, setPassword] = useState("");
  const [available, setAvailable] = useState<string[] | null>(null);
  // Empty = every domain (also ones added on the server later).
  const [chosen, setChosen] = useState<string[]>(status.domains);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);

  // Already connected: show the server's domains right away.
  useEffect(() => {
    if (!status.configured) return;
    let alive = true;
    mailApi
      .check()
      .then((result) => alive && setAvailable(result.domains))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [status.configured]);

  const isChosen = (domain: string) => chosen.length === 0 || chosen.includes(domain);
  const toggle = (domain: string, on: boolean) => {
    const all = available ?? [];
    const current = chosen.length === 0 ? all : chosen;
    const next = on ? [...new Set([...current, domain])] : current.filter((d) => d !== domain);
    setChosen(next.length === all.length ? [] : next);
  };

  const save = async () => {
    setError(null);
    setFieldError(null);
    if (!baseUrl.trim() || !adminEmail.trim()) return setFieldError("服务器地址和管理员邮箱都要填");
    if (!status.has_password && !password) return setFieldError("第一次连接要填管理员密码");
    if (available && chosen.length === 0 && available.length === 0) return setFieldError("至少选一个域名");
    setSaving(true);
    try {
      const next = await mailApi.saveSettings({
        base_url: baseUrl.trim(),
        admin_email: adminEmail.trim(),
        password: password ? password : null,
        domains: chosen,
      });
      queryClient.setQueryData(mailKeys.settings, next);
      setPassword("");
      try {
        const check = await mailApi.check();
        setAvailable(check.domains);
        toast.show({ tone: "success", title: "已连接邮箱服务器", description: `可用域名 ${check.domains.length} 个：${check.domains.join("、")}` });
        onDone?.();
      } catch (err) {
        setError(message(err));
      }
    } catch (err) {
      setError(message(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      className="flex flex-col gap-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <FormField label="服务器地址" description="邮箱后台的网址，例如 mail.example.com。" error={fieldError && !baseUrl.trim() ? fieldError : undefined}>
          <Input mono value={baseUrl} placeholder="mail.example.com" autoComplete="off" spellCheck={false} onChange={(event) => setBaseUrl(event.target.value)} />
        </FormField>
        <FormField label="管理员邮箱" error={fieldError && baseUrl.trim() && !adminEmail.trim() ? fieldError : undefined}>
          <Input mono value={adminEmail} placeholder="admin@example.com" autoComplete="off" spellCheck={false} onChange={(event) => setAdminEmail(event.target.value)} />
        </FormField>
      </div>
      <FormField label="管理员密码" description="只写不读：加密保存，保存后这里不再显示。" error={fieldError && baseUrl.trim() && adminEmail.trim() ? fieldError : undefined}>
        <Input
          type="password"
          value={password}
          placeholder={status.has_password ? "已保存（留空表示不修改）" : "管理员密码"}
          autoComplete="new-password"
          onChange={(event) => setPassword(event.target.value)}
        />
      </FormField>
      {available && (
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-sm font-medium text-fg">新地址用哪些域名</legend>
          {available.length === 0 ? (
            <p className="text-sm text-warning">服务器上还没有域名，先在邮箱后台添加。</p>
          ) : (
            <div className="flex flex-wrap gap-x-5 gap-y-2">
              {available.map((domain) => (
                <Checkbox key={domain} checked={isChosen(domain)} onCheckedChange={(on) => toggle(domain, on)} label={<span className="font-mono">{domain}</span>} />
              ))}
            </div>
          )}
          <p className="text-xs text-fg-3">全选时，以后在后台新加的域名也会自动用上。</p>
        </fieldset>
      )}
      {error && <Banner tone="danger" title="没有连上">{error}</Banner>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" loading={saving}>
          {status.configured ? "保存" : "保存并连接"}
        </Button>
        {onDone && (
          <Button type="button" onClick={onDone} disabled={saving}>
            关闭
          </Button>
        )}
      </div>
    </form>
  );
}

// ── Addresses and their inboxes ──────────────────────────────────────────────

function Mailboxes({ selected, onSelect, onCreate }: { selected: string | null; onSelect: (address: string | null) => void; onCreate: () => void }) {
  const addresses = useMailAddresses(true);
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const forget = useMutation({
    mutationFn: mailApi.forget,
    onSettled: () => queryClient.invalidateQueries({ queryKey: mailKeys.addresses }),
  });
  const list = useMemo(() => addresses.data ?? [], [addresses.data]);
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? list.filter((a) => a.address.includes(q) || (a.profile_name ?? "").toLowerCase().includes(q)) : list;
  }, [list, search]);

  // Keep a valid selection: the first address, or none.
  useEffect(() => {
    if (!addresses.isSuccess) return;
    if (!selected || !list.some((a) => a.address === selected)) onSelect(list[0]?.address ?? null);
  }, [addresses.isSuccess, list, selected, onSelect]);

  const ask = async (item: MailAddress) => {
    const ok = await confirm({
      title: `忘记 ${item.address}？`,
      description: "只是从 Manager 里移除：邮箱服务器上的邮箱和邮件都还在。AI 下次会给这个环境发一个新地址。",
      confirmLabel: "忘记",
      danger: true,
    });
    if (!ok) return;
    try {
      await forget.mutateAsync(item.address);
      toast.show({ tone: "success", title: `已忘记 ${item.address}` });
    } catch (error) {
      toast.show({ tone: "error", title: "没有移除", description: message(error) });
    }
  };

  if (addresses.isPending) return <Skeleton className="h-64 w-full" />;
  if (addresses.isError) return <ErrorState title="地址列表没有读出来" message={addresses.error.message} onRetry={() => void addresses.refetch()} retrying={addresses.isFetching} />;
  if (list.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border-strong bg-surface">
        <EmptyState
          icon={Mail}
          title="还没有地址"
          description="AI 第一次用 mail_get_address 时会自动创建，也可以在这里手动建一个。"
          action={
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={onCreate}>
              新地址
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="flex min-w-0 flex-col gap-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-3" aria-hidden />
          <Input className="pl-8" value={search} placeholder="搜索地址或环境" aria-label="搜索地址或环境" onChange={(event) => setSearch(event.target.value)} />
        </div>
        {shown.length === 0 ? (
          <p className="px-1 py-6 text-center text-sm text-fg-2">没有匹配「{search.trim()}」的地址</p>
        ) : (
          <Table label="邮箱地址" minWidth={480}>
            <colgroup>
              <col />
              <col className="w-32" />
              <col className="w-28" />
              <col className="w-12" />
            </colgroup>
            <THead>
              <tr>
                <TH>地址</TH>
                <TH>环境</TH>
                <TH>创建时间</TH>
                <TH className="text-right">
                  <span className="sr-only">操作</span>
                </TH>
              </tr>
            </THead>
            <tbody>
              {shown.map((item) => {
                const active = item.address === selected;
                return (
                  <TR key={item.address} selected={active}>
                    <TD className="truncate">
                      <button
                        type="button"
                        aria-pressed={active}
                        className="max-w-full truncate rounded-sm text-left font-mono text-xs text-fg hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                        title={item.address}
                        onClick={() => onSelect(item.address)}
                      >
                        {item.address}
                      </button>
                    </TD>
                    <TD className="truncate text-fg-2" title={item.profile_name ?? undefined}>
                      {item.profile_name ?? (item.profile_id ? "已删除的环境" : "未绑定")}
                    </TD>
                    <TD className="text-fg-2">{formatDateTime(item.created_at)}</TD>
                    <TD className="text-right">
                      <IconButton size="sm" variant="danger-ghost" label={`忘记 ${item.address}`} icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => void ask(item)} />
                    </TD>
                  </TR>
                );
              })}
            </tbody>
          </Table>
        )}
      </div>
      {selected && <InboxPanel address={selected} />}
    </div>
  );
}

function InboxPanel({ address }: { address: string }) {
  const inbox = useMailMessages(address);
  const messages = inbox.data?.messages ?? [];
  return (
    <Section
      id="mail-inbox"
      title="收件箱"
      description={<span className="break-all font-mono">{address}</span>}
      actions={
        <IconButton
          size="sm"
          label="刷新收件箱"
          icon={<RefreshCw className={cn("h-3.5 w-3.5", inbox.isFetching && "animate-spin")} />}
          onClick={() => void inbox.refetch()}
        />
      }
    >
      <div className="flex flex-col gap-3">
        <CopyField value={address} label="邮箱地址" />
        {inbox.isPending ? (
          <Skeleton className="h-32 w-full" />
        ) : inbox.isError ? (
          <ErrorState title="收件箱没有读出来" message={inbox.error.message} onRetry={() => void inbox.refetch()} retrying={inbox.isFetching} />
        ) : messages.length === 0 ? (
          <EmptyState icon={Inbox} title="还没有收到邮件" description="发到这个地址的邮件会自动出现在这里（每 10 秒刷新一次）。" />
        ) : (
          <ul className="flex flex-col gap-2" aria-label="邮件">
            {messages.map((item) => (
              <MessageItem key={item.id} item={item} handed={item.id <= (inbox.data?.last_delivered_id ?? 0)} />
            ))}
          </ul>
        )}
      </div>
    </Section>
  );
}

function MessageItem({ item, handed }: { item: MailMessage; handed: boolean }) {
  return (
    <li className="min-w-0 rounded-md border border-border bg-surface px-3 py-2.5">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-fg" title={item.subject}>
            {item.subject || "（无标题）"}
          </p>
          <p className="truncate text-xs text-fg-2" title={item.from}>
            {item.from_name ? `${item.from_name} · ` : ""}
            {item.from}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <span className="text-xs text-fg-3">{formatDateTime(item.received_at)}</span>
          {handed && <Badge tone="info">AI 已取用</Badge>}
        </div>
      </div>
      {(item.code || item.link) && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {item.code && <CopyField value={item.code} label="验证码" className="w-40" />}
          {item.link && (
            <a
              href={item.link}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1 rounded-sm text-sm text-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              验证链接
            </a>
          )}
        </div>
      )}
      {item.text && (
        <details className="mt-2">
          <summary className="cursor-pointer select-none text-xs text-fg-2 hover:text-fg">正文</summary>
          <p className="mt-1.5 max-h-48 overflow-y-auto whitespace-pre-wrap break-words text-xs text-fg-2">{item.text}</p>
        </details>
      )}
    </li>
  );
}

// ── New address ──────────────────────────────────────────────────────────────

function NewAddressDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (address: string) => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const profiles = useProfiles();
  const domains = useQuery({ queryKey: ["mail", "domains"], queryFn: mailApi.check, staleTime: 5 * 60_000 });
  const [profileId, setProfileId] = useState("");
  const [domain, setDomain] = useState("");
  const [prefix, setPrefix] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const create = async () => {
    setError(null);
    setSaving(true);
    try {
      const created = await mailApi.createAddress({
        ...(profileId ? { profile_id: profileId } : {}),
        ...(domain ? { domain } : {}),
        ...(prefix.trim() ? { local_part: prefix.trim().toLowerCase() } : {}),
      });
      await queryClient.invalidateQueries({ queryKey: mailKeys.addresses });
      onCreated(created.address);
      toast.show({ tone: "success", title: "已创建地址", description: created.address });
      onClose();
    } catch (err) {
      setError(message(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      dismissible={!saving}
      title="新地址"
      description="地址会在邮箱服务器上创建好，马上就能收信。"
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            取消
          </Button>
          <Button variant="primary" loading={saving} onClick={() => void create()}>
            创建
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void create();
        }}
      >
        <FormField label="归属环境" description="AI 给这个环境要地址时会拿到它。">
          <Select value={profileId} onChange={(event) => setProfileId(event.target.value)} disabled={profiles.isPending}>
            <option value="">不绑定环境</option>
            {(profiles.data ?? []).map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.name}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="域名" error={domains.isError ? `读不到域名：${domains.error.message}` : undefined}>
          <Select value={domain} onChange={(event) => setDomain(event.target.value)} disabled={!domains.isSuccess}>
            <option value="">{domains.isPending ? "正在读取域名…" : "随机（从选用的域名里挑）"}</option>
            {(domains.data?.domains ?? []).map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="前缀" description="留空会自动生成一个像人名的前缀，例如 emma.walker42。">
          <Input mono value={prefix} placeholder="可选" autoComplete="off" spellCheck={false} onChange={(event) => setPrefix(event.target.value)} />
        </FormField>
        {error && <Banner tone="danger" title="没有创建">{error}</Banner>}
        <button type="submit" hidden />
      </form>
    </Dialog>
  );
}
