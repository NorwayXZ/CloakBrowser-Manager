import { useQueryClient } from "@tanstack/react-query";
import { ArchiveRestore, Trash2 } from "lucide-react";
import { useState } from "react";
import { Banner, Button, EmptyState, ErrorState, Skeleton, Table, TD, TH, THead, TR, useConfirm, useToast } from "../../ui";
import { profileKeys } from "../profiles/api";
import { formatDateTime, groupOf } from "../profiles/format";
import type { Profile } from "../profiles/types";
import { dataApi, dataKeys, daysLeft, useTrash } from "./api";

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

/** Profiles deleted in the last 7 days: restore them, or delete them for good. */
export function TrashTab() {
  const trash = useTrash();
  const queryClient = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = () =>
    Promise.all([queryClient.invalidateQueries({ queryKey: dataKeys.trash }), queryClient.invalidateQueries({ queryKey: profileKeys.list })]);

  const restore = async (profile: Profile) => {
    setBusy(profile.id);
    try {
      await dataApi.restoreProfile(profile.id);
      toast.show({ tone: "success", title: `已恢复「${profile.name}」`, description: "它回到了环境列表。" });
    } catch (error) {
      toast.show({ tone: "error", title: "没有恢复", description: message(error) });
    } finally {
      setBusy(null);
      await refresh();
    }
  };

  const purge = async (profile: Profile) => {
    const ok = await confirm({
      title: `彻底删除「${profile.name}」？`,
      description: "浏览器数据、Cookie 和登录状态会一起删除，不能恢复。",
      confirmLabel: "彻底删除",
      danger: true,
    });
    if (!ok) return;
    setBusy(profile.id);
    try {
      await dataApi.purge(profile.id);
      toast.show({ tone: "success", title: `已彻底删除「${profile.name}」` });
    } catch (error) {
      toast.show({ tone: "error", title: "没有删除", description: message(error) });
    } finally {
      setBusy(null);
      await refresh();
    }
  };

  if (trash.isPending) return <Skeleton className="h-40 w-full max-w-form" />;
  if (trash.isError) return <ErrorState message={trash.error.message} onRetry={() => void trash.refetch()} />;

  return (
    <div className="flex max-w-form flex-col gap-4">
      <Banner tone="info">删除的环境在回收站保留 7 天，到期自动清理；这期间可以恢复，也可以彻底删除。</Banner>
      {trash.data.length === 0 ? (
        <div className="rounded-md border border-dashed border-border-strong bg-surface">
          <EmptyState icon={Trash2} title="回收站是空的" description="在环境列表里移到回收站的环境会出现在这里。" />
        </div>
      ) : (
        <Table label="回收站" minWidth={560}>
          <colgroup>
            <col />
            <col className="w-28" />
            <col className="w-32" />
            <col className="w-24" />
            <col className="w-52" />
          </colgroup>
          <THead>
            <tr>
              <TH>名称</TH>
              <TH>分组</TH>
              <TH>删除时间</TH>
              <TH>剩余</TH>
              <TH className="text-right">操作</TH>
            </tr>
          </THead>
          <tbody>
            {trash.data.map((profile) => {
              const left = daysLeft(profile.deleted_at);
              return (
                <TR key={profile.id}>
                  <TD className="truncate font-medium" title={profile.name}>
                    {profile.name}
                  </TD>
                  <TD className="truncate text-fg-2">{groupOf(profile)}</TD>
                  <TD className="text-fg-2">{formatDateTime(profile.deleted_at)}</TD>
                  <TD className={left !== null && left <= 1 ? "text-warning" : "text-fg-2"}>{left === null ? "—" : left === 0 ? "今天清理" : `${left} 天`}</TD>
                  <TD className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button size="sm" icon={<ArchiveRestore className="h-3.5 w-3.5" />} loading={busy === profile.id} disabled={busy !== null} onClick={() => void restore(profile)} aria-label={`恢复「${profile.name}」`}>
                        恢复
                      </Button>
                      <Button size="sm" variant="danger-ghost" icon={<Trash2 className="h-3.5 w-3.5" />} disabled={busy !== null} onClick={() => void purge(profile)} aria-label={`彻底删除「${profile.name}」`}>
                        彻底删除
                      </Button>
                    </div>
                  </TD>
                </TR>
              );
            })}
          </tbody>
        </Table>
      )}
    </div>
  );
}
