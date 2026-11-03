import { NavLink, Outlet } from "react-router";
import { cn } from "../../shared/lib/cn";

const TABS = [
  { to: "/resources/proxies", label: "代理" },
  { to: "/resources/mail", label: "邮箱" },
];

/** 资源: the pools profiles draw from — saved proxies and mailboxes — as two tabs. */
export function ResourcesLayout() {
  return (
    <div className="flex flex-col pt-2">
      <nav aria-label="资源分类" className="glass flex w-fit max-w-full gap-1 overflow-x-auto rounded-full p-1.5">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={cn(
              "flex h-9 shrink-0 items-center rounded-full px-5 text-sm font-medium text-fg-2 transition-[background-color,color,box-shadow] duration-fast hover:text-fg",
              "aria-[current=page]:bg-surface aria-[current=page]:text-fg aria-[current=page]:shadow-raised",
            )}
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
