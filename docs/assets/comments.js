import { blogUrl, blogFetch } from "./blog-api.js";
import { readVisitor, getVisitor, guestLabel, displayName } from "./comment-visitor.js";

const identityKey = "blog-comment-identity:v1";
const endpoint = blogUrl("/api/blog-comments");
const page = document.querySelector("[data-view-page]")?.dataset.viewPage;
if (endpoint && page?.startsWith("posts/")) addDiscussion();

function addDiscussion() {
  const article = document.querySelector("main > article");
  article.insertAdjacentHTML("beforeend", `
    <section class="discussion" id="comments" aria-labelledby="discussion-title">
      <header class="discussion-heading">
        <h2 id="discussion-title">评论</h2>
        <button type="button" class="comment-button" data-write>写评论</button>
      </header>
      <p class="comment-status" data-list-status role="status"></p>
      <ol class="comment-list" data-comments></ol>
      <button type="button" class="comment-link" data-more hidden>加载更多评论</button>
      <dialog class="comment-dialog" aria-labelledby="comment-dialog-title">
        <form class="comment-form">
          <header class="discussion-heading">
            <h3 id="comment-dialog-title">写评论</h3>
            <button type="button" class="comment-link" data-close>关闭</button>
          </header>
          <p class="comment-status" data-reply-to hidden></p>
          <fieldset class="comment-identity">
            <legend>发表评论的身份</legend>
            <label><input name="kind" type="radio" value="guest" checked> 游客</label>
            <label><input name="kind" type="radio" value="github"> GitHub 用户名</label>
          </fieldset>
          <div data-guest>
            <label>昵称（可选）<input name="nickname" type="text" maxlength="30"></label>
            <p class="comment-status" data-guest-label hidden></p>
          </div>
          <div data-github hidden>
            <label>GitHub 用户名或个人主页链接
              <input name="github" type="text" maxlength="160" autocomplete="username" spellcheck="false" autocapitalize="none">
            </label>
            <p class="comment-status">名称会标为未验证。 <a href="https://github.com/settings/profile" target="_blank" rel="noopener">去 GitHub 查看</a></p>
          </div>
          <label>评论内容<textarea name="message" rows="5" required maxlength="2000"></textarea></label>
          <p class="comment-status" data-form-status role="status" hidden></p>
          <button class="comment-button" type="submit">发送</button>
        </form>
      </dialog>
    </section>
  `);

  const section = article.querySelector("#comments");
  const dialog = section.querySelector("dialog");
  const form = dialog.querySelector("form");
  const send = form.querySelector("button[type=submit]");
  const formStatus = form.querySelector("[data-form-status]");
  const replyLabel = form.querySelector("[data-reply-to]");
  const list = section.querySelector("[data-comments]");
  const listStatus = section.querySelector("[data-list-status]");
  const more = section.querySelector("[data-more]");
  const entries = new Map();
  const timeFormat = new Intl.DateTimeFormat(document.documentElement.lang, {
    dateStyle: "medium", timeStyle: "short",
  });
  let parent = null;
  let next = 0;
  let pending = null;
  let visitorReady;
  restoreIdentity(form);
  showIdentity();

  const shortcut = make("button", "comment-link", "评论");
  shortcut.type = "button";
  article.querySelector(".post-meta").append(shortcut);
  shortcut.addEventListener("click", () => open());
  section.querySelector("[data-write]").addEventListener("click", () => open());
  form.querySelector("[data-close]").addEventListener("click", () => {
    if (!send.disabled) dialog.close();
  });
  form.addEventListener("change", event => {
    if (event.target.name === "kind") showIdentity();
  });
  dialog.addEventListener("cancel", event => {
    if (send.disabled) event.preventDefault();
  });
  more.addEventListener("click", load);
  form.addEventListener("submit", submit);
  if (readVisitor()) identifyGuest();
  load().then(revealLinkedComment);
  window.addEventListener("hashchange", revealLinkedComment);

  function identifyGuest() {
    if (!visitorReady) {
      visitorReady = getVisitor().then(async visitor => {
        if (visitor) {
          const label = await guestLabel(visitor).catch(() => "");
          if (label) {
            const guest = form.querySelector("[data-guest-label]");
            guest.hidden = false;
            guest.textContent = "你的游客身份 " + label;
            form.elements.nickname.placeholder = label;
          }
        }
        return visitor;
      });
    }
    return visitorReady;
  }

  function showIdentity() {
    const github = form.elements.kind.value === "github";
    form.querySelector("[data-guest]").hidden = github;
    form.querySelector("[data-github]").hidden = !github;
    form.elements.github.required = github;
  }

  function open(reply = null) {
    if (dialog.open) return;
    if (parent?.id !== reply?.id) {
      form.elements.message.value = "";
      pending = null;
    }
    parent = reply;
    replyLabel.hidden = !reply;
    replyLabel.textContent = reply ? "回复 " + displayName(reply) : "";
    setError("");
    identifyGuest();
    dialog.showModal();
    form.elements.message.focus();
  }

  function setError(message) {
    formStatus.hidden = !message;
    formStatus.textContent = message;
  }

  async function load() {
    more.disabled = true;
    if (!entries.size) listStatus.textContent = "正在加载评论…";
    try {
      const url = new URL(endpoint);
      url.searchParams.set("page", page);
      url.searchParams.set("after", next);
      const response = await blogFetch(url);
      if (!response.ok) throw new Error("read failed");
      const payload = await response.json();
      for (const comment of payload.comments) entries.set(comment.id, comment);
      next = payload.next;
      more.hidden = next === null;
      render();
    } catch {
      listStatus.textContent = "评论暂时加载失败。";
      more.hidden = false;
      more.textContent = "重试加载";
    } finally {
      more.disabled = false;
    }
  }

  async function revealLinkedComment() {
    const target = /^#comment-([1-9][0-9]*)$/.exec(location.hash);
    if (!target) return;
    const id = Number(target[1]);
    if (!Number.isSafeInteger(id)) return;

    try {
      if (!entries.has(id)) {
        const url = new URL(endpoint);
        url.searchParams.set("page", page);
        url.searchParams.set("comment", id);
        const response = await blogFetch(url);
        if (!response.ok) {
          listStatus.textContent = response.status === 404 ? "这条评论已不可用。" : "暂时无法打开这条评论。";
          return;
        }
        const payload = await response.json();
        for (const comment of payload.comments) entries.set(comment.id, comment);
        render();
      }
      if (location.hash === target[0]) {
        requestAnimationFrame(() => document.getElementById("comment-" + id)?.scrollIntoView());
      }
    } catch {
      listStatus.textContent = "暂时无法打开这条评论。";
    }
  }

  async function submit(event) {
    event.preventDefault();
    if (send.disabled) return;
    const kind = form.elements.kind.value;
    const name = form.elements[kind === "github" ? "github" : "nickname"].value.trim();
    const message = form.elements.message.value.trim();
    if (!message) {
      setError("请填写评论内容。");
      return;
    }
    const details = {page, parent_id: parent?.id ?? null, kind, name, message};
    const key = JSON.stringify(details);
    if (pending?.key !== key) pending = {key, id: crypto.randomUUID()};
    send.disabled = true;
    send.textContent = "发送中…";
    setError("");
    try {
      const visitor = await identifyGuest();
      const response = await blogFetch(endpoint, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({...details, visitor, submission: pending.id}),
      });
      if (response.status === 400 && kind === "github") {
        setError("请检查 GitHub 用户名或个人主页链接。");
        return;
      }
      if (response.status === 429) {
        setError("发送过于频繁，请稍后再试。");
        return;
      }
      if (!response.ok) throw new Error("send failed");
      const comment = await response.json();
      entries.set(comment.id, comment);
      saveIdentity(kind, comment.name);
      if (kind === "github") form.elements.github.value = comment.name;
      pending = null;
      form.elements.message.value = "";
      dialog.close();
      render();
      list.querySelector("#comment-" + comment.id)?.scrollIntoView({block: "nearest"});
    } catch {
      setError("发送失败，请稍后重试。");
    } finally {
      send.disabled = false;
      send.textContent = "发送";
    }
  }

  function render() {
    const content = document.createDocumentFragment();
    const roots = new Map();
    const ordered = [...entries.values()].sort((a, b) => a.id - b.id);
    for (const comment of ordered) {
      const item = make("li", "comment-entry");
      item.id = "comment-" + comment.id;
      const meta = make("div", "comment-meta");
      if (comment.kind === "github") {
        const profile = make("a", "", displayName(comment));
        profile.href = "https://github.com/" + encodeURIComponent(comment.name);
        profile.rel = "nofollow ugc";
        meta.append(profile, make("span", "", "GitHub · 未验证"));
      } else {
        meta.append(make("strong", "", displayName(comment)));
      }
      const date = new Date(comment.created_at * 1000);
      const stamp = make("time", "", timeFormat.format(date));
      stamp.dateTime = date.toISOString();
      meta.append(stamp);
      const referenced = entries.get(comment.parent_id);
      if (referenced) meta.append(make("span", "", "回复 " + displayName(referenced)));
      const reply = make("button", "comment-link", "回复");
      reply.type = "button";
      reply.addEventListener("click", () => open(comment));
      item.append(meta, make("p", "comment-message", comment.message), reply);

      const thread = roots.get(comment.parent_id);
      if (thread) {
        thread.replies.append(item);
        roots.set(comment.id, thread);
      } else {
        const replies = make("ol", "comment-replies");
        item.append(replies);
        content.append(item);
        roots.set(comment.id, {replies});
      }
    }
    list.replaceChildren(content);
    listStatus.textContent = ordered.length ? "" : "暂无评论。";
    more.textContent = "加载更多评论";
  }
}

function make(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function saveIdentity(kind, name) {
  try {
    localStorage.setItem(identityKey, JSON.stringify({kind, name}));
  } catch {
    // The form works when browser storage is unavailable.
  }
}

function restoreIdentity(form) {
  try {
    const identity = JSON.parse(localStorage.getItem(identityKey));
    if (identity?.kind === "github") {
      form.elements.kind.value = "github";
      form.elements.github.value = identity.name;
    } else if (identity?.kind === "guest") {
      form.elements.nickname.value = identity.name;
    }
  } catch {
    // A first-time visitor can comment as a guest.
  }
}
