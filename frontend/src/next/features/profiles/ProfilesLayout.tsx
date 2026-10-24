import { Pencil, Sparkles, UserRoundPlus } from "lucide-react";
import { Outlet, useNavigate } from "react-router";
import { LEGACY_PANEL_URL } from "../../app/nav";
import { Button, buttonClass, EmptyState, PageHeader } from "../../ui";
import { LaunchProvider } from "./launch";

/** Every environment page shares one launch flow (preflight dialog, busy state). */
export function ProfilesLayout() {
  return (
    <LaunchProvider>
      <Outlet />
    </LaunchProvider>
  );
}

/**
 * /profiles/new and /profiles/:id/edit until the editor is rebuilt (phase 3).
 * The quick ways to create are already here.
 */
export function EditorComingSoon({ mode }: { mode: "new" | "edit" }) {
  const navigate = useNavigate();
  return (
    <div className="flex flex-col gap-6 p-6">
      <PageHeader title={mode === "new" ? "新建环境" : "编辑环境"} description="完整的配置页（基础、代理、指纹、更多指纹、高级）正在重做，会在第 3 阶段完成。" />
      <div className="rounded-md border border-dashed border-border-strong bg-surface">
        <EmptyState
          icon={Pencil}
          title={mode === "new" ? "自定义创建暂时请用当前界面" : "编辑配置暂时请用当前界面"}
          description={mode === "new" ? "也可以先用下面两种快速方式创建，之后再细调。" : "在当前界面的环境列表里点“编辑”。"}
          action={
            <>
              <a className={buttonClass("secondary")} href={LEGACY_PANEL_URL}>
                打开当前界面
              </a>
              {mode === "new" && (
                <>
                  <Button icon={<Sparkles className="h-4 w-4" />} onClick={() => navigate("/profiles?create=sentence")}>
                    一句话建号
                  </Button>
                  <Button icon={<UserRoundPlus className="h-4 w-4" />} onClick={() => navigate("/profiles?create=disposable")}>
                    一次性身份
                  </Button>
                </>
              )}
            </>
          }
        />
      </div>
    </div>
  );
}
