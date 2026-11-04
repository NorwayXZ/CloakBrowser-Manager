import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Banner, Button, Dialog, Segmented, useToast } from "../../ui";
import { profilesApi, useInvalidateProfiles } from "./api";
import { isRunning, proxyHost } from "./format";
import type { Profile, ResetBindings, ResetResult } from "./types";

const BINDING_CHOICES: [ResetBindings, string][] = [
  ["unbind", "保留并解绑"],
  ["keep", "继续绑定"],
  ["delete", "删除记录"],
];

const BINDING_HINTS: Record<ResetBindings, string> = {
  unbind: "记录留在“邮箱”和“设置 › 保险库”里，但不再属于这个环境；之后注册会发新的邮箱地址。",
  keep: "仍然绑定在这个环境，重置后还能用同一个邮箱和账号。",
  delete: "从 Manager 里删除这些邮箱地址和账号密码（邮箱服务器上的信箱不动）。",
};

/**
 * 一键重置环境: the same profile becomes a brand-new browser. Says plainly
 * what is deleted for good, what is regenerated and what stays (the proxy),
 * and asks what to do with the profile's mail addresses and vault entries.
 */
export function ResetProfileDialog({
  profile,
  onClose,
  onDone,
}: {
  profile: Profile;
  onClose: () => void;
  onDone?: (result: ResetResult) => void;
}) {
  const toast = useToast();
  const invalidate = useInvalidateProfiles();
  const [bindings, setBindings] = useState<ResetBindings>("unbind");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const linked = useQuery({ queryKey: ["profiles", profile.id, "bindings"], queryFn: () => profilesApi.bindings(profile.id), staleTime: 0 });
  const running = isRunning(profile);
  const mail = linked.data?.mail ?? 0;
  const vault = linked.data?.vault ?? 0;

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await profilesApi.reset(profile.id, bindings);
      await invalidate();
      toast.show({
        tone: "success",
        title: `「${profile.name}」已重置为全新环境`,
        description: `新指纹种子 ${result.new_fingerprint_seed}，代理保留。`,
      });
      onDone?.(result);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && !busy && onClose()}
      dismissible={!busy}
      title={`把「${profile.name}」重置为全新环境？`}
      description="Cookie、登录状态、历史全部删除，不可恢复；代理保留。"
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button variant="danger" loading={busy} onClick={() => void run()} autoFocus>
            重置环境
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3 text-sm text-fg-2">
        {running && <Banner tone="warning">环境正在运行，会先正常关闭浏览器再重置。</Banner>}
        <dl className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-3 gap-y-2">
          <dt className="font-medium text-danger">删除</dt>
          <dd>Cookie、登录状态、保存的密码、历史记录、缓存、LocalStorage / IndexedDB、Service Worker，以及导入的 Cookie。</dd>
          <dt className="font-medium text-fg">重新生成</dt>
          <dd>指纹种子、设备型号、分辨率、显卡、CPU、内存、UA；时区和语言改为按代理出口 IP 自动匹配。</dd>
          <dt className="font-medium text-success">保留</dt>
          <dd>
            代理{profile.proxy ? `（${proxyHost(profile)}）` : ""}和换 IP 链接、名称、分组、备注、标签。
          </dd>
        </dl>
        {linked.isPending && <p className="text-fg-3">正在查看绑定的邮箱和账号…</p>}
        {(mail > 0 || vault > 0) && (
          <div className="flex flex-col gap-2 rounded-md border border-border px-3 py-2.5">
            <p className="text-fg">
              这个环境绑定了 {[mail > 0 && `${mail} 个邮箱地址`, vault > 0 && `${vault} 个保险库账号`].filter(Boolean).join("、")}：
            </p>
            <Segmented label="邮箱和保险库账号怎么处理" value={bindings} options={BINDING_CHOICES} onChange={setBindings} />
            <p className="text-fg-3">{BINDING_HINTS[bindings]}</p>
          </div>
        )}
        {error && <Banner tone="danger" title="重置没有完成">{error}</Banner>}
      </div>
    </Dialog>
  );
}
