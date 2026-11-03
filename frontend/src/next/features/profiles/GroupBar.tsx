import { FolderPlus, X } from "lucide-react";
import { useState } from "react";
import { cn } from "../../shared/lib/cn";
import { Button, IconButton, Input, Skeleton, useConfirm, useToast } from "../../ui";
import { useCreateGroup, useDeleteGroup } from "./api";
import { ALL_GROUPS, UNGROUPED } from "./format";
import type { ProfileGroup } from "./types";

/** Group filter plus group management (create / delete), as one row of chips above the list. */
export function GroupBar({
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
          "flex h-8 max-w-56 items-center gap-1.5 rounded-full border px-3 text-sm transition-colors duration-fast",
          value === key ? "border-accent/40 bg-accent-soft font-medium text-accent" : "border-border bg-surface text-fg-2 hover:bg-surface-2 hover:text-fg",
          group && "pr-7",
        )}
      >
        {group?.color && <span aria-hidden className="h-2 w-2 shrink-0 rounded-full" style={{ background: group.color }} />}
        <span className="min-w-0 truncate">{label}</span>
        <span className="tabular text-xs opacity-70">{count}</span>
      </button>
      {group && (
        <IconButton
          size="sm"
          label={`删除分组「${group.name}」`}
          icon={<X className="h-3 w-3" />}
          className="invisible absolute right-1 top-1 h-6 w-6 rounded-full group-hover/item:visible group-focus-within/item:visible focus-visible:visible"
          onClick={() => void remove(group)}
        />
      )}
    </li>
  );

  return (
    <nav aria-label="分组" className="flex flex-wrap items-center gap-1.5">
      <ul className="flex flex-wrap items-center gap-1.5">
        {item(ALL_GROUPS, "全部", total)}
        {item(UNGROUPED, UNGROUPED, counts.get(UNGROUPED) ?? 0)}
        {loading ? (
          <li className="flex gap-1.5">
            <Skeleton className="h-8 w-20 rounded-full" />
            <Skeleton className="h-8 w-16 rounded-full" />
          </li>
        ) : (
          groups.filter((group) => group.name !== UNGROUPED).map((group) => item(group.name, group.name, counts.get(group.name) ?? 0, group))
        )}
      </ul>
      {adding ? (
        <form
          className="flex items-center gap-1.5"
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
            className="h-8 w-40"
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
