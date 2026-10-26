import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { log } from "../../shared/log/logger";
import { appKeys, type AuthStatus } from "../app/api";
import { settingsApi } from "./api";

/**
 * Sign out. The server only clears the cookie; if it cannot be reached we
 * still drop back to the login page so nobody is stuck inside the panel,
 * and forget every cached answer so the next user does not see them.
 */
export function useLogout() {
  const queryClient = useQueryClient();
  return useCallback(async () => {
    try {
      await settingsApi.logout();
    } catch (error) {
      log.warn("退出登录请求失败，已在本地退出", { action: "auth.logout", detail: error });
    }
    const previous = queryClient.getQueryData<AuthStatus>(appKeys.auth);
    // Keep only the sign-in state and the theme, which the login page still uses.
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== "auth" && !(query.queryKey[0] === "settings" && query.queryKey[1] === "ui") });
    queryClient.setQueryData<AuthStatus>(appKeys.auth, { auth_required: true, authenticated: false, username: previous?.username ?? null });
  }, [queryClient]);
}
