import { Globe, Wifi } from "lucide-react";
import { useState } from "react";
import { cn } from "../../../shared/lib/cn";
import { maskProxy } from "../../../shared/lib/mask";
import { Banner, Button, Checkbox, FormField, Hint, Input, Section, Segmented, Select, Textarea } from "../../../ui";
import { editorApi } from "../api";
import { BROWSER_LANGUAGES, type ProxyKind, type ProxyScheme } from "../model";
import type { IpQuality, IpQualityStatus, ProxyPreset } from "../types";
import type { Editor } from "../useEditor";

const IP_QUALITY: Record<IpQualityStatus, { label: string; box: string }> = {
  flagged: { label: "已被标记", box: "border-danger/30 bg-danger-soft" },
  suspicious: { label: "有风险", box: "border-warning/30 bg-warning-soft" },
  clean: { label: "未标记", box: "border-success/30 bg-success-soft" },
  unknown: { label: "无法判断", box: "border-border bg-surface-2" },
};

export function IpQualityPanel({ quality }: { quality: IpQuality }) {
  const style = IP_QUALITY[quality.verdict];
  return (
    <div data-testid="ip-quality" className={cn("rounded-md border p-3 text-sm", style.box)}>
      <div className="font-medium text-fg">IP 质量：{style.label}</div>
      <p className="mt-1 text-fg-2">{quality.summary}</p>
      <ul className="mt-2 flex flex-col gap-0.5 text-xs text-fg-2">
        {quality.signals.map((signal) => (
          <li key={signal.source}>
            {signal.source}：{IP_QUALITY[signal.status].label} · {signal.detail}
          </li>
        ))}
      </ul>
      {quality.links.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-2">
          <span>手动再查：</span>
          {quality.links.map((link) => (
            <a key={link.name} href={link.url} target="_blank" rel="noreferrer" className="text-accent underline">
              {link.name}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

export function ProxySection({ editor, presets }: { editor: Editor; presets: ProxyPreset[] }) {
  const { form, proxyParts, proxyTest, proxyTestError } = editor;
  const [testing, setTesting] = useState(false);
  const needsAddress = proxyParts.kind !== "none" && !form.proxy;

  const check = async () => {
    if (needsAddress) {
      editor.proxyCheckFailed("请先填写代理主机和端口");
      return;
    }
    setTesting(true);
    try {
      editor.proxyChecked(await editorApi.testProxy(form.proxy ?? null));
    } catch (error) {
      editor.proxyCheckFailed(error instanceof Error ? error.message : "代理测试失败");
    } finally {
      setTesting(false);
    }
  };

  return (
    <Section id="form-proxy" title="代理信息" description="直连使用这台电脑的网络，不启动代理或 Xray。HTTP / HTTPS / SOCKS5 填主机和端口；VLESS、VMess、Trojan、Shadowsocks 粘贴链接。">
      <div className="grid max-w-form grid-cols-1 gap-4 md:grid-cols-2">
        <FormField label="代理方式" className="md:col-span-2" description="自定义代理适合 HTTP/HTTPS/SOCKS5；Xray 链接会在本机启动内核，转成一个本机 SOCKS5。">
          <Segmented<ProxyKind>
            label="代理方式"
            value={proxyParts.kind}
            onChange={editor.setProxyKind}
            options={[
              ["none", "直连"],
              ["custom", "自定义代理"],
              ["xray", "Xray 链接"],
            ]}
          />
        </FormField>
        <FormField label="已保存代理" className="md:col-span-2" description="在“代理”页保存的代理，选中后填入这个环境。">
          <Select
            value=""
            onChange={(event) => {
              const preset = presets.find((item) => item.id === event.target.value);
              if (preset) editor.usePreset(preset.proxy);
            }}
          >
            <option value="">{presets.length ? "选择保存的代理…" : "还没有保存的代理"}</option>
            {presets.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.name} · {preset.mode.toUpperCase()}
              </option>
            ))}
          </Select>
        </FormField>

        {proxyParts.kind === "none" ? (
          <div className="md:col-span-2">
            <Banner tone="success" title="直连已启用">
              浏览器直接使用这台电脑的网络出口，不经过已保存的代理，也不会启动 Xray。
            </Banner>
          </div>
        ) : proxyParts.kind === "xray" ? (
          <FormField label="代理链接" className="md:col-span-2" description="启动时为这个环境建一条独立的本机 SOCKS5 通道。">
            <Textarea mono rows={3} className="text-xs" spellCheck={false} value={proxyParts.raw} placeholder="粘贴 ss://、vmess://、vless:// 或 trojan:// 链接" onChange={(event) => editor.setProxyPart("raw", event.target.value)} />
          </FormField>
        ) : (
          <>
            <FormField label="代理类型" description="带账号密码的 SOCKS5 会自动走本机桥接，避免 Chrome 认证不稳定。">
              <Select value={proxyParts.scheme} onChange={(event) => editor.setProxyPart("scheme", event.target.value as ProxyScheme)}>
                <option value="http">HTTP</option>
                <option value="https">HTTPS</option>
                <option value="socks5">SOCKS5</option>
              </Select>
            </FormField>
            <div className="grid grid-cols-[minmax(0,1fr)_96px] gap-2">
              <FormField label="主机">
                <Input mono value={proxyParts.host} placeholder="192.168.100.1" onChange={(event) => editor.setProxyPart("host", event.target.value)} />
              </FormField>
              <FormField label="端口">
                <Input mono inputMode="numeric" value={proxyParts.port} placeholder="1090" onChange={(event) => editor.setProxyPart("port", event.target.value)} />
              </FormField>
            </div>
            <FormField label="代理账号" description="没有认证就留空；会自动拼进代理地址。">
              <Input value={proxyParts.username} placeholder="可选" autoComplete="off" onChange={(event) => editor.setProxyPart("username", event.target.value)} />
            </FormField>
            <FormField label="代理密码" description="保存后加密存进本机的配置数据库。">
              <Input type="password" value={proxyParts.password} placeholder="可选" autoComplete="new-password" onChange={(event) => editor.setProxyPart("password", event.target.value)} />
            </FormField>
          </>
        )}

        <div className="flex flex-col gap-2 md:col-span-2">
          <span className="text-sm font-medium text-fg">出口检测</span>
          <div className="flex flex-wrap items-center gap-2">
            <Button icon={<Wifi className="h-3.5 w-3.5" />} loading={testing} disabled={needsAddress} onClick={() => void check()}>
              {proxyParts.kind === "none" ? "检查直连出口" : "检查代理"}
            </Button>
            <span className="min-w-0 break-all font-mono text-xs text-fg-3">{form.proxy ? maskProxy(form.proxy) : "用这台电脑的网络检测公网 IP、国家、时区和语言"}</span>
          </div>
          <p className="text-xs text-fg-3">保存前可以先查一次；启动时还会重新检测。时区、语言留空时会自动补全，开启“跟随出口 IP”时会覆盖手填的值。</p>
          {proxyTestError && <Banner tone="danger">{proxyTestError}</Banner>}
          {proxyTest && (
            <div className="rounded-md border border-success/30 bg-success-soft p-3 text-sm text-fg">
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                <span>
                  出口 IP：<span className="font-mono">{proxyTest.ip ?? "未知"}</span>
                </span>
                <span>国家：{proxyTest.country ?? "未知"}</span>
                <span>时区：{proxyTest.timezone ?? "未知"}</span>
                <span>建议语言：{proxyTest.suggested_locale ?? "未知"}</span>
              </div>
              <Button size="sm" variant="ghost" className="mt-1.5 -ml-2 text-accent" icon={<Globe className="h-3.5 w-3.5" />} disabled={!proxyTest.timezone && !proxyTest.suggested_locale} onClick={editor.applyProxyGeo}>
                应用到时区和语言
              </Button>
            </div>
          )}
          {proxyTest?.ip_quality && <IpQualityPanel quality={proxyTest.ip_quality} />}
        </div>

        <FormField label="时区" description="IANA 时区，例如 Asia/Hong_Kong；留空按出口 IP 补全。">
          <Input mono value={form.timezone ?? ""} placeholder="Asia/Shanghai" onChange={(event) => editor.set("timezone", event.target.value || null)} />
        </FormField>
        <FormField label="语言区域" description="浏览器语言，例如 zh-HK；留空按出口 IP 补全。">
          <Input mono value={form.locale ?? ""} placeholder="zh-CN" onChange={(event) => editor.set("locale", event.target.value || null)} />
        </FormField>
        <div className="md:col-span-2">
          <Checkbox
            checked={form.geoip ?? false}
            onCheckedChange={(value) => editor.set("geoip", value)}
            label="根据出口 IP 自动匹配时区和语言区域"
            description="直连和代理都适用。勾选后覆盖手填的值；不勾选时，只要时区或语言留空，启动时也会按出口地区补全。"
          />
        </div>
        <FormField
          label="浏览器语言"
          className="md:col-span-2"
          description={
            <Hint>
              想看懂菜单和设置页时选中文：浏览器界面、网页读到的语言和日期格式会一起换成中文，时区仍按出口 IP。只换界面、网页语言不变会被检测网站判为语言不一致，所以三者一起换。也可以在浏览器设置页“语言”里加中文：放在第一位后浏览器会在几秒内自动重启并恢复标签页；放在后面只作备用语言。
            </Hint>
          }
        >
          <Select value={form.fingerprint_options?.language ?? ""} onChange={(event) => editor.setOption("language", event.target.value || null)}>
            {BROWSER_LANGUAGES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </FormField>
      </div>
    </Section>
  );
}
