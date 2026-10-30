import { useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Server, Trash2, Wifi } from "lucide-react";
import { useState } from "react";
import { Badge, Banner, Button, Dialog, EmptyState, ErrorState, FormField, IconButton, Input, PageHeader, Skeleton, Table, TD, TH, THead, TR, Textarea, useConfirm } from "../../ui";
import { relayApi, relayKey, useRelayNodes, type RelayNode } from "./relayApi";

function address(proxy: string) {
  if (proxy.startsWith("vmess:") || (proxy.startsWith("ss:") && !proxy.includes("@"))) return "加密连接链接";
  try { const u = new URL(proxy); return `${u.protocol}//${u.hostname}:${u.port || "443"}`; }
  catch { return "加密连接链接"; }
}

export function RelayNodesPanel() {
  const nodes = useRelayNodes();
  const cache = useQueryClient();
  const confirm = useConfirm();
  const [editing, setEditing] = useState<RelayNode | "new" | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ error?: boolean; text: string } | null>(null);
  const test = async (node: RelayNode) => {
    setTesting(node.id); setNotice(null);
    try {
      const result = await relayApi.test(node.id);
      setNotice({ text: `「${node.name}」可连接，中转出口 ${result.ip ?? "未知"}。这是中转服务器的 IP；浏览器最终出口请用 SOCKS5 完整链路检测。` });
    } catch (e) { setNotice({ error: true, text: e instanceof Error ? e.message : String(e) }); }
    finally { setTesting(null); }
  };
  const remove = async (node: RelayNode) => {
    if (!await confirm({ title: `删除中转服务器「${node.name}」？`, description: "仍有环境使用时不能删除，请先修改这些环境的连接方式。", confirmLabel: "删除", danger: true })) return;
    try { await relayApi.remove(node.id); await cache.invalidateQueries({ queryKey: relayKey }); }
    catch (e) { setNotice({ error: true, text: e instanceof Error ? e.message : String(e) }); }
  };
  return <div className="flex flex-col gap-5 p-6">
    <PageHeader title="中转服务器" description="先连接这台服务器，再连接每个环境自己的 SOCKS5。多个环境可共用一台中转。" actions={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setEditing("new")}>添加中转服务器</Button>} />
    <p className="text-sm text-fg-2">先在服务器或 Flux 面板创建一条加密代理入口，选择服务器自身 IP 出口，再把连接链接添加到这里。已有环境保持直接连接；修改中转后，正在运行的环境需关闭并重新打开才能应用。</p>
    {notice && <Banner tone={notice.error ? "danger" : "info"}>{notice.text}</Banner>}
    {nodes.isPending ? <Skeleton className="h-40" /> : nodes.isError ? <ErrorState message={nodes.error.message} onRetry={() => void nodes.refetch()} /> : !nodes.data.length ?
      <EmptyState icon={Server} title="还没有中转服务器" description="添加后，在环境的代理信息里选择“通过中转服务器”。最终出口仍是该环境的 SOCKS5。" /> :
      <Table label="中转服务器" minWidth={620}><THead><tr><TH>名称</TH><TH>入口</TH><TH>使用情况</TH><TH className="text-right">操作</TH></tr></THead><tbody>{nodes.data.map(node =>
        <TR key={node.id}><TD className="font-medium">{node.name}</TD><TD className="font-mono text-xs">{address(node.proxy)}</TD><TD><Badge>{node.profile_count ?? 0} 个环境</Badge></TD><TD><div className="flex justify-end gap-1">
          <IconButton label={`检测中转 ${node.name}`} icon={<Wifi className="h-4 w-4" />} disabled={testing !== null} onClick={() => void test(node)} />
          <IconButton label={`编辑中转 ${node.name}`} icon={<Pencil className="h-4 w-4" />} onClick={() => setEditing(node)} />
          <IconButton label={`删除中转 ${node.name}`} icon={<Trash2 className="h-4 w-4" />} onClick={() => void remove(node)} />
        </div></TD></TR>,
      )}</tbody></Table>}
    {testing && <p role="status" className="text-sm text-fg-2">正在检测中转服务器…</p>}
    {editing && <RelayEditor node={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void cache.invalidateQueries({ queryKey: relayKey }); }} />}
  </div>;
}

function RelayEditor({ node, onClose, onSaved }: { node: RelayNode | null; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(node?.name ?? "");
  const [proxy, setProxy] = useState(node?.proxy ?? "");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const save = async () => {
    if (!name.trim() || !proxy.trim()) { setError("请填写中转名称和连接链接"); return; }
    setSaving(true); setError("");
    try { await relayApi.save({ name: name.trim(), proxy: proxy.trim() }, node?.id); onSaved(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setSaving(false); }
  };
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }} title={node ? "编辑中转服务器" : "添加中转服务器"} description="支持 VLESS TLS/REALITY、Trojan、VMess TLS 和 Shadowsocks 加密入口。" dismissible={!saving}
    footer={<><Button variant="ghost" disabled={saving} onClick={onClose}>取消</Button><Button loading={saving} onClick={() => void save()}>保存中转服务器</Button></>}>
    <div className="flex flex-col gap-4">
      <FormField label="中转名称"><Input value={name} maxLength={64} placeholder="美国中转 A" onChange={e => setName(e.target.value)} /></FormField>
      <FormField label="中转连接链接"><Textarea value={proxy} rows={4} spellCheck={false} autoComplete="off" placeholder="粘贴 vless://、trojan://、vmess:// 或 ss:// 链接" onChange={e => setProxy(e.target.value)} /></FormField>
      {error && <Banner tone="danger">{error}</Banner>}
    </div>
  </Dialog>;
}
