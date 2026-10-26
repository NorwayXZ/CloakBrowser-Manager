import { useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { appKeys, useAuthStatus } from "../features/app/api";
import { LoginPage } from "../features/app/LoginPage";
import { isApiError, onUnauthorized } from "../shared/api/client";
import { ErrorState, Spinner } from "../ui";

/**
 * Nothing renders until we know whether a password is required. Any 401
 * re-reads the sign-in state, which swaps the panel for the login page.
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
    return <LoginPage initialUsername={auth.data.username} />;
  }
  return <>{children}</>;
}
