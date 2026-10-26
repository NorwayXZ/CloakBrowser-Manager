// Cloudflare Email Worker for the CloakBrowser domain mailbox.
//
//   mail to *@your-domain ──Email Routing (catch-all)──▶ email()  ──▶ D1
//   CloakBrowser Manager  ──HTTPS + bearer token──────▶ fetch()  ◀── D1
//
// Only addresses the Manager registered are accepted; everything else is rejected at
// SMTP time, so the database holds nothing but mail an agent is waiting for.

import PostalMime from "postal-mime";
import {
  MAX_HTML_CHARS,
  MAX_RAW_BYTES,
  MAX_TEXT_CHARS,
  clip,
  isAuthorized,
  normalizeAddress,
  parseLimit,
  retentionCutoff,
} from "./core.ts";

export interface Env {
  DB: D1Database;
  /** Secret: `wrangler secret put API_TOKEN`. The Manager sends it as a bearer token. */
  API_TOKEN: string;
  MAIL_DOMAIN: string;
  RETENTION_DAYS?: string;
}

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

async function receive(message: ForwardableEmailMessage, env: Env): Promise<void> {
  const to = message.to.toLowerCase();
  const known = await env.DB.prepare("SELECT 1 AS ok FROM addresses WHERE address = ?").bind(to).first();
  if (!known) {
    message.setReject("550 5.1.1 Mailbox unavailable");
    return;
  }
  if (message.rawSize > MAX_RAW_BYTES) {
    message.setReject("552 5.3.4 Message too large");
    return;
  }
  const raw = await new Response(message.raw).arrayBuffer();
  const mail = await PostalMime.parse(raw);
  await env.DB.prepare(
    `INSERT INTO messages (id, address, from_addr, from_name, subject, text, html, received_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
  )
    .bind(
      crypto.randomUUID(),
      to,
      mail.from?.address ?? message.from,
      mail.from?.name || null,
      mail.subject ?? "",
      clip(mail.text, MAX_TEXT_CHARS),
      clip(mail.html, MAX_HTML_CHARS),
      new Date().toISOString(),
    )
    .run();
}

async function api(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/health") {
    return json({ ok: true, domain: env.MAIL_DOMAIN, time: new Date().toISOString() });
  }
  if (!isAuthorized(request.headers.get("authorization"), env.API_TOKEN)) {
    return json({ error: "unauthorized" }, 401);
  }

  if (url.pathname === "/addresses" && request.method === "PUT") {
    const body = (await request.json().catch(() => null)) as { address?: unknown } | null;
    const address = normalizeAddress(body?.address, env.MAIL_DOMAIN);
    if (!address) return json({ error: `address must be a valid @${env.MAIL_DOMAIN} address` }, 400);
    await env.DB.prepare("INSERT OR IGNORE INTO addresses (address, created_at) VALUES (?, ?)")
      .bind(address, new Date().toISOString())
      .run();
    return json({ ok: true, address });
  }

  if (url.pathname === "/addresses" && request.method === "DELETE") {
    const address = normalizeAddress(url.searchParams.get("address"), env.MAIL_DOMAIN);
    if (!address) return json({ error: "invalid address" }, 400);
    await env.DB.batch([
      env.DB.prepare("DELETE FROM messages WHERE address = ?").bind(address),
      env.DB.prepare("DELETE FROM addresses WHERE address = ?").bind(address),
    ]);
    return json({ ok: true });
  }

  if (url.pathname === "/messages" && request.method === "GET") {
    const after = Number.parseInt(url.searchParams.get("after") ?? "0", 10) || 0;
    const limit = parseLimit(url.searchParams.get("limit"), 50, 100);
    const rows = await env.DB.prepare(
      `SELECT seq, id, address, from_addr AS "from", from_name, subject, text, html, received_at
         FROM messages WHERE seq > ? ORDER BY seq ASC LIMIT ?`,
    )
      .bind(after, limit)
      .all();
    // `max_seq` lets the Manager notice a reset database (its cursor would be ahead of it).
    const top = await env.DB.prepare("SELECT seq FROM sqlite_sequence WHERE name = 'messages'").first<{ seq: number }>();
    return json({ messages: rows.results, max_seq: top?.seq ?? 0 });
  }

  return json({ error: "not found" }, 404);
}

async function purge(env: Env): Promise<void> {
  const days = Number.parseInt(env.RETENTION_DAYS ?? "7", 10) || 7;
  await env.DB.prepare("DELETE FROM messages WHERE received_at < ?").bind(retentionCutoff(new Date(), days)).run();
}

export default {
  email: (message, env) => receive(message, env),
  fetch: (request, env) => api(request, env),
  scheduled: (_controller, env, ctx) => {
    ctx.waitUntil(purge(env));
  },
} satisfies ExportedHandler<Env>;
