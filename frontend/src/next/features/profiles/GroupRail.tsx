import { FolderPlus, Trash2 } from "lucide-react";
import { useState } from "react";
import { cn } from "../../shared/lib/cn";
import { Button, IconButton, Input, Skeleton, useConfirm, useToast } from "../../ui";
import { useCreateGroup, useDeleteGroup } from "./api";
import { ALL_GROUPS, UNGROUPED } from "./format";
import type { ProfileGroup } from "./types";

/** Group filter plus group management (create / delete), beside the list. */
export function GroupRail({
  groups,
  loading,
  counts,
  total,
  value,
  onChange,
}: {
  groups: ProfileGroup[];
  loading: boolean;
  counts: Map<string, number>;
  total: number;
  value: string;
  onChange: (group: string) => void;
}) {
  const toast = useToast();
  const confirm = useConfirm();
  const createGroup = useCreateGroup();
  const deleteGroup = useDeleteGroup();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      await createGroup.mutateAsync(trimmed);
      setName("");
      setAdding(false);
      toast.show({ tone: "success", title: `已新建分组「${trimmed}」` });
    } catch (error) {
      toast.show({ tone: "error", title: "分组没有建好", description: error instanceof Error ? error.message : String(error) });
    }
  };

  const remove = async (group: ProfileGroup) => {
    const count = counts.get(group.name) ?? 0;
    const ok = await confirm({
      title: `删除分组「${group.name}」？`,
      description: count > 0 ? `其中 ${count} 个环境会回到“未分组”，环境本身不受影响。` : "这个分组里没有环境。",
      confirmLabel: "删除分组",
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteGroup.mutateAsync(group.id);
      if (value === group.name) onChange(ALL_GROUPS);
      toast.show({ tone: "success", title: `已删除分组「${group.name}」` });
    } catch (error) {
      toast.show({ tone: "error", title: "分组没有删除", description: error instanceof Error ? error.message : String(error) });
    }
  };

  const chip = (key: string, label: string, count: number, group?: ProfileGroup) => {
    const active = value === key;
    return (
      <li key={key} className="group/item flex shrink-0 items-center">
        <button
          type="button"
          aria-current={active ? "true" : undefined}
          onClick={() => onChange(key)}
          className={cn(
            "inline-flex h-9 items-center gap-2 rounded-full px-4 text-sm transition-colors duration-fast",
            active ? "bg-fg font-medium text-canvas" : "border border-border-strong/30 bg-surface/70 text-fg-2 hover:bg-surface hover:text-fg",
            group && "pr-3",
          )}
        >
          {group?.color && <span aria-hidden className="h-2 w-2 shrink-0 rounded-full" style={{ background: group.color }} />}
          <span className="max-w-40 truncate">{label}</span>
          <span className={cn("tabular text-xs", active ? "text-canvas/70" : "text-fg-3")}>{count}</span>
        </button>
        {group && (
          <IconButton
            size="sm"
            label={`删除分组「${group.name}」`}
            icon={<Trash2 className="h-3.5 w-3.5" />}
            className="-ml-1 hidden group-hover/item:inline-flex group-focus-within/item:inline-flex"
            onClick={() => void remove(group)}
          />
        )}
      </li>
    );
  };

  return (
    <nav aria-label="分组" className="flex flex-wrap items-center gap-2">
      <ul className="flex max-w-full list-none items-center gap-2 overflow-x-auto p-0 pb-1">
        {chip(ALL_GROUPS, "全部", total)}
        {chip(UNGROUPED, UNGROUPED, counts.get(UNGROUPED) ?? 0)}
        {loading ? (
          <li className="flex items-center gap-2 px-2">
            <Skeleton className="h-4 w-20" />
          </li>
        ) : (
          groups.filter((group) => group.name !== UNGROUPED).map((group) => chip(group.name, group.name, counts.get(group.name) ?? 0, group))
        )}
      </ul>
      {adding ? (
        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <Input
            autoFocus
            aria-label="新分组名称"
            placeholder="例如 美国账号"
            maxLength={64}
            className="w-44"
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setAdding(false);
                setName("");
              }
            }}
          />
          <Button type="submit" size="sm" variant="primary" loading={createGroup.isPending} disabled={!name.trim()}>
            添加
          </Button>
          <Button size="sm" onClick={() => { setAdding(false); setName(""); }}>
            取消
          </Button>
        </form>
      ) : (
        <Button variant="ghost" size="sm" icon={<FolderPlus className="h-3.5 w-3.5" />} onClick={() => setAdding(true)}>
          新建分组
        </Button>
      )}
    </nav>
  );
}
