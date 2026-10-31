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

  const item = (key: string, label: string, count: number, group?: ProfileGroup) => (
    <li key={key} className="group/item relative">
      <button
        type="button"
        aria-current={value === key ? "true" : undefined}
        onClick={() => onChange(key)}
        className={cn(
          "flex h-8 w-full items-center gap-2 rounded px-2.5 text-left text-sm transition-colors duration-fast",
          value === key ? "bg-accent-soft font-medium text-accent" : "text-fg-2 hover:bg-surface-2 hover:text-fg",
          group && "pr-9",
        )}
      >
        {group?.color && <span aria-hidden className="h-2 w-2 shrink-0 rounded-full" style={{ background: group.color }} />}
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <span className={cn("tabular text-xs", group && "group-hover/item:invisible group-focus-within/item:invisible")}>{count}</span>
      </button>
      {group && (
        <IconButton
          size="sm"
          label={`删除分组「${group.name}」`}
          icon={<Trash2 className="h-3.5 w-3.5" />}
          className="invisible absolute right-1 top-0.5 group-hover/item:visible group-focus-within/item:visible focus-visible:visible"
          onClick={() => void remove(group)}
        />
      )}
    </li>
  );

  return (
    <nav aria-label="分组" className="flex w-52 shrink-0 flex-col gap-2 border-r border-border bg-surface px-3 py-4">
      <div className="px-2.5 text-xs font-medium text-fg-3">分组</div>
      <ul className="flex flex-col gap-0.5">
        {item(ALL_GROUPS, "全部", total)}
        {item(UNGROUPED, UNGROUPED, counts.get(UNGROUPED) ?? 0)}
        {loading ? (
          <li className="flex flex-col gap-2 px-2.5 py-1">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-4 w-20" />
          </li>
        ) : (
          groups.filter((group) => group.name !== UNGROUPED).map((group) => item(group.name, group.name, counts.get(group.name) ?? 0, group))
        )}
      </ul>
      {adding ? (
        <form
          className="flex flex-col gap-2 px-1"
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
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setAdding(false);
                setName("");
              }
            }}
          />
          <div className="flex gap-2">
            <Button type="submit" size="sm" variant="primary" loading={createGroup.isPending} disabled={!name.trim()}>
              添加
            </Button>
            <Button size="sm" onClick={() => { setAdding(false); setName(""); }}>
              取消
            </Button>
          </div>
        </form>
      ) : (
        <Button variant="ghost" size="sm" className="justify-start" icon={<FolderPlus className="h-3.5 w-3.5" />} onClick={() => setAdding(true)}>
          新建分组
        </Button>
      )}
    </nav>
  );
}
