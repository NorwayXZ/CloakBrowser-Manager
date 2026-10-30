import { useQuery } from "@tanstack/react-query";
import { request } from "../../shared/api/client";
import type { ProxyTestResult } from "../editor/types";

export interface RelayNode {
  id: string;
  name: string;
  proxy: string;
  profile_count?: number;
  created_at: string;
  updated_at: string;
}

export const relayKey = ["relay-nodes"] as const;
export const relayApi = {
  list: () => request<RelayNode[]>("/api/relay-nodes"),
  save: (body: { name: string; proxy: string }, id?: string) => request<RelayNode>(
    `/api/relay-nodes${id ? `/${encodeURIComponent(id)}` : ""}`, { method: id ? "PUT" : "POST", body },
  ),
  remove: (id: string) => request(`/api/relay-nodes/${encodeURIComponent(id)}`, { method: "DELETE" }),
  test: (id: string) => request<ProxyTestResult>(`/api/relay-nodes/${encodeURIComponent(id)}/test`, { method: "POST", timeoutMs: 60_000 }),
};

export function useRelayNodes(enabled = true) {
  return useQuery({ queryKey: relayKey, queryFn: relayApi.list, enabled });
}
