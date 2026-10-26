"""A tiny sign-up site for trying the domain mailbox end to end, offline.

    python scripts/mail_signup_demo_site.py --port 18767 --worker http://127.0.0.1:8799

* ``/signup``  email, username, password, confirm password
* it "sends" a confirmation mail by handing a MIME message to the mail Worker's local
  email trigger (``wrangler dev``: ``/cdn-cgi/handler/email``), exactly where Cloudflare
  Email Routing would deliver real mail; a recipient the Worker does not know is refused,
  and the site says so
* ``/verify``  the six-digit code from the mail, or the link in it (``/confirm?token=``)
* ``/state``   JSON of what the site really received (for checking a test run)

It is a test fixture: passwords are kept in memory and shown by ``/state``.
"""

from __future__ import annotations

import argparse
import html
import json
import random
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE: dict = {"pending": {}, "accounts": [], "mail_log": []}
LOCK = threading.Lock()
WORKER = ""

PAGE = """<!doctype html><meta charset="utf-8"><title>{title}</title>
<main style="font:16px sans-serif;max-width:420px;margin:40px auto"><h1>{title}</h1>{body}</main>"""

SIGNUP = """<form method="post" action="/signup">
<p><label for="email">Email</label><br><input id="email" name="email" type="email" required></p>
<p><label for="username">Username</label><br><input id="username" name="username" required></p>
<p><label for="password">Password</label><br><input id="password" name="password" type="password" required></p>
<p><label for="confirm">Confirm password</label><br><input id="confirm" name="confirm" type="password" required></p>
<p><button type="submit">Create account</button></p></form>"""

VERIFY = """<p>We sent a code to <b>{email}</b>.</p>
<form method="post" action="/verify"><input type="hidden" name="email" value="{email}">
<p><label for="code">Verification code</label><br><input id="code" name="code" autocomplete="off" required></p>
<p><button type="submit">Verify</button></p></form>"""


def deliver(email: str, code: str, token: str, port: int) -> tuple[bool, str]:
    link = f"http://127.0.0.1:{port}/confirm?token={token}"
    raw = "\r\n".join([
        "From: Demo Site <noreply@demo-site.example>", f"To: {email}", "Subject: Confirm your Demo Site account",
        "MIME-Version: 1.0", f"Message-ID: <{token}@demo-site.example>",
        'Content-Type: multipart/alternative; boundary="b1"', "",
        "--b1", "Content-Type: text/plain; charset=utf-8", "",
        f"Welcome!\r\n\r\nYour verification code is {code}.\r\nOr confirm with one click: {link}\r\n",
        "--b1", "Content-Type: text/html; charset=utf-8", "",
        f'<p>Your verification code is <b>{code}</b>.</p><p><a href="{link}">Confirm my account</a></p>',
        "--b1--", "",
    ]).encode()
    url = f"{WORKER}/cdn-cgi/handler/email?from={urllib.parse.quote('noreply@demo-site.example')}&to={urllib.parse.quote(email)}"
    try:
        request = urllib.request.Request(url, data=raw, method="POST", headers={"Content-Type": "message/rfc822"})
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status == 200, ""
    except Exception as exc:  # the Worker rejects unknown recipients
        return False, str(exc)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _page(self, title: str, body: str, status: int = 200) -> None:
        self._send(status, PAGE.format(title=html.escape(title), body=body))

    def _form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        return {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode()).items()}

    def _confirm(self, email: str) -> None:
        with LOCK:
            pending = STATE["pending"].pop(email, None)
            if pending:
                STATE["accounts"].append({"email": email, "username": pending["username"], "password": pending["password"], "verified": True})
        if pending:
            self._page("Account verified", f"<p>Welcome, <b>{html.escape(pending['username'])}</b>! Your account is ready.</p>")
        else:
            self._page("Verification failed", "<p>That code or link is not valid.</p>", 400)

    def do_GET(self) -> None:
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/signup":
            self._page("Create your account", SIGNUP)
        elif url.path == "/confirm":
            token = urllib.parse.parse_qs(url.query).get("token", [""])[0]
            with LOCK:
                email = next((e for e, p in STATE["pending"].items() if p["token"] == token), None)
            self._confirm(email) if email else self._page("Verification failed", "<p>That link is not valid.</p>", 400)
        elif url.path == "/state":
            with LOCK:
                self._send(200, json.dumps(STATE), "application/json")
        else:
            self._page("Demo site", '<p><a href="/signup">Sign up</a></p>')

    def do_POST(self) -> None:
        form = self._form()
        if self.path == "/signup":
            email, password = form.get("email", "").strip().lower(), form.get("password", "")
            if not email or password != form.get("confirm") or len(password) < 10:
                return self._page("Create your account", "<p style='color:#b00'>Check the form: passwords must match and be 10+ characters.</p>" + SIGNUP, 400)
            code, token = f"{random.randrange(10**6):06d}", f"{random.getrandbits(64):016x}"
            ok, error = deliver(email, code, token, self.server.server_address[1])
            with LOCK:
                STATE["mail_log"].append({"to": email, "delivered": ok, "error": error})
                if ok:
                    STATE["pending"][email] = {"username": form.get("username", ""), "password": password, "code": code, "token": token}
            if not ok:
                return self._page("Create your account", "<p style='color:#b00'>We could not send the confirmation email to that address.</p>" + SIGNUP, 400)
            self._page("Check your email", VERIFY.format(email=html.escape(email)))
        elif self.path == "/verify":
            email = form.get("email", "").strip().lower()
            with LOCK:
                pending = STATE["pending"].get(email)
            if pending and form.get("code", "").strip() == pending["code"]:
                self._confirm(email)
            else:
                self._page("Verification failed", "<p>That code is not valid.</p>" + VERIFY.format(email=html.escape(email)), 400)
        else:
            self._send(404, "not found")


def main() -> None:
    global WORKER
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=18767)
    parser.add_argument("--worker", default="http://127.0.0.1:8799", help="mail Worker running under `wrangler dev`")
    args = parser.parse_args()
    WORKER = args.worker.rstrip("/")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
