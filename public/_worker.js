/**
 * SKYTRACE — Cloudflare Pages Advanced Mode worker.
 * Uses public ADS-B sources with sequential fallback:
 * ADSB One, Airplanes.live, ADSB.lol and ADSB.fi.
 * Public APIs can deny requests; this code honours provider cooldowns.
 */
const PROVIDERS = [
  { name: "ADSB One", base: "https://api.adsb.one/v2/point", format: "point-v2" },
  { name: "Airplanes.live", base: "https://api.airplanes.live/v2/point", format: "point-v2" },
  { name: "ADSB.lol", base: "https://api.adsb.lol/v2/point", format: "point-v2" },
  { name: "ADSB.fi", base: "https://opendata.adsb.fi/api/v3/lat", format: "adsbfi-v3" },
];
const ALLOWED_RANGES = new Set([25, 50, 100, 150, 250]);
// Cooldown in-memory per Worker isolate: reduces repeated hits while a feed is denying requests.
const providerCooldownUntil = new Map();
const providerCooldownStatus = new Map();
const providerLastRequestAt = new Map();
const PROVIDER_MIN_INTERVAL_MS = { "ADSB.fi": 1100 };

function json(body, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-skytrace-api": "pages-worker",
      ...extraHeaders,
    },
  });
}

function validateParams(url) {
  const latText = url.searchParams.get("lat");
  const lonText = url.searchParams.get("lon");
  const distText = url.searchParams.get("dist");
  const lat = Number(latText);
  const lon = Number(lonText);
  const dist = Number(distText);
  if (latText === null || lonText === null || distText === null ||
      !Number.isFinite(lat) || lat < -90 || lat > 90 ||
      !Number.isFinite(lon) || lon < -180 || lon > 180 ||
      !ALLOWED_RANGES.has(dist)) {
    return { error: "Coordinate o raggio non validi. Usa latitudine da -90 a 90, longitudine da -180 a 180 e raggio 25, 50, 100, 150 o 250 NM." };
  }
  return { lat, lon, dist };
}

function providerUrl(provider, lat, lon, dist) {
  if (provider.format === "adsbfi-v3") {
    // ADSB.fi v3 uses /lat/{lat}/lon/{lon}/dist/{dist}, unlike the v2 point endpoints.
    return `${provider.base}/${encodeURIComponent(lat)}/lon/${encodeURIComponent(lon)}/dist/${encodeURIComponent(dist)}`;
  }
  return `${provider.base}/${encodeURIComponent(lat)}/${encodeURIComponent(lon)}/${encodeURIComponent(dist)}`;
}

async function queryProvider(provider, lat, lon, dist, appOrigin) {
  const now = Date.now();
  const minInterval = PROVIDER_MIN_INTERVAL_MS[provider.name] || 0;
  const lastRequestAt = providerLastRequestAt.get(provider.name) || 0;
  const waitMs = minInterval - (now - lastRequestAt);
  if (waitMs > 0) {
    return { ok: false, provider: provider.name, reason: `limite prudenziale: riprova tra ${Math.ceil(waitMs / 1000)} s`, status: 429, cooldown: true };
  }
  if (minInterval) providerLastRequestAt.set(provider.name, now);
  const url = providerUrl(provider, lat, lon, dist);
  let response;
  try {
    response = await fetch(url, {
      method: "GET",
      // Identify the app clearly instead of relying on a generic Worker user-agent.
      // The referrer identifies the published site; it does not change provider permissions.
      headers: {
        "accept": "application/json",
        "user-agent": `SKYTRACE-Radar/1.0 (+${appOrigin})`,
        "referer": `${appOrigin}/`,
      },
      signal: AbortSignal.timeout(10000),
    });
  } catch (error) {
    return { ok: false, provider: provider.name, reason: error?.name === "TimeoutError" ? "timeout" : "errore di connessione", status: 0 };
  }

  const contentType = response.headers.get("content-type") || "sconosciuto";
  const raw = await response.text();
  let data = null;
  try { data = JSON.parse(raw); } catch (_) { /* diagnosed below */ }

  if (!response.ok) {
    const reason = response.status === 403 ? "accesso rifiutato" : response.status === 429 ? "limite richieste raggiunto" : `HTTP ${response.status}`;
    const cooldownMs = response.status === 403 ? 10 * 60 * 1000 : response.status === 429 ? 5 * 60 * 1000 : 60 * 1000;
    providerCooldownUntil.set(provider.name, Date.now() + cooldownMs);
    providerCooldownStatus.set(provider.name, response.status);
    return { ok: false, provider: provider.name, reason, status: response.status, contentType };
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    // A 200 HTML page often indicates a provider-side block/challenge: avoid polling it repeatedly.
    providerCooldownUntil.set(provider.name, Date.now() + 5 * 60 * 1000);
    providerCooldownStatus.set(provider.name, response.status || 502);
    return { ok: false, provider: provider.name, reason: `risposta non JSON (${contentType})`, status: response.status, contentType };
  }
  const aircraft = Array.isArray(data.ac) ? data.ac : Array.isArray(data.aircraft) ? data.aircraft : null;
  if (!aircraft) {
    providerCooldownUntil.set(provider.name, Date.now() + 5 * 60 * 1000);
    providerCooldownStatus.set(provider.name, response.status || 502);
    return { ok: false, provider: provider.name, reason: `JSON senza elenco aeromobili (${Object.keys(data).slice(0, 8).join(", ") || "nessun campo"})`, status: response.status, contentType };
  }
  providerCooldownUntil.delete(provider.name);
  providerCooldownStatus.delete(provider.name);
  return { ok: true, aircraft, provider: provider.name, now: data.now || data.time || Date.now() };
}

