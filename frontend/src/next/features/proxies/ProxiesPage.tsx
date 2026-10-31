import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Globe2, Trash2, Wifi } from "lucide-react";
import { useMemo, useState } from "react";
import { request } from "../../shared/api/client";
import { maskProxy } from "../../shared/lib/mask";
import {
  Badge,
  Banner,
  Button,
  Dialog,
  EmptyState,
  ErrorState,
  FormField,
  IconButton,
  Input,
  KeyValueList,
  PageHeader,
  Select,
  Skeleton,
  Table,
  Tabs,
  TD,
  TH,
  THead,
  TR,
  Textarea,
  useConfirm,
  useToast,
} from "../../ui";
import { editorApi, editorKeys, useProxyPresets } from "../editor/api";
import { IpQualityPanel } from "../editor/sections/ProxySection";
import type { ProxyPreset, ProxyTestResult } from "../editor/types";
import { ProxyIpActions } from "./ProxyIpActions";
import { RelayNodesPanel } from "./RelayNodesPanel";
import { RelayRouteFields } from "./RelayRouteFields";
import { formatDateTime } from "../profiles/format";
import { buildDirectProxyUrl, isDirectProxyMode, LINK_PROXY_MODES, parseProxyBatchLine, type ProxyMode } from "./proxyInput";

type PresetInput = { name: string; proxy: string; mode: string };
type SavedPreset = ProxyPreset & { created_at?: string };

