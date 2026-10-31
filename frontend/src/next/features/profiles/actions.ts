import { useCallback } from "react";
import { useConfirm, useToast } from "../../ui";
import { profilesApi, useInvalidateProfiles } from "./api";
import { duplicatePayload, isRunning } from "./format";
import type { Profile } from "./types";

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Copy, move to trash (with undo), and burn. Moving to the trash needs no
 * confirmation when nothing is running: the toast offers 撤销 and the trash
 * keeps it for 7 days. Closing a running browser, deleting several, and
 * burning (no way back) always ask first.
 */
export function useProfileActions() {
  const toast = useToast();
  const confirm = useConfirm();
  const invalidate = useInvalidateProfiles();

  const duplicate = useCallback(
    async (profiles: Profile[]) => {
      let made = 0;
      for (const profile of profiles) {
        try {
          await profilesApi.create(duplicatePayload(profile));
          made += 1;
        } catch (error) {
          toast.show({ tone: "error", title: `没能复制「${profile.name}」`, description: message(error) });
        }
      }
      await invalidate();
      if (made > 0) {
        toast.show({ tone: "success", title: profiles.length === 1 ? `已复制为「${profiles[0]!.name} 副本」` : `已复制 ${made} 个环境` });
      }
    },
    [invalidate, toast],
  );

  const trash = useCallback(
    async (profiles: Profile[]): Promise<boolean> => {
      if (profiles.length === 0) return false;
      const running = profiles.filter(isRunning);
      if (profiles.length > 1 || running.length > 0) {
        const ok = await confirm({
          title: profiles.length > 1 ? `把 ${profiles.length} 个环境移到回收站？` : `把「${profiles[0]!.name}」移到回收站？`,
          description: running.length
            ? `其中 ${running.length} 个正在运行，会先被关闭。回收站保留 7 天，期间可以恢复。`
            : "回收站保留 7 天，期间可以恢复。",
          confirmLabel: "移到回收站",
          danger: true,
        });
        if (!ok) return false;
      }
      const removed: Profile[] = [];
      for (const profile of profiles) {
        try {
          await profilesApi.remove(profile.id);
          removed.push(profile);
        } catch (error) {
          toast.show({ tone: "error", title: `没能删除「${profile.name}」`, description: message(error) });
        }
      }
      await invalidate();
      if (removed.length) {
        toast.show({
          tone: "success",
          title: removed.length === 1 ? `「${removed[0]!.name}」已移到回收站` : `${removed.length} 个环境已移到回收站`,
          duration: 8000,
          action: {
            label: "撤销",
            onClick: () => {
              void (async () => {
                const failed: string[] = [];
                for (const profile of removed) {
                  await profilesApi.restore(profile.id).catch(() => failed.push(profile.name));
                }
                await invalidate();
                toast.show(
                  failed.length
                    ? { tone: "error", title: "有环境没能恢复", description: `${failed.join("、")}，可以到“数据 › 回收站”里恢复。` }
                    : { tone: "success", title: "已恢复" },
                );
              })();
            },
          },
        });
      }
      return removed.length > 0;
    },
    [confirm, invalidate, toast],
  );

  const burn = useCallback(
    async (profile: Profile): Promise<boolean> => {
      const ok = await confirm({
        title: `永久删除「${profile.name}」？`,
        description: "永久删除会永久删除这个一次性身份的全部数据（Cookie、登录状态、历史记录和本地文件），不进回收站，不能恢复。",
        confirmLabel: "永久删除",
        danger: true,
      });
      if (!ok) return false;
      try {
        await profilesApi.burn(profile.id);
        toast.show({ tone: "success", title: `「${profile.name}」已永久删除` });
        return true;
      } catch (error) {
        toast.show({ tone: "error", title: "永久删除没有完成", description: message(error) });
        return false;
      } finally {
        await invalidate();
      }
    },
    [confirm, invalidate, toast],
  );

  return { duplicate, trash, burn };
}
