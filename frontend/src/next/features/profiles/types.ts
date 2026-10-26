import type { components } from "../../shared/api/schema";

type Schemas = components["schemas"];

export type Profile = Schemas["ProfileResponse"];
export type ProfileCreate = Schemas["ProfileCreate"];
export type ProfileGroup = Schemas["GroupResponse"];
export type LaunchMode = "manual" | "debug";
export type LaunchResult = Schemas["LaunchResponse"];
export type Preflight = Schemas["PreflightResponse"];
export type PreflightIssue = Schemas["PreflightIssue"];
export type DeviceTemplate = Schemas["DeviceTemplateResponse"];
export type BurnResult = Schemas["BurnResponse"];

// The endpoints below return plain dicts on the backend (no response model),
// so their shapes are written out here, matching backend/main.py.

export interface FingerprintIssue {
  severity: "error" | "warning";
  signal: string;
  scope: string;
  expected: unknown;
  actual: unknown;
  message: string;
}

export interface ExternalNetworkProbe {
  egress?: { ip?: string | null; country?: string | null; region?: string | null; city?: string | null; timezone?: string | null };
  transport?: { http_protocol?: string | null; tls_version?: string | null; tls_cipher?: string | null };
  error?: string;
}

export interface FingerprintReport {
  profile_id: string;
  expected: {
    browser_engine: string | null;
    launch_mode: LaunchMode | null;
    external_cdp: boolean;
    locale: string | null;
    timezone: string | null;
  };
  collection: "active" | "passive";
  proxy_geo: { ip?: string | null; country?: string | null; region?: string | null; city?: string | null; source?: string } | null;
  network: { dns_externally_verified: boolean };
  analysis: {
    status: "pass" | "warning" | "fail";
    error_count: number;
    warning_count: number;
    issues: FingerprintIssue[];
  };
  raw: Record<string, unknown>;
}

export interface SentenceSpec {
  country: string;
  city: string | null;
  interests: string[];
  persona_notes: string | null;
  purpose: string | null;
  disposable: boolean;
}

export interface SentenceAssembled {
  name: string;
  platform: string;
  device_profile: string;
  screen_width: number;
  screen_height: number;
  gpu_vendor: string;
  gpu_renderer: string;
  hardware_concurrency: number;
  device_memory: number;
  timezone: string;
  locale: string;
  warmup_targets: string[];
  warmup_enabled: boolean;
  warmup_persona: string | null;
  notes: string | null;
  disposable: boolean;
  fingerprint_options: Record<string, unknown>;
}

export interface SentenceDraft {
  source: "llm" | "fallback";
  spec: SentenceSpec;
  assembled: SentenceAssembled;
  warnings: string[];
}

export interface SentenceOptions {
  countries: { code: string; name: string; locale: string | null; timezone: string | null }[];
  cities: Record<string, { name: string; name_zh: string; timezone: string }[]>;
  interests: { id: string; name: string; targets: string[] }[];
  targets: { id: string; name: string }[];
}

export type SentenceCreated = Profile & { warnings: string[] };
