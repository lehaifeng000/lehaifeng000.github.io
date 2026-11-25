const liveOrigin = "https://198.13.61.80:8443";
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
