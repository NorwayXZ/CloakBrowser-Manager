import { lazy, Suspense } from "react";
import { createBrowserRouter, Navigate, type RouteObject } from "react-router";
import { ComingSoon, NotFound } from "../pages/ComingSoon";
import { SettingsPage } from "../pages/SettingsPage";
import { Skeleton } from "../ui";
import { AppShell } from "./AppShell";
import { APP_BASENAME } from "./nav";

const Gallery = lazy(() => import("../dev/Gallery").then((m) => ({ default: m.Gallery })));

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
      { path: "profiles", element: <ComingSoon title="环境" description="打开、新建和管理浏览器环境。" phase={2} /> },
      { path: "profiles/new", element: <ComingSoon title="新建环境" description="自定义创建、一句话建号或一次性身份。" phase={2} /> },
      { path: "proxies", element: <ComingSoon title="代理" description="保存常用代理，批量导入，测试连通性。" phase={4} /> },
      { path: "checks", element: <ComingSoon title="检测" description="检测报告、自对抗进化和关联分析。" phase={5} /> },
      { path: "data", element: <ComingSoon title="数据" description="备份与恢复、回收站。" phase={4} /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "settings/:section", element: <SettingsPage /> },
      {
        path: "__ui",
        element: (
          <Suspense fallback={<PageFallback />}>
            <Gallery />
          </Suspense>
        ),
      },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(routes, { basename: APP_BASENAME });
}
