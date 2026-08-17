function corsHeaders(request: Request): Headers {
  const origin = request.headers.get("Origin") || "*";
  const headers = new Headers({
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "access-control-allow-origin": origin,
    "access-control-allow-methods": "GET, OPTIONS",
    "access-control-allow-headers": "content-type",
  });
  return headers;
}

export default {
  async fetch(request: Request): Promise<Response> {
    const headers = corsHeaders(request);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers });
    if (request.method !== "GET") return new Response(JSON.stringify({ error: "method_not_allowed" }), { status: 405, headers });

    const cf = (request as Request & { cf?: Record<string, unknown> }).cf ?? {};
    const response = {
      observed_at: new Date().toISOString(),
      egress: {
        ip: request.headers.get("CF-Connecting-IP"),
        country: cf.country ?? null,
        region: cf.region ?? null,
        city: cf.city ?? null,
        timezone: cf.timezone ?? null,
        colo: cf.colo ?? null,
      },
      transport: {
        http_protocol: cf.httpProtocol ?? null,
        tls_version: cf.tlsVersion ?? null,
        tls_cipher: cf.tlsCipher ?? null,
        tls_client_hello_length: cf.tlsClientHelloLength ?? null,
      },
      headers: {
        user_agent: request.headers.get("User-Agent"),
        accept_language: request.headers.get("Accept-Language"),
        sec_ch_ua: request.headers.get("Sec-CH-UA"),
        sec_ch_ua_platform: request.headers.get("Sec-CH-UA-Platform"),
        sec_ch_ua_mobile: request.headers.get("Sec-CH-UA-Mobile"),
      },
      limitations: {
        dns_resolver_externally_verified: false,
        note: "HTTP endpoint can observe browser egress and TLS, but cannot prove the host OS DNS resolver path.",
      },
    };
    return new Response(JSON.stringify(response), { headers });
  },
};
