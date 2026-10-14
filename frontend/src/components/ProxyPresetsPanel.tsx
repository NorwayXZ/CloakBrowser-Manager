import { CheckCircle2, Plus, XCircle } from "lucide-react";
import { useState } from "react";
import type { ProxyPreset } from "../lib/api";
import { formatDate } from "../lib/format";
import {
  LINK_PROXY_MODES,
  buildDirectProxyUrl,
  isDirectProxyMode,
  parseProxyBatchLine,
  type ProxyInputMode,
  type ProxyMode,
} from "../lib/proxyInput";

interface ProxyPresetsPanelProps {
  proxyPresets: ProxyPreset[];
  onCreateProxyPreset: (data: { name: string; proxy: string; mode: string }) => Promise<void>;
  onCreateProxyPresets: (items: { name: string; proxy: string; mode: string }[]) => Promise<void>;
  onDeleteProxyPreset: (id: string) => Promise<void>;
}

export function ProxyPresetsPanel({
  proxyPresets,
  onCreateProxyPreset,
  onCreateProxyPresets,
  onDeleteProxyPreset,
}: ProxyPresetsPanelProps) {
  const [proxyName, setProxyName] = useState("");
  const [proxyInputMode, setProxyInputMode] = useState<ProxyInputMode>("single");
  const [proxyMode, setProxyMode] = useState<ProxyMode>("socks5");
  const [proxyHostInput, setProxyHostInput] = useState("");
  const [proxyPortInput, setProxyPortInput] = useState("");
  const [proxyUsernameInput, setProxyUsernameInput] = useState("");
  const [proxyPasswordInput, setProxyPasswordInput] = useState("");
  const [proxyValue, setProxyValue] = useState("");
  const [proxyBatchText, setProxyBatchText] = useState("");
  const [proxyError, setProxyError] = useState<string | null>(null);
  const [proxySaving, setProxySaving] = useState(false);

  const handleDeleteProxyPreset = async (preset: ProxyPreset) => {
    if (!confirm(`确定删除保存代理「${preset.name}」吗？不会影响已经使用这个代理的浏览器。`)) return;
    await onDeleteProxyPreset(preset.id);
  };

  const handleCreateProxyPreset = async () => {
    setProxyError(null);
    const name = proxyName.trim();
    if (!name) {
      setProxyError("请先填写代理名称");
      return;
    }

    const proxy = isDirectProxyMode(proxyMode)
      ? buildDirectProxyUrl(proxyMode, proxyHostInput, proxyPortInput, proxyUsernameInput, proxyPasswordInput)
      : proxyValue.trim();
    if (!proxy) {
      setProxyError(isDirectProxyMode(proxyMode) ? "请填写主机和端口" : "请粘贴代理链接");
      return;
    }

    setProxySaving(true);
    try {
      await onCreateProxyPreset({ name, proxy, mode: proxyMode });
      setProxyName("");
      setProxyHostInput("");
      setProxyPortInput("");
      setProxyUsernameInput("");
      setProxyPasswordInput("");
      setProxyValue("");
    } catch (err) {
      setProxyError(err instanceof Error ? err.message : "保存代理失败");
    } finally {
      setProxySaving(false);
    }
  };

  const handleCreateProxyBatch = async () => {
    setProxyError(null);
    const items = proxyBatchText
      .split(/\r?\n/)
      .reduce<{ name: string; proxy: string; mode: string }[]>((acc, line, index) => {
        const item = parseProxyBatchLine(line, proxyMode, index + 1);
        if (item) acc.push(item);
        return acc;
      }, []);
    if (items.length === 0) {
      setProxyError("没有识别到可保存的代理，请检查格式");
      return;
    }
    setProxySaving(true);
    try {
      await onCreateProxyPresets(items);
      setProxyBatchText("");
    } catch (err) {
      setProxyError(err instanceof Error ? err.message : "批量保存代理失败");
    } finally {
      setProxySaving(false);
    }
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col p-4">
      <div className="mb-4 overflow-hidden rounded-md border border-border bg-white">
        <div className="flex border-b border-border px-5">
          {[
            ["single", "单个添加"],
            ["batch", "批量导入"],
          ].map(([id, label]) => (
            <button
              key={id}
              className={`mr-8 h-12 border-b-2 text-sm font-semibold ${
                proxyInputMode === id
                  ? "border-accent text-accent"
                  : "border-transparent text-slate-500 hover:text-slate-900"
              }`}
              onClick={() => {
                setProxyInputMode(id as ProxyInputMode);
                setProxyError(null);
              }}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="grid gap-5 p-5 xl:grid-cols-[390px_minmax(0,1fr)]">
          <div className="rounded-md border border-blue-100 bg-blue-50 p-4 text-sm leading-6 text-slate-700">
            <div className="mb-2 font-semibold text-slate-900">支持的代理格式</div>
            <div>HTTP / HTTPS / SOCKS5 可分开填写主机、端口、账号、密码。</div>
            <div className="mt-3 font-mono text-xs leading-6 text-blue-700">
              <div>192.168.0.1:8000</div>
              <div>192.168.0.1:8000:user:pass</div>
              <div>socks5://user:pass@192.168.0.1:8000</div>
              <div>http://[2001:db8::1]:8000</div>
              <div>vless://... / vmess://... / trojan://... / ss://...</div>
            </div>
            <div className="mt-3 text-xs text-slate-500">
              同名代理会更新原记录；保存后可在创建/编辑浏览器时直接选择。
            </div>
          </div>

          <div>
            <div className="mb-4 grid gap-3 lg:grid-cols-[minmax(180px,260px)_180px_minmax(180px,1fr)]">
              <div>
                <label className="label">代理名称</label>
                <input
                  className="input h-11"
                  value={proxyName}
                  onChange={(event) => setProxyName(event.target.value)}
                  placeholder="例如 美国 SOCKS5"
                  disabled={proxyInputMode === "batch"}
                />
              </div>
              <div>
                <label className="label">代理类型</label>
                <select
                  className="input h-11"
                  value={proxyMode}
                  onChange={(event) => {
                    setProxyMode(event.target.value as ProxyMode);
                    setProxyError(null);
                  }}
                >
                  <option value="socks5">SOCKS5</option>
                  <option value="http">HTTP</option>
                  <option value="https">HTTPS</option>
                  <option value="vless">VLESS</option>
                  <option value="vmess">VMESS</option>
                  <option value="trojan">TROJAN</option>
                  <option value="ss">Shadowsocks</option>
                </select>
              </div>
              <div>
                <label className="label">检测方式</label>
                <div className="flex h-11 items-center rounded-md border border-slate-300 bg-slate-50 px-3 text-sm text-slate-500">
                  浏览器启动时自动检测出口 IP / 地区
                </div>
              </div>
            </div>

            {proxyInputMode === "single" && isDirectProxyMode(proxyMode) && (
              <div className="space-y-4">
                <div className="grid gap-3 lg:grid-cols-[minmax(220px,1fr)_140px]">
                  <div>
                    <label className="label">主机</label>
                    <input
                      className="input h-11"
                      value={proxyHostInput}
                      onChange={(event) => setProxyHostInput(event.target.value)}
                      placeholder="192.168.100.1 或 proxy.example.com"
                    />
                  </div>
                  <div>
                    <label className="label">端口</label>
                    <input
                      className="input h-11 no-spin"
                      value={proxyPortInput}
                      onChange={(event) => setProxyPortInput(event.target.value)}
                      placeholder="1090"
                    />
                  </div>
                </div>
                <div className="grid gap-3 lg:grid-cols-2">
                  <div>
                    <label className="label">代理账号</label>
                    <input
                      className="input h-11"
                      value={proxyUsernameInput}
                      onChange={(event) => setProxyUsernameInput(event.target.value)}
                      placeholder="没有账号就留空"
                    />
                  </div>
                  <div>
                    <label className="label">代理密码</label>
                    <input
                      className="input h-11"
                      type="password"
                      value={proxyPasswordInput}
                      onChange={(event) => setProxyPasswordInput(event.target.value)}
                      placeholder="没有密码就留空"
                    />
                  </div>
                </div>
                <div className="rounded-md bg-slate-50 px-3 py-2 font-mono text-xs text-slate-500">
                  {buildDirectProxyUrl(proxyMode, proxyHostInput, proxyPortInput, proxyUsernameInput, proxyPasswordInput) || "代理地址会自动拼接显示在这里"}
                </div>
              </div>
            )}

            {proxyInputMode === "single" && LINK_PROXY_MODES.includes(proxyMode) && (
              <div>
                <label className="label">代理链接</label>
                <textarea
                  className="input min-h-32 resize-y font-mono text-xs"
                  value={proxyValue}
                  onChange={(event) => setProxyValue(event.target.value)}
                  placeholder="粘贴 vless://、vmess://、trojan:// 或 ss:// 链接"
                  spellCheck={false}
                />
              </div>
            )}

            {proxyInputMode === "batch" && (
              <div>
                <label className="label">批量代理</label>
                <textarea
                  className="input min-h-48 resize-y font-mono text-xs"
                  value={proxyBatchText}
                  onChange={(event) => setProxyBatchText(event.target.value)}
                  placeholder={"一行一个代理，例如：\n192.168.0.1:8000\n192.168.0.1:8000:user:pass\nsocks5://user:pass@192.168.0.1:8000\nvless://..."}
                  spellCheck={false}
                />
                <div className="mt-2 text-xs text-slate-500">
                  裸 host:port 格式会按上方选择的代理类型保存；完整链接会按链接自己的协议保存。
                </div>
              </div>
            )}

            {proxyError && (
              <div className="mt-4 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
                <XCircle className="h-4 w-4" />
                <span>{proxyError}</span>
              </div>
            )}

            <div className="mt-4 flex items-center gap-3">
              {proxyInputMode === "single" ? (
                <button
                  className="btn-primary flex h-10 items-center gap-1.5 px-5"
                  onClick={() => void handleCreateProxyPreset()}
                  disabled={proxySaving}
                >
                  <Plus className="h-4 w-4" />
                  <span>{proxySaving ? "保存中..." : "保存代理"}</span>
                </button>
              ) : (
                <button
                  className="btn-primary flex h-10 items-center gap-1.5 px-5"
                  onClick={() => void handleCreateProxyBatch()}
                  disabled={proxySaving}
                >
                  <Plus className="h-4 w-4" />
                  <span>{proxySaving ? "保存中..." : "批量保存"}</span>
                </button>
              )}
              <div className="flex items-center gap-1.5 text-xs text-emerald-700">
                <CheckCircle2 className="h-3.5 w-3.5" />
                <span>支持带账号密码的 SOCKS5</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="overflow-hidden rounded-md border border-border bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left font-medium">名称</th>
              <th className="px-4 py-3 text-left font-medium">代理模式</th>
              <th className="px-4 py-3 text-left font-medium">代理地址</th>
              <th className="px-4 py-3 text-left font-medium">创建时间</th>
              <th className="w-32 px-4 py-3 text-left font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {proxyPresets.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-slate-400">
                  暂无保存代理。可以保存“美国 SOCKS5”“香港 VLESS”这类常用代理。
                </td>
              </tr>
            )}
            {proxyPresets.map((preset) => (
              <tr key={preset.id} className="hover:bg-slate-50">
                <td className="border-t border-border px-4 py-3 font-medium">{preset.name}</td>
                <td className="border-t border-border px-4 py-3">
                  <span className="rounded bg-slate-100 px-2 py-1 text-xs font-medium uppercase text-slate-700">
                    {preset.mode}
                  </span>
                </td>
                <td className="max-w-xl truncate border-t border-border px-4 py-3 font-mono text-xs text-slate-600" title={preset.proxy}>
                  {preset.proxy}
                </td>
                <td className="border-t border-border px-4 py-3 text-slate-600">{formatDate(preset.created_at)}</td>
                <td className="border-t border-border px-4 py-3">
                  <button
                    className="btn-secondary px-2.5 text-red-600"
                    onClick={() => void handleDeleteProxyPreset(preset)}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
