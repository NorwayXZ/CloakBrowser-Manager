import { useCallback, useState } from "react";

const KEY = "cbm.pinned-profiles";

function read(): string[] {
  try {
    const raw = JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

/** Profiles pinned to the top of the list. Kept in this browser only; it is a view preference, not profile data. */
export function usePinnedProfiles() {
  const [pinned, setPinned] = useState<ReadonlySet<string>>(() => new Set(read()));
  const toggle = useCallback((id: string) => {
    setPinned((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      try {
        window.localStorage.setItem(KEY, JSON.stringify([...next]));
      } catch {
        /* storage blocked: the pin lasts until reload */
      }
      return next;
    });
  }, []);
  return { pinned, toggle };
}

/** Pinned first, otherwise the original order. */
export function pinnedFirst<T extends { id: string }>(items: T[], pinned: ReadonlySet<string>): T[] {
  if (pinned.size === 0) return items;
  return [...items.filter((item) => pinned.has(item.id)), ...items.filter((item) => !pinned.has(item.id))];
}
