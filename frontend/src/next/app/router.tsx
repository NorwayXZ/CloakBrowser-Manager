import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter, Navigate, useLocation, type RouteObject } from "react-router";
import { ProfilesLayout } from "../features/profiles/ProfilesLayout";
import { ProfilesPage } from "../features/profiles/ProfilesPage";
import { NotFound } from "../pages/NotFound";
import { Skeleton } from "../ui";
import { AppShell } from "./AppShell";
import { ResourcesLayout } from "../features/resources/ResourcesLayout";
import { APP_BASENAME, MOVED_PAGES } from "./nav";

const Gallery = lazy(() => import("../dev/Gallery").then((m) => ({ default: m.Gallery })));
const ViewerPage = lazy(() => import("../features/profiles/ViewerPage").then((m) => ({ default: m.ViewerPage })));
const EditorPage = lazy(() => import("../features/editor/EditorPage").then((m) => ({ default: m.EditorPage })));
const RelayNodesPanel = lazy(() => import("../features/proxies/RelayNodesPanel").then((m) => ({ default: m.RelayNodesPanel })));
const ProxiesPage = lazy(() => import("../features/proxies/ProxiesPage").then((m) => ({ default: m.ProxiesPage })));
const DataPage = lazy(() => import("../features/data/DataPage").then((m) => ({ default: m.DataPage })));
const MailPage = lazy(() => import("../features/mail/MailPage").then((m) => ({ default: m.MailPage })));
const ChecksPage = lazy(() => import("../features/checks/ChecksPage").then((m) => ({ default: m.ChecksPage })));
const SettingsPage = lazy(() => import("../pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const SettingsSubpage = lazy(() => import("../pages/SettingsPage").then((m) => ({ default: m.SettingsSubpage })));

function page(element: ReactNode) {
  return <Suspense fallback={<PageFallback />}>{element}</Suspense>;
}

/** An old top-level address: same sub-path, query and hash under the page's new home. */
function MovedPage({ from }: { from: string }) {
  const { pathname, search, hash } = useLocation();
  return <Navigate to={`${MOVED_PAGES[from]}${pathname.slice(from.length)}${search}${hash}`} replace />;
}

function PageFallback() {
  return (
    <div className="flex flex-col gap-4 p-6" aria-busy="true">
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/profiles" replace /> },
      {
        path: "profiles",
        element: <ProfilesLayout />,
        children: [
          { index: true, element: <ProfilesPage /> },
          { path: "new", element: page(<EditorPage mode="new" />) },
          { path: ":id/edit", element: page(<EditorPage mode="edit" />) },
          { path: ":id/viewer", element: page(<ViewerPage />) },
        ],
      },
      {
        path: "resources",
        element: <ResourcesLayout />,
        children: [
          { index: true, element: <Navigate to="proxies" replace /> },
          { path: "proxies", element: page(<ProxiesPage />) },
          { path: "relays", element: page(<RelayNodesPanel />) },
          { path: "mail", element: page(<MailPage />) },
        ],
      },
      { path: "settings", element: page(<SettingsPage />) },
      { path: "settings/checks", element: page(<SettingsSubpage><ChecksPage /></SettingsSubpage>) },
      { path: "settings/checks/evolution", element: page(<SettingsSubpage><ChecksPage /></SettingsSubpage>) },
      { path: "settings/checks/links", element: page(<SettingsSubpage><ChecksPage /></SettingsSubpage>) },
      { path: "settings/data", element: page(<SettingsSubpage><DataPage /></SettingsSubpage>) },
      { path: "settings/data/trash", element: page(<SettingsSubpage><DataPage /></SettingsSubpage>) },
      ...Object.keys(MOVED_PAGES).flatMap((from) => [
        { path: from.slice(1), element: <MovedPage from={from} /> },
        { path: `${from.slice(1)}/*`, element: <MovedPage from={from} /> },
      ]),
      { path: "settings/:section", element: page(<SettingsPage />) },
      {
        path: "__ui",
        element: page(<Gallery />),
      },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(routes, { basename: APP_BASENAME });
}
