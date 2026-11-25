export const visitorStorage = "blog-comment-visitor:v1";
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;

export function readVisitor() {
  try {
    const key = localStorage.getItem(visitorStorage);
    return key && uuid.test(key) ? key : null;
  } catch {
    return null;
  }
}

export async function getVisitor() {
  const existing = readVisitor();
  if (existing) return existing;
  const obtain = () => {
    const key = readVisitor() ?? crypto.randomUUID();
    localStorage.setItem(visitorStorage, key);
    return key;
  };
  try {
    return await (navigator.locks ? navigator.locks.request(visitorStorage, obtain) : obtain());
  } catch {
    return null;
  }
}

export async function guestLabel(key) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(key));
  return "游客" + [...new Uint8Array(digest, 0, 4)]
    .map(byte => byte.toString(16).padStart(2, "0")).join("").toUpperCase();
}

export function displayName(comment) {
  return comment.kind === "github" ? "@" + comment.name : comment.name || "游客";
}
