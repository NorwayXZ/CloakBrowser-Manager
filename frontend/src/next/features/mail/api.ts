import { useQuery } from "@tanstack/react-query";
import { request } from "../../shared/api/client";

// The mail endpoints answer plain dicts (no response models), matching backend/main.py.

/** /api/settings/mail: the admin password is never sent back. */
export interface MailSettings {
  configured: boolean;
  base_url: string | null;
  admin_email: string | null;
  has_password: boolean;
  /** Domains new addresses use; empty = every domain on the server. */
  domains: string[];
}

export interface MailSettingsUpdate {
  base_url: string;
  admin_email: string;
  /** Write-only: null keeps the stored password. */
  password: string | null;
  domains: string[];
}

export interface MailAddress {
  address: string;
  profile_id: string | null;
  profile_name: string | null;
  created_at: string;
  last_delivered_id: number;
}

export interface MailMessage {
  id: number;
  to: string;
  from: string;
  from_name: string | null;
  subject: string;
  received_at: string | null;
  code: string | null;
  link: string | null;
  text: string;
}

export interface MailMessages {
  address: string;
  last_delivered_id: number;
  messages: MailMessage[];
}

const enc = encodeURIComponent;

export const mailApi = {
  settings: () => request<MailSettings>("/api/settings/mail"),
  saveSettings: (body: MailSettingsUpdate) => request<MailSettings>("/api/settings/mail", { method: "PUT", body }),
  /** Logs in with the saved account and lists the server's domains. */
  check: () => request<{ ok: boolean; domains: string[] }>("/api/mail/check", { method: "POST", timeoutMs: 30_000 }),
  addresses: () => request<MailAddress[]>("/api/mail/addresses"),
  createAddress: (body: { profile_id?: string; domain?: string; local_part?: string }) =>
    request<MailAddress>("/api/mail/addresses", { method: "POST", body, timeoutMs: 30_000 }),
  forget: (address: string) => request<{ ok: boolean }>(`/api/mail/addresses/${enc(address)}`, { method: "DELETE" }),
  messages: (address: string) => request<MailMessages>(`/api/mail/messages?address=${enc(address)}&limit=20`, { timeoutMs: 30_000 }),
};

export const mailKeys = {
  settings: ["mail", "settings"] as const,
  addresses: ["mail", "addresses"] as const,
  messages: (address: string) => ["mail", "messages", address] as const,
};

export function useMailSettings() {
  return useQuery({ queryKey: mailKeys.settings, queryFn: mailApi.settings });
}

export function useMailAddresses(enabled: boolean) {
  return useQuery({ queryKey: mailKeys.addresses, queryFn: mailApi.addresses, enabled });
}

/** One address's inbox, refreshed every 10 s while the page is open. */
export function useMailMessages(address: string | null) {
  return useQuery({
    queryKey: mailKeys.messages(address ?? ""),
    queryFn: () => mailApi.messages(address as string),
    enabled: Boolean(address),
    refetchInterval: 10_000,
  });
}
