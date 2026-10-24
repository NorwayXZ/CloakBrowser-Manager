import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter, Navigate, type RouteObject } from "react-router";
import { ProfilesLayout } from "../features/profiles/ProfilesLayout";
import { ProfilesPage } from "../features/profiles/ProfilesPage";
import { ComingSoon, NotFound } from "../pages/ComingSoon";
import { Skeleton } from "../ui";
import { AppShell } from "./AppShell";
import { APP_BASENAME } from "./nav";

const Gallery = lazy(() => import("../dev/Gallery").then((m) => ({ default: m.Gallery })));
const ViewerPage = lazy(() => import("../features/profiles/ViewerPage").then((m) => ({ default: m.ViewerPage })));
const EditorPage = lazy(() => import("../features/editor/EditorPage").then((m) => ({ default: m.EditorPage })));
const SettingsPage = lazy(() => import("../pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));

function page(element: ReactNode) {
  return <Suspense fallback={<PageFallback />}>{element}</Suspense>;
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
      { path: "proxies", element: <ComingSoon title="代理" description="保存常用代理，批量导入，测试连通性。" phase={4} /> },
      { path: "checks", element: <ComingSoon title="检测" description="检测报告、自对抗进化和关联分析。" phase={5} /> },
      { path: "data", element: <ComingSoon title="数据" description="备份与恢复、回收站。" phase={4} /> },
      { path: "settings", element: page(<SettingsPage />) },
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
