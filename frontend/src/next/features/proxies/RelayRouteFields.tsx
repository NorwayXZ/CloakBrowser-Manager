import { Banner, FormField, Select } from "../../ui";
import { useRelayNodes } from "./relayApi";

export function RelayRouteFields({ mode, relayId, isSocks, onMode, onRelay }: {
  mode: "direct" | "relay"; relayId?: string | null; isSocks: boolean;
  onMode: (mode: "direct" | "relay") => void; onRelay: (id: string | null) => void;
}) {
  const nodes = useRelayNodes(mode === "relay");
  if (!isSocks && mode !== "relay") return null;
  return <div className="grid gap-3 rounded-md border border-border bg-surface-2 p-4 md:col-span-2 md:grid-cols-2">
    <FormField label="SOCKS5 连接方式" description="只影响这个环境，其他环境可选择不同方式。">
      <Select value={mode} onChange={e => onMode(e.target.value as "direct" | "relay")}>
        <option value="direct">直接连接 SOCKS5</option><option value="relay" disabled={!isSocks}>通过中转服务器</option>
      </Select>
    </FormField>
    {mode === "relay" && <FormField label="中转服务器" description="先到“代理 → 中转服务器”添加加密入口。">
      <Select value={relayId ?? ""} required onChange={e => onRelay(e.target.value || null)}>
        <option value="">请选择中转服务器</option>
        {nodes.data?.map(node => <option key={node.id} value={node.id}>{node.name}</option>)}
      </Select>
    </FormField>}
    {mode === "relay" && <p className="text-xs text-fg-2 md:col-span-2">浏览器 → 加密中转 → 当前 SOCKS5 → 网站。中转失败时停止连接，不自动切换出口。此模式使用 TCP，启动时关闭 QUIC。</p>}
    {mode === "relay" && nodes.isError && <Banner tone="danger">无法读取中转服务器：{nodes.error.message}</Banner>}
  </div>;
}
