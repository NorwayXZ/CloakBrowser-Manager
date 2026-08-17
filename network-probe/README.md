# CloakBrowser network probe

This is an optional, minimal Cloudflare Worker used by the local start page to
observe the browser's actual egress IP, request headers, HTTP protocol and TLS
metadata. It does not store requests. CORS is enabled because active debug
probes run from an HTTPS page while passive manual probes run from the local
Manager start page; the endpoint contains no credentials or private state.

Deploy from the repository root:

```bash
wrangler deploy --config network-probe/wrangler.jsonc
```

The repository default points at the deployed probe. A self-hosted probe can
be selected by setting `CLOAKBROWSER_NETWORK_PROBE_URL` before starting
Manager. The URL should not have a trailing slash.

The probe cannot prove which DNS resolver the operating system used. The local
report therefore keeps DNS policy and external DNS verification as separate
fields instead of claiming a DNS leak test that the endpoint cannot perform.
