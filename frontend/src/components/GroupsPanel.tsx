import { useState } from "react";
import type { Profile, ProfileGroup } from "../lib/api";
import { formatDate } from "../lib/format";

interface GroupsPanelProps {
  groups: ProfileGroup[];
  profiles: Profile[];
  onCreateGroup: (name: string, color?: string | null) => Promise<void>;
  onDeleteGroup: (id: string) => Promise<void>;
}

export function GroupsPanel({ groups, profiles, onCreateGroup, onDeleteGroup }: GroupsPanelProps) {
  const [groupName, setGroupName] = useState("");

  const handleDeleteGroup = async (group: ProfileGroup) => {
    const count = profiles.filter((profile) => profile.group_name === group.name).length;
    const detail = count > 0 ? `其中 ${count} 个浏览器会回到“未分组”。` : "";
    if (!confirm(`确定删除分组「${group.name}」吗？${detail}`)) return;
    await onDeleteGroup(group.id);
  };

  const handleCreateGroup = async () => {
    const name = groupName.trim();
    if (!name) return;
    await onCreateGroup(name);
    setGroupName("");
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col p-4">
      <div className="mb-4 rounded-md border border-border bg-white p-4">
        <div className="grid grid-cols-[minmax(220px,360px)_auto] gap-3">
          <input
            className="input h-11"
            value={groupName}
            onChange={(event) => setGroupName(event.target.value)}
            placeholder="输入分组名称，例如 美国账号"
          />
          <button
            className="btn-primary px-5"
            onClick={() => void handleCreateGroup()}
            disabled={!groupName.trim()}
          >
            新建分组
          </button>
        </div>
      </div>

      <div className="overflow-hidden rounded-md border border-border bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left font-medium">分组名称</th>
              <th className="px-4 py-3 text-left font-medium">浏览器数量</th>
              <th className="px-4 py-3 text-left font-medium">创建时间</th>
              <th className="w-32 px-4 py-3 text-left font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="border-t border-border px-4 py-3 font-medium">未分组</td>
              <td className="border-t border-border px-4 py-3 text-slate-600">
                {profiles.filter((profile) => !profile.group_name || profile.group_name === "未分组").length}
              </td>
              <td className="border-t border-border px-4 py-3 text-slate-400">系统默认</td>
              <td className="border-t border-border px-4 py-3 text-slate-400">不可删除</td>
            </tr>
            {groups.map((group) => (
              <tr key={group.id} className="hover:bg-slate-50">
                <td className="border-t border-border px-4 py-3 font-medium">{group.name}</td>
                <td className="border-t border-border px-4 py-3 text-slate-600">
                  {profiles.filter((profile) => profile.group_name === group.name).length}
                </td>
                <td className="border-t border-border px-4 py-3 text-slate-600">{formatDate(group.created_at)}</td>
                <td className="border-t border-border px-4 py-3">
                  <button
                    className="btn-secondary px-2.5 text-red-600"
                    onClick={() => void handleDeleteGroup(group)}
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