const proxiesApi = {
  create: (item: PresetInput) => request<ProxyPreset>("/api/proxy-presets", { method: "POST", body: item }),
  createMany: (items: PresetInput[]) => request<ProxyPreset[]>("/api/proxy-presets/bulk", { method: "POST", body: { items } }),
  remove: (id: string) => request<{ ok: boolean }>(`/api/proxy-presets/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

const MODE_OPTIONS: [ProxyMode, string][] = [
  ["socks5", "SOCKS5"],
  ["http", "HTTP"],
  ["https", "HTTPS"],
  ["vless", "VLESS"],
  ["vmess", "VMESS"],
  ["trojan", "TROJAN"],
  ["ss", "Shadowsocks"],
];

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export function ProxiesPage() {
  const [tab, setTab] = useState("proxies");
  return <div className="p-4"><Tabs label="代理分类" value={tab} onValueChange={setTab} tabs={[
    { value: "proxies", label: "出口代理", content: <ExitProxiesPage /> },
    { value: "relays", label: "中转服务器", content: <RelayNodesPanel /> },
  ]} /></div>;
}

function ExitProxiesPage() {
  const presets = useProxyPresets();
  const queryClient = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const [testing, setTesting] = useState<SavedPreset | null>(null);
  const remove = useMutation({
    mutationFn: proxiesApi.remove,
    onSettled: () => queryClient.invalidateQueries({ queryKey: editorKeys.proxyPresets }),
  });

  const ask = async (preset: SavedPreset) => {
    const ok = await confirm({
      title: `删除代理「${preset.name}」？`,
      description: "已经在用这个代理的环境不受影响，它们保存的是自己的一份。",
      confirmLabel: "删除",
      danger: true,
    });
    if (!ok) return;
    try {
      await remove.mutateAsync(preset.id);
      toast.show({ tone: "success", title: `已删除「${preset.name}」` });
    } catch (error) {
      toast.show({ tone: "error", title: "没有删除", description: message(error) });
    }
  };

  const list = (presets.data ?? []) as SavedPreset[];

  return (
    <div className="flex flex-col gap-6 p-6">
      <PageHeader title="代理" description={presets.isSuccess ? `共 ${list.length} 个保存的代理。新建或编辑环境时可以直接选用。` : "保存常用代理，新建或编辑环境时直接选用。"} />
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0">
          {presets.isPending ? (
            <Skeleton className="h-48 w-full" />
          ) : presets.isError ? (
            <ErrorState message={presets.error.message} onRetry={() => void presets.refetch()} />
          ) : list.length === 0 ? (
            <div className="glass rounded-lg">
              <EmptyState icon={Globe2} title="还没有保存的代理" description="在右边添加一个，或者一次粘贴一批。保存后在新建、编辑环境时可以直接选用。" />
            </div>
          ) : (
            <Table label="保存的代理" minWidth={540}>
              <colgroup>
                <col className="w-40" />
                <col className="w-24" />
                <col />
                <col className="w-28" />
                <col className="w-20" />
              </colgroup>
              <THead>
                <tr>
                  <TH>名称</TH>
                  <TH>类型</TH>
                  <TH>地址</TH>
                  <TH>创建时间</TH>
                  <TH className="text-right">操作</TH>
                </tr>
              </THead>
              <tbody>
                {list.map((preset) => (
                  <TR key={preset.id}>
                    <TD className="truncate font-medium" title={preset.name}>
                      {preset.name}
                    </TD>
                    <TD>
                      <Badge>{preset.mode.toUpperCase()}</Badge>
                    </TD>
                    <TD className="truncate font-mono text-xs text-fg-2" title={maskProxy(preset.proxy)}>
                      {maskProxy(preset.proxy)}
                      {preset.proxy.toLowerCase().startsWith("socks5://") && <ProxyIpActions proxyId={preset.id} configured={preset.can_rotate_ip} editable />}
                    </TD>
                    <TD className="text-fg-2">{formatDateTime(preset.created_at)}</TD>
                    <TD className="text-right">
                      <div className="flex justify-end gap-1">
                        <IconButton size="sm" label={`检测「${preset.name}」的出口`} icon={<Wifi className="h-3.5 w-3.5" />} onClick={() => setTesting(preset)} />
                        <IconButton size="sm" variant="danger-ghost" label={`删除「${preset.name}」`} icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => void ask(preset)} />
                      </div>
                    </TD>
                  </TR>
                ))}
              </tbody>
            </Table>
          )}
        </div>
        <AddPanel />
      </div>
      {testing && <TestDialog preset={testing} onClose={() => setTesting(null)} />}
    </div>
  );
}

function AddPanel() {
  const [tab, setTab] = useState("single");
  return (
    <div className="glass rounded-lg px-4 pb-4 pt-1">
      <Tabs
        label="添加代理"
        value={tab}
        onValueChange={setTab}
        tabs={[
          { value: "single", label: "单个添加", content: <SingleForm /> },
          { value: "batch", label: "批量导入", content: <BatchForm /> },
        ]}
      />
    </div>
  );
}

function useSaved() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: editorKeys.proxyPresets });
}

function SingleForm() {
  const toast = useToast();
  const saved = useSaved();
  const [name, setName] = useState("");
  const [mode, setMode] = useState<ProxyMode>("socks5");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [link, setLink] = useState("");
  const [error, setError] = useState<{ field: "name" | "address" | "server"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const direct = isDirectProxyMode(mode);
  const built = direct ? buildDirectProxyUrl(mode, host, port, username, password) : link.trim();

  const submit = async () => {
    setError(null);
    if (!name.trim()) return setError({ field: "name", text: "请先填写代理名称" });
    if (!built) return setError({ field: "address", text: direct ? "请填写主机和端口" : "请粘贴代理链接" });
    setSaving(true);
    try {
      await proxiesApi.create({ name: name.trim(), proxy: built, mode });
      await saved();
      toast.show({ tone: "success", title: `已保存「${name.trim()}」`, description: "同名代理会更新原来那条。" });
      setName("");
      setHost("");
      setPort("");
      setUsername("");
      setPassword("");
      setLink("");
    } catch (err) {
      setError({ field: "server", text: message(err) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      className="flex flex-col gap-3"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <FormField label="代理名称" required error={error?.field === "name" ? error.text : undefined}>
        <Input value={name} placeholder="例如 美国 SOCKS5" maxLength={64} onChange={(event) => setName(event.target.value)} />
      </FormField>
      <FormField label="代理类型" description="启动浏览器时会自动检测出口 IP 和地区。">
        <Select value={mode} onChange={(event) => setMode(event.target.value as ProxyMode)}>
          {MODE_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
      </FormField>
      {direct ? (
        <>
          <div className="grid grid-cols-[minmax(0,1fr)_96px] gap-2">
            <FormField label="主机" error={error?.field === "address" ? error.text : undefined}>
              <Input mono value={host} placeholder="192.168.100.1 或 proxy.example.com" onChange={(event) => setHost(event.target.value)} />
            </FormField>
            <FormField label="端口">
              <Input mono inputMode="numeric" value={port} placeholder="1090" onChange={(event) => setPort(event.target.value)} />
            </FormField>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <FormField label="代理账号">
              <Input value={username} placeholder="没有就留空" autoComplete="off" onChange={(event) => setUsername(event.target.value)} />
            </FormField>
            <FormField label="代理密码">
              <Input type="password" value={password} placeholder="没有就留空" autoComplete="new-password" onChange={(event) => setPassword(event.target.value)} />
            </FormField>
          </div>
          <p className="break-all rounded bg-surface-2 px-2.5 py-1.5 font-mono text-xs text-fg-2" aria-label="将保存的地址">
            {built ? maskProxy(built) : "代理地址会在这里自动拼好"}
          </p>
        </>
      ) : (
        <FormField label="代理链接" error={error?.field === "address" ? error.text : undefined}>
          <Textarea mono rows={3} className="text-xs" spellCheck={false} value={link} placeholder="粘贴 vless://、vmess://、trojan:// 或 ss:// 链接" onChange={(event) => setLink(event.target.value)} />
        </FormField>
      )}
      {error?.field === "server" && <Banner tone="danger" title="没有保存">{error.text}</Banner>}
      <Button type="submit" variant="primary" loading={saving} className="self-start">
        保存代理
      </Button>
    </form>
  );
}

function BatchForm() {
  const toast = useToast();
  const saved = useSaved();
  const [mode, setMode] = useState<ProxyMode>("socks5");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const lines = useMemo(() => text.split(/\r?\n/).filter((line) => line.trim() && !line.trim().startsWith("#")), [text]);
  const items = useMemo(
    () => text.split(/\r?\n/).reduce<PresetInput[]>((acc, line, index) => {
      const item = parseProxyBatchLine(line, mode, index + 1);
      if (item) acc.push(item);
      return acc;
    }, []),
    [text, mode],
  );
  const skipped = lines.length - items.length;

  const submit = async () => {
    setError(null);
    if (items.length === 0) return setError("没有识别到可保存的代理，请检查格式");
    setSaving(true);
    try {
      await proxiesApi.createMany(items);
      await saved();
      toast.show({ tone: "success", title: `已保存 ${items.length} 个代理` });
      setText("");
    } catch (err) {
      setError(message(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <FormField label="没写类型的行按" description="写了 socks5:// 等前缀的行按前缀识别。">
        <Select value={mode} onChange={(event) => setMode(event.target.value as ProxyMode)}>
          {MODE_OPTIONS.filter(([value]) => !LINK_PROXY_MODES.includes(value)).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
      </FormField>
      <FormField label="批量代理" error={error ?? undefined} description="一行一个；# 开头的行会跳过。同名代理会更新原来那条。">
        <Textarea
          mono
          rows={6}
          className="text-xs"
          spellCheck={false}
          value={text}
          placeholder={"一行一个代理，例如：\n192.168.0.1:8000\n192.168.0.1:8000:user:pass\nsocks5://user:pass@192.168.0.1:8000\nvless://..."}
          onChange={(event) => {
            setText(event.target.value);
            setError(null);
          }}
        />
      </FormField>
      {lines.length > 0 && (
        <div className="rounded-md border border-border">
          <div className="flex items-center justify-between border-b border-border px-3 py-1.5 text-xs text-fg-2">
            <span>识别出 {items.length} 个</span>
            {skipped > 0 && <span className="text-warning">{skipped} 行无法识别，会跳过</span>}
          </div>
          <ul className="max-h-48 divide-y divide-border overflow-y-auto" aria-label="将保存的代理">
            {items.map((item, index) => (
              <li key={index} className="flex min-w-0 items-center gap-2 px-3 py-1.5 text-xs">
                <Badge>{item.mode.toUpperCase()}</Badge>
                <span className="min-w-0 flex-1 truncate">{item.name}</span>
                <span className="min-w-0 max-w-[45%] truncate font-mono text-fg-3">{maskProxy(item.proxy)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <Button variant="primary" loading={saving} disabled={items.length === 0} className="self-start" onClick={() => void submit()}>
        {items.length ? `保存 ${items.length} 个代理` : "批量保存"}
      </Button>
    </div>
  );
}

function TestDialog({ preset, onClose }: { preset: SavedPreset; onClose: () => void }) {
  const [routeMode, setRouteMode] = useState<"direct" | "relay">("direct");
  const [relayId, setRelayId] = useState<string | null>(null);
  const [result, setResult] = useState<ProxyTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      setResult(await editorApi.testProxy(preset.proxy, routeMode === "relay" ? { proxy_connection_mode: "relay", relay_id: relayId } : undefined));
    } catch (err) {
      setError(message(err));
    } finally {
      setRunning(false);
    }
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={`检测「${preset.name}」`}
      description="通过这个代理查询出口 IP、地区，以及它在 IP 信誉库里的记录。"
      footer={
        <>
          <Button onClick={onClose}>关闭</Button>
          <Button variant="primary" icon={<Wifi className="h-4 w-4" />} loading={running} onClick={() => void run()} autoFocus>
            {result || error ? "再测一次" : "开始检测"}
          </Button>
        </>
      }
    >
      <fieldset disabled={running}><RelayRouteFields mode={routeMode} relayId={relayId} isSocks={preset.proxy.toLowerCase().startsWith("socks5://")} onMode={value => { setRouteMode(value); setResult(null); }} onRelay={value => { setRelayId(value); setResult(null); }} /></fieldset>
      <div className="flex flex-col gap-3">
        <p className="break-all font-mono text-xs text-fg-2">{maskProxy(preset.proxy)}</p>
        {error && <Banner tone="danger" title="连不通">{error}</Banner>}
        {result && (
          <KeyValueList
            items={[
              { label: "出口 IP", value: <span className="font-mono">{result.ip ?? "未知"}</span> },
              { label: "地区", value: [result.country, result.region, result.city].filter(Boolean).join(" · ") || "未知" },
              { label: "时区", value: result.timezone ?? "未知" },
              { label: "建议语言", value: result.suggested_locale ?? "未知" },
              { label: "运营商", value: [result.org, result.asn].filter(Boolean).join(" · ") || "未知" },
            ]}
          />
        )}
        {result?.ip_quality && <IpQualityPanel quality={result.ip_quality} />}
      </div>
    </Dialog>
  );
}
