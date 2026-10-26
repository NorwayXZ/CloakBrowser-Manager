import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "../../shared/api/client";
import type {
  AgentLease,
  BurnResult,
  DeviceTemplate,
  FingerprintReport,
  LaunchMode,
  LaunchResult,
  Preflight,
  Profile,
  ProfileCreate,
  ProfileGroup,
  SentenceAssembled,
  SentenceCreated,
  SentenceDraft,
  SentenceOptions,
} from "./types";

export const profileKeys = {
  list: ["profiles", "list"] as const,
  groups: ["groups", "list"] as const,
  trash: ["profiles", "trash"] as const,
  sentenceOptions: ["profiles", "sentence-options"] as const,
  deviceTemplates: ["device-templates"] as const,
};

const enc = encodeURIComponent;

export const profilesApi = {
  list: () => request<Profile[]>("/api/profiles"),
  create: (data: ProfileCreate) => request<Profile>("/api/profiles", { method: "POST", body: data }),
  update: (id: string, data: Partial<ProfileCreate>) => request<Profile>(`/api/profiles/${enc(id)}`, { method: "PUT", body: data }),
  remove: (id: string) => request<{ ok: boolean }>(`/api/profiles/${enc(id)}`, { method: "DELETE" }),
  restore: (id: string) => request<Profile>(`/api/profiles/${enc(id)}/restore`, { method: "POST" }),
  burn: (id: string) => request<BurnResult>(`/api/profiles/${enc(id)}/burn`, { method: "POST", body: { confirm: true } }),
  preflight: (id: string, mode: LaunchMode) =>
    request<Preflight>(`/api/profiles/${enc(id)}/preflight?launch_mode=${mode}`),
  // Launching waits for the browser to come up; give it more than the default 15 s.
  launch: (id: string, mode: LaunchMode) =>
    request<LaunchResult>(`/api/profiles/${enc(id)}/launch`, { method: "POST", body: { launch_mode: mode }, timeoutMs: 120_000 }),
  stop: (id: string) => request<{ ok: boolean }>(`/api/profiles/${enc(id)}/stop`, { method: "POST", timeoutMs: 60_000 }),
  fingerprintReport: (id: string) => request<FingerprintReport>(`/api/profiles/${enc(id)}/fingerprint-report`, { timeoutMs: 60_000 }),
  createDisposable: (region: string) => request<Profile>("/api/profiles/disposable", { method: "POST", body: { region } }),
  sentenceDraft: (sentence: string, signal?: AbortSignal) =>
    request<SentenceDraft>("/api/profiles/from-sentence/draft", { method: "POST", body: { sentence }, signal, timeoutMs: 90_000 }),
  sentenceOptions: () => request<SentenceOptions>("/api/profiles/from-sentence/options"),
  sentenceCreate: (sentence: string, assembled: SentenceAssembled) =>
    request<SentenceCreated>("/api/profiles/from-sentence", { method: "POST", body: { sentence, assembled } }),
  deviceTemplates: () => request<DeviceTemplate[]>("/api/device-templates"),
  groups: () => request<ProfileGroup[]>("/api/groups"),
  createGroup: (name: string) => request<ProfileGroup>("/api/groups", { method: "POST", body: { name } }),
  deleteGroup: (id: string) => request<{ ok: boolean }>(`/api/groups/${enc(id)}`, { method: "DELETE" }),
  /** The person takes over from an AI agent: parks the lease on "human" and cuts the agent's CDP sockets. */
  takeover: (id: string) => request<{ lease: AgentLease | null; cdp_connections_closed: number }>(`/api/profiles/${enc(id)}/lease/takeover`, { method: "POST", body: {} }),
  /** The person hands the profile back to agents. */
  releaseLease: (id: string) => request<{ released: boolean }>(`/api/profiles/${enc(id)}/lease`, { method: "DELETE" }),
  setClipboard: (id: string, text: string) => request<{ ok: boolean }>(`/api/profiles/${enc(id)}/clipboard`, { method: "POST", body: { text } }),
  getClipboard: (id: string) => request<{ text: string }>(`/api/profiles/${enc(id)}/clipboard`),
};

/** All profiles, refreshed every 3 s for status (paused while the window is hidden). */
export function useProfiles() {
  return useQuery({ queryKey: profileKeys.list, queryFn: profilesApi.list, refetchInterval: 3_000 });
}

export function useGroups() {
  return useQuery({ queryKey: profileKeys.groups, queryFn: profilesApi.groups });
}

export function useSentenceOptions(enabled: boolean) {
  return useQuery({ queryKey: profileKeys.sentenceOptions, queryFn: profilesApi.sentenceOptions, enabled, staleTime: Infinity });
}

export function useDeviceTemplates(enabled: boolean) {
  return useQuery({ queryKey: profileKeys.deviceTemplates, queryFn: profilesApi.deviceTemplates, enabled, staleTime: Infinity });
}

/** Re-read everything a profile change can touch. */
export function useInvalidateProfiles() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: profileKeys.list }),
      queryClient.invalidateQueries({ queryKey: profileKeys.trash }),
      queryClient.invalidateQueries({ queryKey: ["manager", "status"] }),
    ]);
}

/** Notes save straight into the list cache so the row never flickers back. */
export function useUpdateNotes() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, notes }: { id: string; notes: string | null }) => profilesApi.update(id, { notes }),
    onSuccess: (saved) => {
      queryClient.setQueryData<Profile[]>(profileKeys.list, (list) => list?.map((p) => (p.id === saved.id ? saved : p)));
    },
  });
}

export function useCreateGroup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => profilesApi.createGroup(name),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: profileKeys.groups }),
  });
}

export function useDeleteGroup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => profilesApi.deleteGroup(id),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: profileKeys.groups }),
        queryClient.invalidateQueries({ queryKey: profileKeys.list }),
      ]),
  });
}
