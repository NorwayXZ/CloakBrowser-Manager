import { useEffect, useState } from "react";
import { cn } from "../../shared/lib/cn";
import { Spinner } from "../../ui";
import { useUpdateNotes } from "./api";
import type { Profile } from "./types";

/**
 * Notes that save themselves: on blur or Enter (Shift+Enter for a new line in
 * the multi-line form). Esc puts the saved text back. A failed save keeps the
 * draft and says so.
 */
export function NoteField({ profile, multiline = false, className }: { profile: Profile; multiline?: boolean; className?: string }) {
  const saved = profile.notes ?? "";
  const [draft, setDraft] = useState(saved);
  const [editing, setEditing] = useState(false);
  const mutation = useUpdateNotes();

  // Follow outside changes (polling, the other note field) while not editing,
  // but never overwrite text that is being saved or failed to save.
  const holdDraft = editing || mutation.isPending || mutation.isError;
  useEffect(() => {
    if (!holdDraft) setDraft(saved);
  }, [saved, holdDraft]);

  const commit = () => {
    setEditing(false);
    const next = draft.trim();
    if (next === saved.trim()) {
      setDraft(saved);
      mutation.reset();
      return;
    }
    mutation.mutate({ id: profile.id, notes: next || null });
  };

  const state = mutation.isPending ? "saving" : mutation.isError ? "error" : null;
  const common = {
    value: draft,
    "aria-label": `「${profile.name}」的备注`,
    placeholder: "添加备注",
    onFocus: () => setEditing(true),
    onChange: (event: { target: { value: string } }) => {
      setDraft(event.target.value);
      if (mutation.isError) mutation.reset();
    },
    onBlur: commit,
    onKeyDown: (event: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      event.stopPropagation(); // row shortcuts must not fire while typing
      if (event.key === "Escape") {
        setDraft(saved);
        setEditing(false);
        (event.currentTarget as HTMLElement).blur();
      } else if (event.key === "Enter" && !(multiline && event.shiftKey) && !event.nativeEvent.isComposing) {
        event.preventDefault();
        (event.currentTarget as HTMLElement).blur();
      }
    },
    className: cn(
      "w-full min-w-0 rounded border bg-transparent px-2 text-sm text-fg placeholder:text-fg-3 transition-colors duration-fast",
      "hover:bg-surface-2 focus:bg-surface focus:outline-none focus:ring-2 focus:ring-accent/25",
      state === "error" ? "border-danger" : "border-transparent focus:border-accent",
      multiline ? "py-1.5" : "h-8 truncate pr-7",
    ),
  };

  return (
    <div className={cn("relative min-w-0", className)}>
      {multiline ? <textarea rows={3} {...common} /> : <input {...common} title={saved || undefined} />}
      {state === "saving" && <Spinner className="absolute right-2 top-2 h-3.5 w-3.5 text-fg-3" label="正在保存备注" />}
      {state === "error" && (
        <p role="alert" className="mt-1 text-xs text-danger">
          备注没有保存：{mutation.error instanceof Error ? mutation.error.message : "未知错误"}
        </p>
      )}
    </div>
  );
}
