import { blogUrl, blogFetch } from "./blog-api.js";
import { readVisitor, visitorStorage, guestLabel, displayName } from "./comment-visitor.js";

const endpoint = blogUrl("/api/blog-replies");
const panel = document.querySelector("[data-reply-inbox]");
if (endpoint && panel) showInbox();

function showInbox() {
  const opener = panel.querySelector("[data-inbox-open]");
  const badge = panel.querySelector("[data-inbox-badge]");
  const dialog = panel.querySelector("dialog");
  const list = panel.querySelector("[data-inbox-list]");
  const status = panel.querySelector("[data-inbox-status]");
  const more = panel.querySelector("[data-inbox-more]");
  const titles = new Map(
    [...document.querySelectorAll(".post-list h3 a")].map(link => [
      new URL(link.href).pathname.replace(/^\//, "").replace(/\/index\.html$/, ""),
      link.textContent.trim(),
    ]),
  );
  const time = new Intl.DateTimeFormat(document.documentElement.lang, {
    dateStyle: "medium", timeStyle: "short",
  });
  let next = null;
  let refreshing = false;

  opener.addEventListener("click", () => {
    dialog.showModal();
    if (!list.children.length) refresh();
  });
  panel.querySelector("[data-inbox-close]").addEventListener("click", () => dialog.close());
  more.addEventListener("click", () => refresh(next));
  window.addEventListener("pageshow", event => {
    if (event.persisted) refresh();
  });
  window.addEventListener("storage", event => {
    if (event.key === visitorStorage) refresh();
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !dialog.open) refresh();
  });
  refresh();

  async function request(details) {
    const visitor = readVisitor();
    if (!visitor) throw new Error("missing visitor");
    const reply = await blogFetch(endpoint, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({visitor, ...details}),
      keepalive: details.read !== undefined,
    });
    if (!reply.ok) throw new Error("replies unavailable");
    return reply.json();
  }

  function setBadge(unread) {
    badge.hidden = unread === 0;
    badge.textContent = unread ? unread + " 条未读" : "";
  }

  async function refresh(before) {
    const visitor = readVisitor();
    panel.hidden = !visitor;
    if (!visitor || refreshing) return;
    refreshing = true;
    more.disabled = true;
    guestLabel(visitor).then(label => {
      panel.querySelector("[data-inbox-guest]").textContent = label;
    }).catch(() => {});
    try {
      const data = await request(before ? {before} : {});
      if (!before) list.replaceChildren();
      for (const item of data.replies) addReply(item);
      next = data.next;
      more.hidden = next === null;
      setBadge(data.unread);
      status.textContent = list.children.length ? "" : "暂无回复。";
    } catch {
      status.textContent = "回复提醒暂时无法加载。";
    } finally {
      refreshing = false;
      more.disabled = false;
    }
  }

  function addReply(reply) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = displayName(reply) + " 回复了你 · " +
      (titles.get(reply.page) ?? reply.page.split("/").at(-1));
    const indicator = document.createElement("span");
    indicator.className = "reply-unread";
    indicator.textContent = "未读";
    indicator.hidden = reply.seen;
    summary.append(indicator);

    const message = document.createElement("p");
    message.className = "comment-message";
    message.textContent = reply.message;
    const stamp = document.createElement("p");
    stamp.className = "comment-status";
    stamp.textContent = time.format(new Date(reply.created_at * 1000));
    const link = document.createElement("a");
    link.href = "/" + reply.page + "/index.html#comment-" + reply.id;
    link.textContent = "跳到文章里的回复";
    details.append(summary, message, stamp, link);
    list.append(details);

    let marking = false;
    details.addEventListener("toggle", async () => {
      if (!details.open || reply.seen || marking) return;
      marking = true;
      try {
        const result = await request({read: reply.id});
        reply.seen = true;
        indicator.hidden = true;
        setBadge(result.unread);
      } catch {
        // The reply stays readable if marking it fails.
      } finally {
        marking = false;
      }
    });
  }
}
