import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Cpu, Download, RefreshCw, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Banner, Button, ErrorState, FormField, Input, KeyValueList, Section, Select, Skeleton, Switch, Table, TD, TH, THead, TR, useConfirm, useToast } from "../../ui";
import { useManagerStatus } from "../app/api";
import { formatBytes, message, settingsApi, settingsKeys, useKernel, type KernelLicense, type KernelOverview, type KernelSettings } from "./api";

type Busy = "check" | "update" | "save" | "license-save" | "license-remove" | "delete" | null;
type Notice = { tone: "success" | "info" | "danger"; text: string };

export function licenseText(license: KernelLicense): { label: string; detail: string } {
  switch (license.tier) {
    case "paid":
      return {
        label: `付费授权${license.plan ? `（${license.plan}）` : ""}`,
        detail: `使用 Pro 内核，可以锁定或回退版本${license.expires ? `；到期时间 ${license.expires}` : ""}。`,
      };
    case "free":
      return { label: "免费 GitHub 密钥", detail: "自动使用最新 Pro 内核，但不能锁定版本；同时运行的浏览器数量由官方限制。" };
    case "none":
      return { label: "未登录授权", detail: "使用公开发布的免费内核，版本比 Pro 内核旧。登录免费 GitHub 密钥即可用最新内核。" };
    case "invalid":
      return { label: "授权无效", detail: "密钥未通过官方验证，当前退回免费内核。" };
    default:
      return { label: "授权状态未知", detail: "暂时无法连上授权服务器，按上次结果运行。" };
  }
}

/** 设置 › 浏览器内核: version, license key, update policy and old kernels. */
export function KernelSection() {
  const kernel = useKernel();
  if (kernel.isPending) {
    return (
      <Section id="kernel" title="浏览器内核">
        <Skeleton className="h-40 w-full" />
      </Section>
    );
  }
  if (kernel.isError) {
    return (
      <Section id="kernel" title="浏览器内核">
        <ErrorState title="内核信息没有读出来" message={kernel.error.message} onRetry={() => void kernel.refetch()} retrying={kernel.isFetching} />
      </Section>
    );
  }
  return <KernelPanel info={kernel.data} refreshing={kernel.isFetching} onRefresh={() => void kernel.refetch()} />;
}

