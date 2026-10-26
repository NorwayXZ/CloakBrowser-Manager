# CloakBrowser mail Worker

Receives mail for the domain mailbox that AI agents use to register accounts
(see `docs/MAIL.md` for the whole picture and the one-time setup).

* `email()` — Cloudflare Email Routing hands every message for `*@your-domain` here. Mail to an
  address the Manager did not register is rejected at SMTP time; the rest is parsed
  (`postal-mime`) and stored in D1.
* `fetch()` — a small HTTPS API for the Manager, bearer-token protected (`API_TOKEN`):
  `PUT /addresses`, `DELETE /addresses?address=`, `GET /messages?after=<seq>&limit=`, `GET /health`.
* `scheduled()` — daily cleanup of mail older than `RETENTION_DAYS`.

```bash
npm install
npm run typecheck && npm test      # unit tests of the pure helpers
npm run test:integration           # real Worker under `wrangler dev`: parsing, rejection, auth, cursor
```

Deployment steps: `docs/MAIL.md`.
