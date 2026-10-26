import { useQuery } from "@tanstack/react-query";
import { request } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";
import { profileKeys } from "../profiles/api";

type Schemas = components["schemas"];
export type ManagerStatus = Schemas["StatusResponse"];
export type AutomationStatus = Schemas["AutomationStatusResponse"];
export type ProfileSummary = Pick<Schemas["ProfileResponse"], "id" | "name" | "status" | "group_name">;

/** /api/auth/status has no response model on the backend. */
export interface AuthStatus {
  auth_required: boolean;
  authenticated: boolean;
  username: string | null;
}

export const appKeys = {
  auth: ["auth", "status"] as const,
  status: ["manager", "status"] as const,
  automation: ["automation", "status"] as const,
  /** Shared with the environment list, so both read one cache. */
  profiles: profileKeys.list,
};

export const appApi = {
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  status: () => request<ManagerStatus>("/api/status"),
  automation: () => request<AutomationStatus>("/api/automation/status"),
  profiles: () => request<ProfileSummary[]>("/api/profiles"),
};

export function useAuthStatus() {
  return useQuery({ queryKey: appKeys.auth, queryFn: appApi.authStatus, staleTime: 30_000 });
}

/** Version numbers and how many browsers run. Polled; paused while the window is hidden. */
export function useManagerStatus() {
  return useQuery({ queryKey: appKeys.status, queryFn: appApi.status, refetchInterval: 5_000 });
}

export function useAutomationStatus() {
  return useQuery({ queryKey: appKeys.automation, queryFn: appApi.automation, refetchInterval: 5_000 });
}

export function useRunningProfiles(enabled: boolean) {
  return useQuery({
    queryKey: appKeys.profiles,
    queryFn: appApi.profiles,
    enabled,
    select: (profiles) => profiles.filter((profile) => profile.status === "running"),
  });
}
