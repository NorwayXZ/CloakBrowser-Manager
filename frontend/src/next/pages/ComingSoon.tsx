import { Hammer } from "lucide-react";
import { LEGACY_PANEL_URL } from "../app/nav";
import { buttonClass, EmptyState, PageHeader } from "../ui";

/** Placeholder for a page that a later phase rebuilds. */
export function ComingSoon({ title, description, phase }: { title: string; description: string; phase: number }) {
  return (
    <div className="flex flex-col gap-6 p-6">
      <PageHeader title={title} description={description} />
      <ComingSoonPanel phase={phase} />
    </div>
  );
}

export function ComingSoonPanel({ phase, what = "这一页" }: { phase: number; what?: string }) {
  return (
    <div className="rounded-md border border-dashed border-border-strong bg-surface">
      <EmptyState
        icon={Hammer}
        title={`${what}正在重做`}
        description={`它会在第 ${phase} 阶段完成。在那之前，请在当前界面里使用这些功能。`}
        action={
          <a className={buttonClass("secondary")} href={LEGACY_PANEL_URL}>
            打开当前界面
          </a>
        }
      />
    </div>
  );
}

export function NotFound() {
  return (
    <div className="p-6">
      <EmptyState title="没有这个页面" description="地址可能输错了，或者这个页面已经移动。" />
    </div>
  );
}
