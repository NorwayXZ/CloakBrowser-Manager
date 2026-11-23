import { ArrowLeftRight, Wifi } from "lucide-react";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { maskProxy } from "../../shared/lib/mask";
import { Banner, Button, Dialog, FormField, Input, Segmented, Select, Textarea, useToast } from "../../ui";
import { editorApi, useProxyPresets } from "../editor/api";
import { parseProxy, proxyFromParts, type ProxyKind, type ProxyParts, type ProxyScheme } from "../editor/model";
import type { ProxyTestResult } from "../editor/types";
import { RelayRouteFields } from "../proxies/RelayRouteFields";
import { profileKeys, profilesApi } from "./api";
import { isRunning, locationText, proxyHost } from "./format";
import type { Profile } from "./types";

function initialParts(raw?: string | null): ProxyParts {
  const parsed = parseProxy(raw);
  if (parsed.kind === "none") {
    return { ...parsed, scheme: "socks5" };
  }
  return parsed;
}

export function SwitchProxyDialog({ profile, onClose }: { profile: Profile; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const presetsQuery = useProxyPresets();
  const presets = presetsQuery.data ?? [];

  const [parts, setParts] = useState<ProxyParts>(() => initialParts(profile.proxy));
  const [proxyId, setProxyId] = useState<string | null>(profile.proxy_id ?? null);
  const [routeMode, setRouteMode] = useState<"direct" | "relay">(profile.proxy_connection_mode ?? "direct");
  const [relayId, setRelayId] = useState<string | null>(profile.relay_id ?? null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<ProxyTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const running = isRunning(profile);
  const startedWithProxy = Boolean(profile.proxy);
  const nextProxy = proxyFromParts(parts);
  const needsAddress = parts.kind !== "none" && !nextProxy;

  const updateParts = (next: ProxyParts) => {
    setParts(next);
    setProxyId(null);
    if (next.kind !== "custom" || next.scheme !== "socks5") {
      setRouteMode("direct");
      setRelayId(null);
    }
    setTestResult(null);
    setError(null);
  };

  const onHostChange = (value: string) => {
    const trimmed = value.trim();
    // Allow pasting full socks5://user:pass@host:port or host:port:user:pass straight into Host
    if (trimmed.includes("://") || trimmed.split(":").length >= 2) {
      const parsed = parseProxy(trimmed);
      if (parsed.kind === "xray") {
        updateParts(parsed);
        return;
      }
      if (parsed.kind === "custom" && parsed.host && parsed.port) {
        updateParts({
          ...parsed,
          scheme: trimmed.includes("://") ? parsed.scheme : parts.scheme,
        });
        return;
      }
    }
    updateParts({ ...parts, host: value });
  };

  const selectPreset = (selectedId: string) => {
    const preset = presets.find((item) => item.id === selectedId);
    if (!preset) return;
    const parsed = parseProxy(preset.proxy);
    setParts(parsed);
    setProxyId(preset.id);
    if (!preset.proxy.toLowerCase().startsWith("socks5://")) {
      setRouteMode("direct");
      setRelayId(null);
    }
    setTestResult(null);
    setError(null);
  };

  const checkProxy = async () => {
    if (needsAddress) {
      setError("请先填写完整的代理主机和端口");
      return;
    }
    setTesting(true);
    setError(null);
    setTestResult(null);
    try {
      const res = await editorApi.testProxy(
        nextProxy,
        routeMode === "relay" ? { proxy_connection_mode: "relay", relay_id: relayId } : undefined,
      );
      setTestResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "代理测试失败");
    } finally {
      setTesting(false);
    }
  };

  const submit = async () => {
    if (saving) return;
    if (needsAddress) {
      setError("请先填写完整的代理主机和端口");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await profilesApi.switchProxy(profile.id, {
        proxy: nextProxy,
        proxy_id: proxyId,
        proxy_connection_mode: routeMode,
        relay_id: routeMode === "relay" ? relayId : null,
      });
      queryClient.setQueryData<Profile[]>(profileKeys.list, (list) =>
        list ? list.map((p) => (p.id === res.profile.id ? res.profile : p)) : list,
      );
      void queryClient.invalidateQueries({ queryKey: profileKeys.list });

      const exitSummary = [res.proxy_geo?.country, res.proxy_geo?.ip].filter(Boolean).join(" · ");
      if (res.applied_live) {
        toast.show({
          tone: "success",
          title: `已实时切换「${profile.name}」的代理`,
          description: exitSummary
            ? `新出口 ${exitSummary} —— 无需关闭窗口，回浏览器刷新网页（⌘R）即刻生效！`
            : "无需关闭窗口，回浏览器刷新网页（⌘R）即刻生效！",
        });
      } else if (res.requires_restart) {
        toast.show({
          tone: "info",
          title: `已保存「${profile.name}」的新代理`,
          description: "该浏览器本次是以直连打开的，重开一次接入代理通道后，后续即可随时中途热切。",
        });
      } else {
        toast.show({
          tone: "success",
          title: `已更新「${profile.name}」的代理`,
          description: nextProxy ? maskProxy(nextProxy) : "已改为直连",
        });
      }
      onClose();
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "切换代理失败，请检查代理是否可用");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && !saving && onClose()}
      title={`切换代理 · ${profile.name}`}
      description={`当前出口：${proxyHost(profile)}（${locationText(profile)}）`}
      footer={
        <>
          <Button variant="ghost" disabled={saving} onClick={onClose}>
            取消
          </Button>
          <Button
            variant="primary"
            icon={<ArrowLeftRight className="h-3.5 w-3.5" />}
            loading={saving}
            disabled={testing || needsAddress}
            onClick={() => void submit()}
          >
            {running && startedWithProxy ? "立即热切" : "保存切换"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3.5">
        {running && startedWithProxy && (
          <Banner tone="info" title="免关窗实时切换">
            点「立即热切」不会关闭当前浏览器；切完回网页直接按刷新（⌘R），出口就会立刻变成新代理。
          </Banner>
        )}
        {running && !startedWithProxy && (
          <Banner tone="warning" title="首次从直连切入需重开一次">
            当前窗口是以「直连」启动的；本次保存后重开一次浏览器接入代理网关，之后中途换任何 SOCKS5 都无需再关窗。
          </Banner>
        )}

        <FormField label="已保存代理" description="可直接选用在「代理」页存好的节点。">
          <Select value={proxyId ?? ""} onChange={(e) => selectPreset(e.target.value)} disabled={saving || testing}>
            <option value="">{presets.length ? "选择已保存的代理…" : "暂无已保存代理（可在下方直接填写或粘贴）"}</option>
            {presets.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.name} · {preset.mode.toUpperCase()}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label="代理方式">
          <Segmented<ProxyKind>
            label="代理方式"
            value={parts.kind}
            onChange={(kind) =>
              updateParts({
                ...parts,
                kind,
                scheme: kind === "custom" && parts.kind === "none" ? "socks5" : parts.scheme,
                raw: kind === "xray" ? parts.raw : "",
              })
            }
            options={[
              ["custom", "SOCKS5 / HTTP"],
              ["xray", "Xray 链接"],
              ["none", "直连"],
            ]}
          />
        </FormField>

        {parts.kind === "none" ? (
          <Banner tone="success" title="切换为本机直连">
            浏览器将直接走本机网络出口，不再经过上级代理。
          </Banner>
        ) : parts.kind === "xray" ? (
          <FormField label="代理链接" description="粘贴 vless://、vmess://、ss:// 或 trojan:// 链接。">
            <Textarea
              mono
              rows={3}
              className="text-xs"
              spellCheck={false}
              disabled={saving || testing}
              value={parts.raw}
              placeholder="粘贴 ss://、vmess://、vless:// 或 trojan:// 链接"
              onChange={(e) => updateParts({ ...parts, raw: e.target.value })}
            />
          </FormField>
        ) : (
          <>
            <FormField label="协议类型">
              <Select
                value={parts.scheme}
                disabled={saving || testing}
                onChange={(e) => updateParts({ ...parts, scheme: e.target.value as ProxyScheme })}
              >
                <option value="socks5">SOCKS5</option>
                <option value="http">HTTP</option>
                <option value="https">HTTPS</option>
              </Select>
            </FormField>
            <FormField label="主机与端口" description="支持直接把整串 socks5://账号:密码@IP:端口 或 IP:端口:账号:密码 粘贴进主机框自动拆分。">
              <div className="grid grid-cols-[minmax(0,1fr)_96px] gap-2">
                <Input
                  mono
                  disabled={saving || testing}
                  value={parts.host}
                  placeholder="例如 sg.proxy.example.com"
                  onChange={(e) => onHostChange(e.target.value)}
                />
                <Input
                  mono
                  aria-label="端口"
                  inputMode="numeric"
                  disabled={saving || testing}
                  value={parts.port}
                  placeholder="1080"
                  onChange={(e) => updateParts({ ...parts, port: e.target.value })}
                />
              </div>
            </FormField>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <FormField label="代理账号">
                <Input
                  disabled={saving || testing}
                  value={parts.username}
                  placeholder="可选"
                  autoComplete="off"
                  onChange={(e) => updateParts({ ...parts, username: e.target.value })}
                />
              </FormField>
              <FormField label="代理密码">
                <Input
                  type="password"
                  disabled={saving || testing}
                  value={parts.password}
                  placeholder="可选"
                  autoComplete="new-password"
                  onChange={(e) => updateParts({ ...parts, password: e.target.value })}
                />
              </FormField>
            </div>
          </>
        )}

        <RelayRouteFields
          mode={routeMode}
          relayId={relayId}
          isSocks={parts.kind === "custom" && parts.scheme === "socks5"}
          onMode={(m) => {
            setRouteMode(m);
            if (m === "direct") setRelayId(null);
            setTestResult(null);
            setError(null);
          }}
          onRelay={(id) => {
            setRelayId(id);
            setTestResult(null);
            setError(null);
          }}
        />

        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            icon={<Wifi className="h-3.5 w-3.5" />}
            loading={testing}
            disabled={saving || needsAddress}
            onClick={() => void checkProxy()}
          >
            {parts.kind === "none" ? "检测直连出口" : "先测一下新代理"}
          </Button>
          {nextProxy && <span className="truncate font-mono text-xs text-fg-3">{maskProxy(nextProxy)}</span>}
        </div>

        {error && <Banner tone="danger">{error}</Banner>}
        {testResult && (
          <div className="rounded-md border border-success/30 bg-success-soft p-2.5 text-xs text-fg">
            出口 IP：<span className="font-mono font-medium">{testResult.ip ?? "未知"}</span>
            {" · "}国家：{testResult.country ?? "未知"}
            {testResult.timezone ? ` · 时区：${testResult.timezone}` : ""}
            {testResult.handshake_ms != null ? ` · 握手 ${testResult.handshake_ms} ms` : ""}
          </div>
        )}
      </div>
    </Dialog>
  );
}
