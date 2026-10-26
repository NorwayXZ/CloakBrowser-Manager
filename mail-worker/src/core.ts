// Pure helpers for the mail Worker, kept free of Cloudflare APIs so Node can test them.

const ADDRESS_RE = /^[a-z0-9][a-z0-9._+-]{0,63}@([a-z0-9-]+\.)+[a-z]{2,63}$/;

export const MAX_TEXT_CHARS = 50_000;
export const MAX_HTML_CHARS = 100_000;
export const MAX_RAW_BYTES = 2_000_000;

/** Lower-cased address if it is well formed and on `domain`, else null. */
export function normalizeAddress(value: unknown, domain: string): string | null {
  if (typeof value !== "string") return null;
  const address = value.trim().toLowerCase();
  if (!ADDRESS_RE.test(address)) return null;
  return address.endsWith("@" + domain.toLowerCase()) ? address : null;
}

export function clip(value: string | null | undefined, limit: number): string | null {
  if (value == null) return null;
  return value.length > limit ? value.slice(0, limit) : value;
}

/** Compare secrets without an early exit on the first differing byte. */
export function secretsEqual(a: string, b: string): boolean {
  const encoder = new TextEncoder();
  const left = encoder.encode(a);
  const right = encoder.encode(b);
  let diff = left.length ^ right.length;
  const length = Math.max(left.length, right.length);
  for (let i = 0; i < length; i++) diff |= (left[i] ?? 0) ^ (right[i] ?? 0);
  return diff === 0;
}

/** `Authorization: Bearer <token>` check; an empty configured token never matches. */
export function isAuthorized(header: string | null, token: string | undefined): boolean {
  if (!token) return false;
  const match = /^Bearer (.+)$/.exec(header ?? "");
  return match !== null && secretsEqual(match[1], token);
}

export function parseLimit(value: string | null, fallback: number, max: number): number {
  const n = Number.parseInt(value ?? "", 10);
  return Number.isFinite(n) && n > 0 ? Math.min(n, max) : fallback;
}

export function retentionCutoff(now: Date, days: number): string {
  return new Date(now.getTime() - days * 86_400_000).toISOString();
}
