import { useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { appKeys, useAuthStatus } from "../features/app/api";
import { isApiError, onUnauthorized } from "../shared/api/client";
import { buttonClass, EmptyState, ErrorState, Spinner } from "../ui";
import { LEGACY_PANEL_URL } from "./nav";

/**
 * Nothing renders until we know whether a password is required. The login
 * page itself is rebuilt in phase 6; until then the current panel signs in
 * (same cookie, same origin).
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const auth = useAuthStatus();

  useEffect(() => onUnauthorized(() => void queryClient.invalidateQueries({ queryKey: appKeys.auth })), [queryClient]);

  if (auth.isPending) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-fg-2">
        <Spinner label="正在连接 Manager" />
        正在连接 Manager…
      </div>
    );
  }
  if (auth.isError) {
    return (
      <div className="flex h-full items-center justify-center">
        <ErrorState
          title="连接不到 Manager 服务"
          message={isApiError(auth.error) && auth.error.kind !== "http" ? "请确认 CloakBrowser Manager 正在运行，然后重试。" : auth.error.message}
          onRetry={() => void auth.refetch()}
          retrying={auth.isFetching}
        />
      </div>
    );
  }
  if (auth.data.auth_required && !auth.data.authenticated) {
    return (
      <div className="flex h-full items-center justify-center">
        <EmptyState
          icon={KeyRound}
          title="请先登录"
          description="这个 Manager 设置了登录密码。登录后回到这里即可。"
          action={
            <a className={buttonClass("primary")} href={LEGACY_PANEL_URL}>
              去登录
            </a>
          }
        />
      </div>
    );
  }
  return <>{children}</>;
}
