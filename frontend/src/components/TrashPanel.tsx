import type { Profile } from "../lib/api";
import { formatDate } from "../lib/format";

interface TrashPanelProps {
  trashProfiles: Profile[];
  onRestoreProfile: (id: string) => Promise<void>;
  onPurgeProfile: (id: string) => Promise<void>;
}

export function TrashPanel({ trashProfiles, onRestoreProfile, onPurgeProfile }: TrashPanelProps) {
  const handlePurgeProfile = async (profile: Profile) => {
    if (!confirm(`确定彻底删除「${profile.name}」吗？此操作不可恢复。`)) return;
    await onPurgeProfile(profile.id);
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col p-4">
      <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        删除后的浏览器会进入回收站，保留 7 天；可以恢复，也可以彻底删除。
      </div>
      <div className="overflow-hidden rounded-md border border-border bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left font-medium">名称</th>
              <th className="px-4 py-3 text-left font-medium">分组</th>
              <th className="px-4 py-3 text-left font-medium">删除时间</th>
              <th className="w-56 px-4 py-3 text-left font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {trashProfiles.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-12 text-center text-slate-400">回收站为空</td>
              </tr>
            )}
            {trashProfiles.map((profile) => (
              <tr key={profile.id} className="hover:bg-slate-50">
                <td className="border-t border-border px-4 py-3 font-medium">{profile.name}</td>
                <td className="border-t border-border px-4 py-3 text-slate-600">{profile.group_name || "未分组"}</td>
                <td className="border-t border-border px-4 py-3 text-slate-600">{formatDate(profile.deleted_at)}</td>
                <td className="border-t border-border px-4 py-3">
                  <div className="flex gap-2">
                    <button className="btn-secondary px-2.5" onClick={() => void onRestoreProfile(profile.id)}>
                      恢复
                    </button>
                    <button className="btn-danger px-2.5" onClick={() => void handlePurgeProfile(profile)}>
                      彻底删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
