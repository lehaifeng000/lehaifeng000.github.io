// Set the HTTPS origin once the shared backend is deployed.
const liveOrigin = "";
const preview = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
const origin = preview ? location.origin :
  location.origin === "https://lehaifeng000.github.io" ? liveOrigin : "";

export function blogUrl(path) {
  return origin ? new URL(path, origin) : null;
}

export function blogFetch(url, options) {
  return fetch(url, {
    cache: "no-store",
    credentials: "omit",
    referrerPolicy: "no-referrer",
    signal: AbortSignal.timeout?.(8000),
    ...options,
  });
}
