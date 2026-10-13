/**
 * SKYTRACE — Cloudflare Pages Advanced Mode worker.
 * Serves static assets and proxies live aircraft data from several public ADS-B feeds.
 * Keep this file in the Pages build output directory (public/_worker.js).
 */
const ALLOWED_RANGES = new Set([25, 50, 100, 150, 250]);

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

function dataSources(lat, lon, dist) {
  // The endpoints use the ADSBExchange-compatible v2 response schema (`ac`).
  // Try alternate community feeds when one blocks or rate-limits the request.
  return [
    {
      name: "ADSB One",
      url: `https://api.adsb.one/v2/point/${lat}/${lon}/${dist}`,
    },
    {
      name: "Airplanes.live",
      url: `https://api.airplanes.live/v2/point/${lat}/${lon}/${dist}`,
    },
    {
      name: "ADSB.lol",
      url: `https://api.adsb.lol/v2/lat/${lat}/lon/${lon}/dist/${dist}`,
    },
  ];
}

async function aircraftResponse(url) {
  const latText = url.searchParams.get("lat");
  const lonText = url.searchParams.get("lon");
  const distText = url.searchParams.get("dist");
  const lat = Number(latText);
  const lon = Number(lonText);
  const dist = Number(distText);

  if (
    latText === null || lonText === null || distText === null ||
    !Number.isFinite(lat) || lat < -90 || lat > 90 ||
    !Number.isFinite(lon) || lon < -180 || lon > 180 ||
    !ALLOWED_RANGES.has(dist)
  ) {
    return json({ detail: "Coordinate o raggio non validi. Il raggio supportato è 25, 50, 100, 150 o 250 NM." }, 400);
  }

  const failures = [];
  for (const source of dataSources(lat, lon, dist)) {
    let upstream;
    let raw;
    try {
      upstream = await fetch(source.url, {
        method: "GET",
        headers: {
          "accept": "application/json",
          "user-agent": "SKYTRACE-Radar/1.1 (public aircraft visualization)",
        },
        cf: { cacheTtl: 5, cacheEverything: true },
        signal: AbortSignal.timeout(6000),
      });
      raw = await upstream.text();
    } catch (_) {
      failures.push(`${source.name}: connessione non riuscita`);
      continue;
    }

    let data;
    try {
      data = JSON.parse(raw);
    } catch (_) {
      failures.push(`${source.name}: HTTP ${upstream.status}, risposta non JSON (${upstream.headers.get("content-type") || "tipo sconosciuto"})`);
      continue;
    }

    if (!upstream.ok) {
      const note = data && (data.detail || data.message) ? ` — ${String(data.detail || data.message).slice(0, 100)}` : "";
      failures.push(`${source.name}: HTTP ${upstream.status}${note}`);
      continue;
    }

    if (!data || typeof data !== "object" || Array.isArray(data) ||
        (!Array.isArray(data.ac) && !Array.isArray(data.aircraft))) {
      failures.push(`${source.name}: formato JSON non riconosciuto`);
      continue;
    }

    if (!Array.isArray(data.ac) && Array.isArray(data.aircraft)) data.ac = data.aircraft;
    data.skytraceSource = source.name;
    return json(data, 200);
  }

  return json({
    detail: `Nessuna fonte ADS-B disponibile. ${failures.join("; ")}. Riprova tra qualche secondo: l'accesso alle fonti pubbliche può essere limitato o temporaneamente indisponibile.`,
    providersTried: failures.length,
  }, 502);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/health" || url.pathname === "/api/health/") {
      return json({ ok: true, service: "SKYTRACE Pages Worker", mode: "advanced", providers: ["ADSB One", "Airplanes.live", "ADSB.lol"] }, 200);
    }

    if (url.pathname === "/api/aircraft" || url.pathname === "/api/aircraft/") {
      if (request.method !== "GET") {
        return json({ detail: "Metodo non supportato. Usa GET." }, 405, { allow: "GET" });
      }
      return aircraftResponse(url);
    }

    // In Pages Advanced Mode, static assets must be served through ASSETS.
    return env.ASSETS.fetch(request);
  },
};
