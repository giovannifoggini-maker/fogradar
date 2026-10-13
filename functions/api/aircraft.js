function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store, max-age=0"
    }
  });
}

export async function onRequestGet({ request }) {
  const url = new URL(request.url);
  const lat = Number(url.searchParams.get("lat"));
  const lon = Number(url.searchParams.get("lon"));
  const dist = Number(url.searchParams.get("dist"));
  const allowedRanges = new Set([25, 50, 100, 150, 250]);

  if (!Number.isFinite(lat) || lat < -90 || lat > 90 ||
      !Number.isFinite(lon) || lon < -180 || lon > 180 ||
      !allowedRanges.has(dist)) {
    return json({ detail: "Coordinate o raggio non validi." }, 400);
  }

  const upstream = `https://api.adsb.lol/v2/lat/${lat}/lon/${lon}/dist/${dist}`;
  try {
    const response = await fetch(upstream, {
      method: "GET",
      headers: { "accept": "application/json" },
      cf: { cacheTtl: 0, cacheEverything: false }
    });
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") || "application/json; charset=utf-8",
        "cache-control": "no-store, max-age=0"
      }
    });
  } catch (error) {
    return json({ detail: "La fonte ADS-B non è raggiungibile in questo momento." }, 502);
  }
}
