import { blogUrl, blogFetch } from "./blog-api.js";

(() => {
  const endpoint = blogUrl("/api/blog-views");
  const counter = document.querySelector("[data-view-page]");
  if (!endpoint || !counter) return;

  const page = counter.dataset.viewPage;
  const total = counter.querySelector("[data-view-total]");
  const format = new Intl.NumberFormat(document.documentElement.lang);
  let shown = -1;

  async function browserId() {
    const key = "blog-views:v1:" + page;
    const idForPage = () => {
      const saved = localStorage.getItem(key);
      if (saved) return saved;
      const id = crypto.randomUUID();
      localStorage.setItem(key, id);
      return id;
    };

    try {
      // Keep two tabs on a new page from assigning different IDs.
      return await (navigator.locks ? navigator.locks.request(key, idForPage) : idForPage());
    } catch {
      return null;
    }
  }

  async function update() {
    const url = new URL(endpoint, location.origin);
    const options = {};
    try {
      const visitor = await browserId();
      if (visitor) {
        options.method = "POST";
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify({ page, visitor });
      } else {
        // Without a durable browser ID, display the count without inflating it.
        url.searchParams.set("page", page);
      }

      const response = await blogFetch(url, options);
      if (!response.ok) return;
      const result = await response.json();
      if (Number.isSafeInteger(result.total) && result.total >= 0 && result.total >= shown) {
        shown = result.total;
        total.textContent = format.format(result.total);
        counter.hidden = false;
      }
    } catch {
      // A network failure leaves the article and any displayed total intact.
    }
  }

  function onOpen() {
    if (document.prerendering) {
      document.addEventListener("prerenderingchange", update, { once: true });
    } else {
      update();
    }
  }

  if (document.readyState === "complete") onOpen();
  else window.addEventListener("pageshow", onOpen, { once: true });

  // A back/forward cache restore does not run this script again.
  window.addEventListener("pageshow", event => {
    if (event.persisted) onOpen();
  });
})();
