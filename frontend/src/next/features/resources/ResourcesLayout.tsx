import { NavLink, Outlet } from "react-router";
import { cn } from "../../shared/lib/cn";

const TABS = [
  { to: "/resources/proxies", label: "出口代理" },
  { to: "/resources/relays", label: "中转服务器" },
  { to: "/resources/mail", label: "邮箱" },
];

/** 资源: the pools profiles draw from — saved proxies, relay servers and mailboxes — as one row of tabs. */
export function ResourcesLayout() {
  return (
    <div className="flex flex-col pt-5">
      <nav aria-label="资源分类" className="flex max-w-full gap-6 overflow-x-auto border-b border-border">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={cn(
              "-mb-px flex h-10 shrink-0 items-center border-b-2 border-transparent px-0.5 text-sm font-medium text-fg-2 transition-[color,border-color] duration-fast hover:text-fg",
              "aria-[current=page]:border-accent aria-[current=page]:text-accent",
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
