import { Shuffle } from "lucide-react";
import { Button } from "../../ui";
import { normalizeFormEngine, summaryRows } from "./model";
import type { HostOS } from "./types";
import type { Editor } from "./useEditor";

/** Live 概要 of what the browser will present, as in the current editor. */
export function SummaryPanel({ editor, hostOS, hostScreen, isEdit }: { editor: Editor; hostOS: HostOS | null; hostScreen: number[] | null; isEdit: boolean }) {
  const rows = summaryRows({ form: editor.form, proxyParts: editor.proxyParts, proxyTest: editor.proxyTest, hostOS, hostScreen, isEdit });
  const cloak = normalizeFormEngine(editor.form.browser_engine) === "cloakbrowser";
  return (
    <aside aria-label="概要" className="rounded-md border border-border bg-surface">
      <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <h2 className="text-base font-semibold text-fg">概要</h2>
        {cloak ? (
          <Button size="sm" variant="ghost" className="text-accent" icon={<Shuffle className="h-3.5 w-3.5" />} onClick={editor.randomizeDevice}>
            随机设备画像
          </Button>
        ) : (
          <span className="text-xs text-fg-3">稳定原生使用真实设备</span>
        )}
      </header>
      <dl className="grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 gap-y-2 px-4 py-3 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-fg-3">{label}</dt>
            <dd className="m-0 break-words text-right text-fg">{value}</dd>
          </div>
        ))}
      </dl>
    </aside>
  );
}