async function aircraftResponse(url, appOrigin) {
  const params = validateParams(url);
  if (params.error) return json({ detail: params.error }, 400);

  const failures = [];
  for (const provider of PROVIDERS) {
    const cooldownUntil = providerCooldownUntil.get(provider.name) || 0;
    if (cooldownUntil > Date.now()) {
      failures.push({
        ok: false,
        provider: provider.name,
        status: providerCooldownStatus.get(provider.name) || 503,
        reason: `pausa automatica dopo un errore precedente; riprova tra circa ${Math.ceil((cooldownUntil - Date.now()) / 60000)} min`,
        cooldown: true,
      });
      continue;
    }
    const result = await queryProvider(provider, params.lat, params.lon, params.dist, appOrigin);
    if (result.ok) {
      return json({
        ac: result.aircraft,
        total: result.aircraft.length,
        time: result.now,
        skytraceSource: result.provider,
        providersTried: failures.map(item => item.provider),
        note: "Dati ADS-B pubblici. Copertura, latenza e disponibilità dipendono dai ricevitori e dal provider.",
      });
    }
    failures.push(result);
  }

  const detail = failures.map(f => `${f.provider}: ${f.status ? `HTTP ${f.status}, ` : ""}${f.reason}`).join("; ");
  const hasRateLimit = failures.some(f => f.status === 429);
  const allForbiddenOrLimited = failures.every(f => f.status === 403 || f.status === 429);
  const status = hasRateLimit ? 429 : allForbiddenOrLimited ? 503 : 502;
  return json({
    detail: `Nessuna fonte ADS-B disponibile. ${detail}. Riprova più tardi: i provider pubblici possono limitare richieste, soprattutto da server cloud.`,
    providers: failures,
  }, status);
}

// Shared edge cache: identical radar views reuse recent results and avoid making
// every visitor independently hit the public feeds. Successful data is cached for
// 20 seconds; temporary upstream failures are cached for 60 seconds. This respects
// provider limits rather than retrying aggressively. Cache API failures are non-fatal.
async function cachedAircraftResponse(url) {
  const params = validateParams(url);
  if (params.error) return json({ detail: params.error }, 400);

  const cache = globalThis.caches?.default;
  if (!cache) return aircraftResponse(url, url.origin);

  const keyUrl = new URL("/__skytrace_cache/aircraft", url.origin);
  keyUrl.searchParams.set("lat", String(params.lat));
  keyUrl.searchParams.set("lon", String(params.lon));
  keyUrl.searchParams.set("dist", String(params.dist));
  const cacheKey = new Request(keyUrl.toString(), { method: "GET" });

  try {
    const cached = await cache.match(cacheKey);
    if (cached) {
      const headers = new Headers(cached.headers);
      headers.set("x-skytrace-cache", "HIT");
      return new Response(cached.body, {
        status: cached.status,
        statusText: cached.statusText,
        headers,
      });
    }
  } catch (_) {
    // Continue to the provider if edge cache is unavailable.
  }

  const response = await aircraftResponse(url, url.origin);
  const ttl = response.ok ? 20 : (response.status === 400 ? 0 : 60);
  if (ttl > 0) {
    try {
      const body = await response.clone().text();
      const headers = new Headers(response.headers);
      headers.set("cache-control", `public, max-age=${ttl}`);
      headers.set("x-skytrace-cache", "MISS");
      await cache.put(cacheKey, new Response(body, {
        status: response.status,
        statusText: response.statusText,
        headers,
      }));
    } catch (_) {
      // Caching is an optimization and must never break the radar response.
    }
  }
  return response;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/health" || url.pathname === "/api/health/") {
      return json({
        ok: true,
        service: "SKYTRACE Pages Worker",
        mode: "advanced",
        provider: "public ADS-B fallback",
        providers: PROVIDERS.map(provider => provider.name),
        attribution: "ADSB.fi data must be credited and linked when used; public endpoint is for personal, non-commercial use.",
        credentialsRequired: false,
      });
    }
    if (url.pathname === "/api/aircraft" || url.pathname === "/api/aircraft/") {
      if (request.method !== "GET") return json({ detail: "Metodo non supportato. Usa GET." }, 405, { allow: "GET" });
      return cachedAircraftResponse(url);
    }
    return env.ASSETS.fetch(request);
  },
};
