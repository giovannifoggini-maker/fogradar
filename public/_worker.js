/**
 * SKYTRACE — Cloudflare Pages Advanced Mode worker.
 * This worker serves static assets and the same-origin ADS-B JSON proxy.
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

async function aircraftResponse(url) {
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
    return json({ detail: "Coordinate o raggio non validi. Il raggio supportato è 25, 50, 100, 150 o 250 NM." }, 400);
  }

  const upstreamUrl = `https://api.adsb.lol/v2/lat/${lat}/lon/${lon}/dist/${dist}`;
  let upstream;
  let raw;
  try {
    upstream = await fetch(upstreamUrl, {
      method: "GET",
      headers: { "accept": "application/json" },
      cf: { cacheTtl: 0, cacheEverything: false },
    });
    raw = await upstream.text();
  } catch (_) {
    return json({ detail: "La fonte ADS-B non è raggiungibile. Controlla la connessione e riprova." }, 502);
  }

  let data;
  try {
    data = JSON.parse(raw);
  } catch (_) {
    return json({
      detail: `La fonte ADS-B ha restituito contenuto non JSON (HTTP ${upstream.status}, ${upstream.headers.get("content-type") || "tipo sconosciuto"}). Potrebbe essere temporaneamente indisponibile.`,
    }, 502);
  }

  if (!upstream.ok) {
    const status = upstream.status === 429 ? 429 : 502;
    return json({ detail: data && data.detail ? String(data.detail) : `La fonte ADS-B ha risposto con HTTP ${upstream.status}.` }, status);
  }

  if (!data || typeof data !== "object" ||
      (!Array.isArray(data.ac) && !Array.isArray(data.aircraft))) {
    const keys = data && typeof data === "object" ? Object.keys(data).slice(0, 12).join(", ") : typeof data;
    return json({ detail: `Formato restituito dalla fonte ADS-B non riconosciuto${keys ? ` (campi: ${keys})` : ""}.` }, 502);
  }

  // Normalize alternate proxy variants to the documented ADSB.lol v2 `ac` key.
  if (!Array.isArray(data.ac) && Array.isArray(data.aircraft)) data.ac = data.aircraft;
  return json(data, 200);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/health" || url.pathname === "/api/health/") {
      return json({ ok: true, service: "SKYTRACE Pages Worker", mode: "advanced" }, 200);
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
