// End-to-end check of the Worker under `wrangler dev` (local D1, local email trigger).
//   npm install && node test/integration.mjs
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PORT = 8799;
const BASE = `http://127.0.0.1:${PORT}`;
const TOKEN = "integration-token";
const DOMAIN = "mail.test";
const persist = mkdtempSync(join(tmpdir(), "cbm-mail-"));
const wrangler = (args) => spawnSync("npx", ["wrangler", ...args], { encoding: "utf8" });

const migrate = wrangler(["d1", "migrations", "apply", "cloakbrowser-mail", "--local", "--persist-to", persist]);
assert.equal(migrate.status, 0, migrate.stdout + migrate.stderr);

const dev = spawn(
  "npx",
  ["wrangler", "dev", "--local", "--port", String(PORT), "--persist-to", persist,
   "--var", `API_TOKEN:${TOKEN}`, "--var", `MAIL_DOMAIN:${DOMAIN}`],
  { stdio: ["ignore", "pipe", "pipe"] },
);
let log = "";
dev.stdout.on("data", (d) => (log += d));
dev.stderr.on("data", (d) => (log += d));

const call = (path, { method = "GET", token = TOKEN, body } = {}) =>
  fetch(BASE + path, {
    method,
    headers: { ...(token ? { authorization: `Bearer ${token}` } : {}), "content-type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });

const deliver = (to, raw) =>
  fetch(`${BASE}/cdn-cgi/handler/email?from=${encodeURIComponent("noreply@acme.example")}&to=${encodeURIComponent(to)}`, {
    method: "POST",
    body: raw,
  });

const mime = ({ to, subject, text, html }) =>
  [
    "From: Acme Support <noreply@acme.example>",
    `To: ${to}`,
    `Subject: ${subject}`,
    "MIME-Version: 1.0",
    "Message-ID: <abc123@acme.example>",
    html ? 'Content-Type: multipart/alternative; boundary="b1"' : "Content-Type: text/plain; charset=utf-8",
    "",
    ...(html
      ? ["--b1", "Content-Type: text/plain; charset=utf-8", "", text, "--b1", "Content-Type: text/html; charset=utf-8", "", html, "--b1--"]
      : [text]),
    "",
  ].join("\r\n");

let failed = false;
try {
  for (let i = 0; i < 120; i++) {
    const up = await fetch(`${BASE}/health`).then((r) => r.ok).catch(() => false);
    if (up) break;
    if (i === 119) throw new Error("wrangler dev did not start:\n" + log);
    await new Promise((r) => setTimeout(r, 500));
  }

  // health is public; everything else needs the token
  const health = await (await call("/health", { token: null })).json();
  assert.equal(health.domain, DOMAIN);
  assert.equal((await call("/messages", { token: null })).status, 401);
  assert.equal((await call("/messages", { token: "wrong" })).status, 401);

  // registering: only addresses on the domain
  assert.equal((await call("/addresses", { method: "PUT", body: { address: "x@other.com" } })).status, 400);
  const address = `nina.shaw42@${DOMAIN}`;
  assert.equal((await call("/addresses", { method: "PUT", body: { address: address.toUpperCase() } })).status, 200);

  // mail to a registered address is stored and parsed; to an unknown one it is refused
  const ok = await deliver(address, mime({ to: address, subject: "Your Acme code", text: "Your code is 483920", html: '<p>Your code is <b>483920</b></p><a href="https://acme.example/verify?t=1">Verify</a>' }));
  assert.equal(ok.status, 200, await ok.text());
  const unknown = await deliver(`ghost@${DOMAIN}`, mime({ to: `ghost@${DOMAIN}`, subject: "hi", text: "hi" }));
  assert.notEqual(unknown.status, 200, "unknown recipient must be rejected");

  const list = await (await call("/messages?after=0")).json();
  assert.equal(list.messages.length, 1);
  const [m] = list.messages;
  assert.equal(m.address, address);
  assert.equal(m.from, "noreply@acme.example");
  assert.equal(m.from_name, "Acme Support");
  assert.equal(m.subject, "Your Acme code");
  assert.match(m.text, /483920/);
  assert.match(m.html, /acme\.example\/verify/);
  assert.equal(list.max_seq, m.seq);

  // cursor semantics: nothing after the newest
  assert.equal((await (await call(`/messages?after=${m.seq}`)).json()).messages.length, 0);

  // forgetting an address removes its mail
  assert.equal((await call(`/addresses?address=${address}`, { method: "DELETE" })).status, 200);
  assert.equal((await (await call("/messages?after=0")).json()).messages.length, 0);
  const after = await deliver(address, mime({ to: address, subject: "late", text: "late" }));
  assert.notEqual(after.status, 200);
  console.log("mail-worker integration: ok");
} catch (error) {
  failed = true;
  console.error(error);
  console.error("--- wrangler log ---\n" + log.slice(-3000));
} finally {
  dev.kill("SIGTERM");
  setTimeout(() => {
    rmSync(persist, { recursive: true, force: true });
    process.exit(failed ? 1 : 0);
  }, 500);
}
