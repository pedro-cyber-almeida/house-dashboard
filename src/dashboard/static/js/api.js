// Thin fetch wrapper around the same-origin JSON API. Cookies are carried
// automatically thanks to credentials: "same-origin".
let unauthorizedHandler = null;

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
}

async function toResult(res) {
  if (res.status === 401) {
    const err = new Error("Session expired. Please sign in again.");
    err.code = 401;
    if (unauthorizedHandler) unauthorizedHandler(err);
    throw err;
  }
  if (res.status === 204) return null;
  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const detail =
      data && data.detail
        ? typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail)
         : "Unexpected server error.";
    throw new Error(detail);
  }
  return data;
}

export async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  return toResult(res);
}

export async function upload(path, file) {
  const form = new FormData();
  form.append("file", file, file.name || "logo");
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    body: form,
  });
  return toResult(res);
}
