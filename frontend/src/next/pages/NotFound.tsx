import { EmptyState } from "../ui";

export function NotFound() {
  return (
    <div className="p-6">
      <EmptyState title="没有这个页面" description="地址可能输错了，或者这个页面已经移动。" />
    </div>
  );
}