function KernelPanel({ info, refreshing, onRefresh }: { info: KernelOverview; refreshing: boolean; onRefresh: () => void }) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();
  const status = useManagerStatus();
  const running = status.data?.running_count ?? info.running_count;
  const [draft, setDraft] = useState<KernelSettings>(info.settings);
  const [keyDraft, setKeyDraft] = useState("");
  const [latest, setLatest] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [licenseError, setLicenseError] = useState<string | null>(null);

  useEffect(() => setDraft(info.settings), [info.settings]);

  const apply = (next: KernelOverview) => queryClient.setQueryData(settingsKeys.kernel, next);
  const reload = () => queryClient.invalidateQueries({ queryKey: settingsKeys.kernel });

  const run = async (kind: Busy, task: () => Promise<Notice | null>) => {
    setBusy(kind);
    setNotice(null);
    try {
      const result = await task();
      if (result) setNotice(result);
    } catch (error) {
      setNotice({ tone: "danger", text: message(error) });
    } finally {
      setBusy(null);
    }
  };

  const check = () =>
    run("check", async () => {
      const result = await settingsApi.checkKernel();
      setLatest(result.latest_version);
      if (result.pinned) return { tone: "info", text: `官方最新版本是 ${result.latest_version}；当前锁定在 ${result.current_version ?? "未知"}。` };
      return result.update_available
        ? { tone: "info", text: `发现新内核 ${result.latest_version}（当前 ${result.current_version ?? "未下载"}），可以点“立即更新”。` }
        : { tone: "success", text: `当前内核 ${result.current_version ?? ""} 已是最新。` };
    });

  const update = () =>
    run("update", async () => {
      const result = await settingsApi.updateKernel();
      await reload();
      void queryClient.invalidateQueries({ queryKey: ["manager", "status"] });
      return { tone: result.updated ? "success" : "info", text: result.message };
    });

  const save = () =>
    run("save", async () => {
      apply(await settingsApi.saveKernelSettings(draft));
      toast.show({ tone: "success", title: "内核设置已保存", description: "下次启动浏览器时生效。" });
      return null;
    });

  const saveLicense = async () => {
    const key = keyDraft.trim();
    if (!key) return;
    setBusy("license-save");
    setLicenseError(null);
    setNotice(null);
    try {
      const overview = await settingsApi.saveLicense(key);
      apply(overview);
      setKeyDraft("");
      const verified = overview.license.tier === "free" || overview.license.tier === "paid";
      setNotice(
        verified
          ? { tone: "success", text: `授权密钥已保存并通过验证：${licenseText(overview.license).label}。下次启动浏览器时使用对应内核；要马上换内核，关掉浏览器后点“立即更新”。` }
          : { tone: "info", text: "授权密钥已保存，但暂时没连上官方服务器验证；下次启动浏览器时会再确认。" },
      );
    } catch (error) {
      // Keep what was typed so a typo can be fixed instead of pasted again.
      setLicenseError(message(error));
    } finally {
      setBusy(null);
    }
  };

  const removeLicense = async () => {
    const ok = await confirm({
      title: "移除保存的授权密钥？",
      description: "之后退回未登录授权的免费内核，下次启动浏览器时生效。",
      confirmLabel: "移除密钥",
      danger: true,
    });
    if (!ok) return;
    await run("license-remove", async () => {
      apply(await settingsApi.removeLicense());
      setKeyDraft("");
      return { tone: "success", text: "已移除保存的授权密钥，下次启动浏览器时生效。" };
    });
  };

  const remove = async (name: string, version: string) => {
    const ok = await confirm({ title: `删除内核 ${version}？`, description: "以后如果需要，会重新下载。", confirmLabel: "删除", danger: true });
    if (!ok) return;
    await run("delete", async () => {
      const result = await settingsApi.deleteKernel(name);
      await reload();
      return { tone: "success", text: `已删除内核 ${version}，释放 ${formatBytes(result.freed_bytes)}。` };
    });
  };

  const license = licenseText(info.license);
  const oldKernels = info.installed_kernels.filter((item) => !item.in_use);
  const reclaimable = oldKernels.reduce((sum, item) => sum + item.size_bytes, 0);
  const changed = JSON.stringify(draft) !== JSON.stringify(info.settings);
  const pinChoices = info.installed_kernels.filter((item) => item.pro === (info.license.tier === "paid"));
  const verified = info.license.tier === "free" || info.license.tier === "paid";

  return (
    <div className="flex flex-col gap-5">
      <Section
        id="kernel"
        title="浏览器内核"
        description="只有“防检测浏览器”引擎使用这个内核；“稳定原生”用电脑上的 Google Chrome，跟着 Chrome 自己更新。更新后，已经打开的浏览器要关掉重开才会用上新内核。"
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent">
                <Cpu className="h-5 w-5" aria-hidden />
              </div>
              <div>
                <div className="text-xs text-fg-3">当前使用的 CloakBrowser 内核</div>
                <div className="mt-0.5 font-mono text-xl font-semibold text-fg">{info.version ?? "未下载"}</div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <Badge tone={verified ? "success" : info.license.tier === "invalid" ? "danger" : "neutral"}>{license.label}</Badge>
                  {info.pinned && <Badge tone="warning">已锁定版本</Badge>}
                  {info.settings.release_channel === "preview" && <Badge tone="info">预览渠道</Badge>}
                  {!info.installed && <Badge tone="warning">首次启动时下载</Badge>}
                </div>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button icon={<RefreshCw className="h-4 w-4" />} loading={busy === "check"} disabled={busy !== null} onClick={() => void check()}>
                检查更新
              </Button>
              <Button variant="primary" icon={<Download className="h-4 w-4" />} loading={busy === "update"} disabled={busy !== null} onClick={() => void update()}>
                {busy === "update" ? "下载并校验中…" : "立即更新"}
              </Button>
            </div>
          </div>
          <div className="rounded-md bg-surface-2 p-3">
            <KeyValueList
              items={[
                { label: "授权", value: license.detail },
                { label: "官方最新", value: latest ?? "点“检查更新”查看" },
                { label: "平台", value: info.platform ?? "未知" },
                { label: "Wrapper", value: `${info.wrapper_version ?? "未知"}（随 Manager 安装包更新）` },
              ]}
            />
          </div>
          {notice && (
            <Banner tone={notice.tone}>
              <span className="whitespace-pre-line">{notice.text}</span>
            </Banner>
          )}
        </div>
      </Section>

      <Section id="license" title="授权密钥">
        <div className="flex flex-col gap-3">
          <p className="text-sm text-fg-2">
            {info.license.key_stored
              ? `已保存授权密钥（内容不显示），当前授权：${license.label}。更换时在下面输入新密钥保存；新密钥验证不通过时，不会覆盖现有密钥。`
              : verified
                ? "当前授权来自环境变量 CLOAKBROWSER_LICENSE_KEY，不是面板保存的，面板里保存的密钥不会生效。要改用面板管理，请先移除该环境变量并重启 Manager。"
                : "还没有保存授权密钥。免费密钥可在 cloakbrowser.dev/free 用 GitHub 账号领取；粘贴到下面保存后会立即向官方验证，通过即可使用最新内核。"}
          </p>
          <form
            className="flex flex-wrap items-start gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void saveLicense();
            }}
          >
            <FormField label="CloakBrowser 授权密钥" error={licenseError} className="min-w-64 flex-1">
              <Input
                type="password"
                mono
                placeholder="cb_…"
                autoComplete="off"
                spellCheck={false}
                value={keyDraft}
                onChange={(event) => {
                  setKeyDraft(event.target.value);
                  setLicenseError(null);
                }}
              />
            </FormField>
            <div className="flex gap-2 sm:pt-6">
              <Button type="submit" variant="primary" icon={<Save className="h-4 w-4" />} loading={busy === "license-save"} disabled={busy !== null || !keyDraft.trim()}>
                {busy === "license-save" ? "验证并保存中…" : info.license.key_stored ? "更换密钥" : "保存密钥"}
              </Button>
              {info.license.key_stored && (
                <Button variant="danger-ghost" icon={<Trash2 className="h-4 w-4" />} loading={busy === "license-remove"} disabled={busy !== null} onClick={() => void removeLicense()}>
                  移除密钥
                </Button>
              )}
            </div>
          </form>
          <p className="text-xs text-fg-3">密钥只保存在运行 Manager 的这台电脑上（CloakBrowser 密钥文件），不会显示在面板里，也不会写进环境或备份。</p>
        </div>
      </Section>

      <Section id="kernel-updates" title="更新方式">
        <div className="flex flex-col gap-4">
          <Switch
            checked={draft.auto_update}
            onCheckedChange={(auto_update) => setDraft({ ...draft, auto_update })}
            label="启动浏览器时自动下载新内核"
            description="关闭后一直用已下载的版本，需要时到这里手动更新。"
          />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField label="更新渠道" description="预览版更早拿到新 Chrome 版本，但可能不稳定；没有预览版时自动用稳定版。">
              <Select value={draft.release_channel} onChange={(event) => setDraft({ ...draft, release_channel: event.target.value as KernelSettings["release_channel"] })}>
                <option value="stable">稳定版（推荐）</option>
                <option value="preview">预览版</option>
              </Select>
            </FormField>
            <FormField
              label="锁定版本"
              description={info.license.can_pin ? "新内核出问题时，可以锁定到一个已下载的旧版本；锁定期间不会自动更新。" : "免费 GitHub 密钥总是使用最新内核，官方不允许锁定版本。"}
            >
              <Select value={draft.pinned_version ?? ""} disabled={!info.license.can_pin} onChange={(event) => setDraft({ ...draft, pinned_version: event.target.value || null })}>
                <option value="">不锁定，跟随最新</option>
                {pinChoices.map((item) => (
                  <option key={item.name} value={item.version}>
                    {item.version}
                  </option>
                ))}
                {draft.pinned_version && !pinChoices.some((item) => item.version === draft.pinned_version) && <option value={draft.pinned_version}>{draft.pinned_version}</option>}
              </Select>
            </FormField>
          </div>
          <div>
            <Button variant="primary" icon={<Save className="h-4 w-4" />} loading={busy === "save"} disabled={busy !== null || !changed} onClick={() => void save()}>
              保存设置
            </Button>
          </div>
        </div>
      </Section>

      <Section
        id="kernel-versions"
        title="已下载的内核"
        description={oldKernels.length > 0 ? `${oldKernels.length} 个旧版本没在用，共 ${formatBytes(reclaimable)}，可以删除释放空间。` : "没有可清理的旧版本。"}
        actions={
          <Button size="sm" icon={<RefreshCw className="h-4 w-4" />} loading={refreshing} onClick={onRefresh}>
            刷新
          </Button>
        }
      >
        {info.installed_kernels.length === 0 ? (
          <p className="text-sm text-fg-2">还没有下载内核，第一次启动防检测浏览器时会自动下载。</p>
        ) : (
          <Table label="已下载的内核">
            <THead>
              <TR>
                <TH>版本</TH>
                <TH className="w-28 text-right">大小</TH>
                <TH className="w-28">
                  <span className="sr-only">操作</span>
                </TH>
              </TR>
            </THead>
            <tbody>
              {info.installed_kernels.map((item) => (
                <TR key={item.name}>
                  <TD>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono font-medium text-fg">{item.version}</span>
                      <Badge>{item.pro ? "Pro" : "免费版"}</Badge>
                      {item.in_use && (
                        <Badge tone="success">
                          <CheckCircle2 className="h-3 w-3" aria-hidden />
                          正在使用
                        </Badge>
                      )}
                    </div>
                  </TD>
                  <TD className="tabular text-right text-fg-2">{formatBytes(item.size_bytes)}</TD>
                  <TD className="text-right">
                    {!item.in_use && (
                      <Button
                        size="sm"
                        variant="danger-ghost"
                        icon={<Trash2 className="h-3.5 w-3.5" />}
                        disabled={busy !== null || running > 0}
                        title={running > 0 ? "请先关闭所有浏览器" : undefined}
                        aria-label={`删除内核 ${item.version}`}
                        onClick={() => void remove(item.name, item.version)}
                      >
                        删除
                      </Button>
                    )}
                  </TD>
                </TR>
              ))}
            </tbody>
          </Table>
        )}
        {running > 0 && oldKernels.length > 0 && <p className="mt-2 text-xs text-fg-3">有浏览器在运行，关闭全部浏览器后才能删除旧内核。</p>}
        <p className="mt-3 break-all text-xs text-fg-3">位置：{info.cache_dir}</p>
      </Section>
    </div>
  );
}
