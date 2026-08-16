// Front-end shell: login, dashboard, settings, theming and hash routing.
import { api, setUnauthorizedHandler } from "./api.js";
import { mountAdmin } from "./admin.js";

const els = {
  view: document.getElementById("view"),
  topbar: document.getElementById("topbar"),
  clock: document.getElementById("clock"),
  roleBadge: document.getElementById("role-badge"),
  chipName: document.getElementById("chip-name"),
  chipAvatar: document.getElementById("chip-avatar"),
  chipWrap: document.getElementById("chip-wrap"),
  navSettings: document.getElementById("nav-settings"),
  navAdmin: document.getElementById("nav-admin"),
  themeToggle: document.getElementById("theme-toggle"),
  logout: document.getElementById("logout"),
  toasts: document.getElementById("toasts"),
  host: document.getElementById("host"),
};

const state = { me: null };

// ---------- tiny DOM builder (no inline styles/events to satisfy CSP) --------
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, val] of Object.entries(attrs)) {
    if (val === null || val === undefined || val === false) continue;
    if (key === "class") el.className = val;
    else if (key === "html") el.innerHTML = val;
    else if (key === "value") el.value = val;
    else if (key === "checked") el.checked = !!val;
    else if (key === "text") el.textContent = val;
    else if (key.startsWith("on") && typeof val === "function") el.addEventListener(key.slice(2), val);
    else el.setAttribute(key, val);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(child));
  }
  return el;
}

function toast(message, kind = "ok") {
  const el = h("div", { class: `toast ${kind}` }, message);
  els.toasts.append(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 250);
  }, 3400);
}

function initials(name) {
  const parts = (name || "?").trim().split(/\s+/).filter(Boolean);
  return parts.slice(0, 2).map((p) => p[0]).join("").toUpperCase() || "?";
}

// Any icon content is displayed through <img>: a malicious SVG never runs
// because the browser treats the payload as a resource, not as DOM.
let appName = "House Dashboard";
async function loadBrand() {
  try {
    const b = await api("/api/brand");
    if (b && b.name) appName = b.name;
  } catch {
    /* keep default */
  }
  document.title = appName;
  document.querySelectorAll("[data-brand]").forEach((el) => (el.textContent = appName));
}

function iconSrc(icon) {
  if (!icon) return null;
  if (icon.startsWith("data:")) return icon;
  if (icon.includes("<svg")) return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(icon);
  return icon;
}

function hueFor(name) {
  let h = 0;
  const n = name || "";
  for (let i = 0; i < n.length; i++) h = (h * 31 + n.charCodeAt(i)) % 360;
  return h;
}

function iconTile(cls, icon, fallback) {
  const src = iconSrc(icon);
  if (src) return h("img", { class: cls, src, alt: "", ...{ draggable: "false" } });
  const letter = (fallback || "?").trim().charAt(0).toUpperCase() || "?";
  return h(
    "span",
    { class: `${cls} tile-fallback`, style: `background:hsl(${hueFor(fallback)} 52% 46%)` },
    letter,
  );
}

const LED_META = {
  online: { dot: "led-online", label: "online", title: "Service reachable" },
  offline: { dot: "led-offline", label: "offline", title: "Service unreachable (no network route)" },
  degraded: { dot: "led-degraded", label: "degraded", title: "Responding, but its health endpoint is unconfirmed" },
  unknown: { dot: "led-unknown", label: "unknown", title: "Unknown (hostname does not resolve on the server)" },
};

// ---------- theming ---------------------------------------------------------
const THEMES = ["system", "light", "dark"];
const lightScheme = window.matchMedia("(prefers-color-scheme: light)");
function applyTheme(theme) {
  const dark = theme === "system" ? !lightScheme.matches : theme === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}
lightScheme.addEventListener("change", () => {
  if (state.me && (state.me.theme || "system") === "system") applyTheme(state.me.theme);
});

async function cycleTheme() {
  if (!state.me) return;
  const current = state.me.theme || "system";
  const next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
  try {
    const me = await api("/api/me", { method: "PATCH", body: { theme: next } });
    state.me.theme = me.theme;
    applyTheme(me.theme);
    toast(`Theme: ${me.theme}`);
  } catch (err) {
    toast(err.message, "err");
  }
}

function startClock() {
  let fmt;
  try {
    fmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    fmt = null;
  }
  const tick = () => (els.clock.textContent = fmt ? fmt.format(new Date()) : new Date().toLocaleTimeString());
  tick();
  setInterval(tick, 1000);
}

function loading(text = "Loading…") {
  return h("div", { class: "page-loading" }, text);
}

// ---------- login -----------------------------------------------------------
function showLogin(error) {
  state.me = null;
  els.topbar.hidden = true;
  els.view.innerHTML = "";
  const errorEl = h("div", { class: "form-error" }, error || "");

  const username = h("input", { name: "username", autocomplete: "username", required: true, autofocus: true });
  const password = h("input", { type: "password", name: "password", autocomplete: "current-password", required: true });
  const form = h(
    "form",
    {
      class: "",
      onsubmit: async (e) => {
        e.preventDefault();
        try {
          await api("/api/auth/login", {
            method: "POST",
            body: { username: username.value.trim(), password: password.value },
          });
          errorEl.textContent = "";
          await initUser();
        } catch (err) {
          errorEl.textContent = err.message;
        }
      },
    },
    h("label", { class: "field" }, h("span", {}, "Username"), username),
    h("label", { class: "field" }, h("span", {}, "Password"), password),
    h("button", { type: "submit", class: "btn primary", style: "display:flex;width:100%;margin-top:0.4rem" }, "Sign in"),
    errorEl,
  );

  const card = h(
    "div",
    { class: "login-card" },
    h("div", { class: "login-brand" }, h("span", { class: "brand-dot" }), "DASHBOARD"),
    h("h1", {}, appName),
    h("p", { class: "muted small" }, "Sign in to view your services."),
    form,
  );
  els.view.append(h("div", { class: "login-wrap" }, card));
}

// ---------- bootstrap after auth -------------------------------------------
function paintChrome(me) {
  els.chipName.textContent = me.display_name || me.username;
  const avatarSrc = iconSrc(me.avatar);
  if (avatarSrc) {
    els.chipAvatar.replaceChildren(h("img", { src: avatarSrc, alt: "", ...{ "draggable": "false" } }));
  } else {
    els.chipAvatar.replaceChildren(
      h(
        "span",
        {
          style: `background:hsl(${hueFor(me.display_name || me.username)} 52% 46%);width:100%;height:100%;display:grid;place-items:center;`,
        },
        initials(me.display_name || me.username),
      ),
    );
  }
  els.chipWrap.title = `${me.username} · ${me.role}`;
  els.roleBadge.textContent = me.role;
  els.navAdmin.hidden = me.role !== "admin";
  applyTheme(me.theme);
  els.host.textContent = location.hostname || "local";
  els.topbar.hidden = false;
}

async function initUser() {
  try {
    state.me = await api("/api/me");
  } catch {
    showLogin("Invalid session.");
    return;
  }
  applyTheme(state.me.theme);
  paintChrome(state.me);
  route();
}

// ---------- routing ---------------------------------------------------------
function route() {
  const me = state.me;
  if (!me) {
    showLogin();
    return;
  }
  const name = location.hash.replace(/^#\/?/, "").toLowerCase();
  if (name === "admin" && me.role === "admin") {
    mountAdmin(els.view, me);
    return;
  }
  if (name === "settings") {
    mountSettings(els.view, me);
    return;
  }
  loadDashboard();
}

// ---------- dashboard -------------------------------------------------------
let dashServices = []; // last /assigned payload, flat, in server order
let dashQuery = "";
let groupsEl = null;
let dashIndex = new Map(); // service id -> service row (current view)

const UNGROUPED = "No category";

const norm = (v) => (v || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");

function groupKey(s) {
  return (s.category || "").trim() || UNGROUPED;
}

function sortedGroupLabels(labels) {
  return labels.sort((a, b) => {
    const aOut = a === UNGROUPED ? 1 : 0;
    const bOut = b === UNGROUPED ? 1 : 0;
    if (aOut !== bOut) return aOut - bOut;
    return a.localeCompare(b, undefined, { sensitivity: "base" });
  });
}

function serviceCard(s, { nav }) {
  const led = LED_META[s.online] || LED_META.unknown;
  const tile = h(
    "a",
    {
      class: `tile tile--${s.online}`,
      "data-sid": String(s.id),
      href: s.url,
      target: "_blank",
      rel: "noopener noreferrer",
      title: s.url,
    },
    iconTile("tile-logo", s.icon, s.name),
    h(
      "span",
      { class: "tile-body" },
      h("span", { class: "tile-name" }, s.name),
      s.description ? h("span", { class: "tile-desc" }, s.description) : null,
      h("span", { class: "tile-status", title: led.title },
        h("span", { class: `tile-dot ${led.dot}`, "aria-hidden": "true" }),
        led.label,
      ),
    ),
  );
  if (!nav) return tile;
  const navEl = h("span", { class: "tile-nav" },
    nav.up
      ? h("button", {
          type: "button",
          class: "tile-btn",
          title: "Move up",
          "aria-label": `Move ${s.name} up`,
          onclick: (e) => { e.preventDefault(); moveInCategory(s, nav.up); },
        }, "\u2191")
      : null,
    nav.down
      ? h("button", {
          type: "button",
          class: "tile-btn",
          title: "Move down",
          "aria-label": `Move ${s.name} down`,
          onclick: (e) => { e.preventDefault(); moveInCategory(s, nav.down); },
        }, "\u2193")
      : null,
  );
  return h("div", { class: "tile-wrap" }, tile, navEl);
}

function renderGroups() {
  const q = norm(dashQuery);
  // Sort buttons only show on the full, unfiltered view: the reorder API
  // expects the exact assigned set, and a filtered subset would be ambiguous.
  const reorder = state.me.role === "user" && !q;

  const byGroup = new Map();
  dashIndex = new Map();
  for (const s of dashServices) {
    if (q && !norm(s.name).includes(q) && !norm(s.description).includes(q)) continue;
    dashIndex.set(s.id, s);
    const key = groupKey(s);
    if (!byGroup.has(key)) byGroup.set(key, []);
    byGroup.get(key).push(s);
  }

  groupsEl.replaceChildren();
  if (!byGroup.size) {
    groupsEl.append(
      h(
        "div",
        { class: "empty" },
          h("h2", {}, dashQuery ? "No services found" : "No services assigned yet"),
          dashQuery ? "Try a different search term." : "An administrator needs to assign services to your account.",
      ),
    );
    return;
  }
  for (const key of sortedGroupLabels([...byGroup.keys()])) {
    const items = byGroup.get(key);
    const grid = h(
      "section",
      { class: "grid" },
      ...items.map((s, idx) =>
        serviceCard(s, {
          nav: reorder
            ? {
                up: idx > 0 ? items[idx - 1] : null,
                down: idx < items.length - 1 ? items[idx + 1] : null,
              }
            : null,
        }),
      ),
    );
    groupsEl.append(
      h(
        "section",
        { class: "group" },
        h("h3", { class: "group-title" }, key, h("span", { class: "group-count" }, String(items.length))),
        grid,
      ),
    );
  }
}

// ---------- reorder: move up/down within a category ------------------------
let reorderBusy = false;

function moveInCategory(svc, target) {
  if (reorderBusy || !target || svc === target) return;
  const from = dashServices.indexOf(svc);
  const to = dashServices.indexOf(target);
  if (from < 0 || to < 0) return;
  const next = dashServices.slice();
  next[from] = target;
  next[to] = svc;
  reorderBusy = true;
  api("/api/services/order", { method: "PUT", body: { service_ids: next.map((s) => s.id) } })
    .then(() => {
      dashServices = next;
      renderGroups();
    })
    .catch((err) => {
      renderGroups();
      toast(err.message, "err");
    })
    .finally(() => {
      reorderBusy = false;
    });
}

async function loadDashboard() {
  els.view.innerHTML = "";
  els.view.append(loading("Loading your services…"));
  try {
    const services = await api("/api/services/assigned");
    els.view.innerHTML = "";
    dashServices = services;
    dashQuery = "";
    const online = services.filter((s) => s.online === "online").length;
    const degraded = services.filter((s) => s.online === "degraded").length;
    const checked = services.map((s) => s.checked_at).filter(Boolean).sort().at(-1);
    const checkedLabel = checked ? ` at ${new Date(checked).toLocaleTimeString()}` : "";
    const summaryTitle =
      "Verified on the server" +
      checkedLabel +
      " · results are cached for 30 s";
    const countParts = [`${online}/${services.length} online`];
    if (degraded) countParts.push(`${degraded} degraded`);
    const summary = h("span", { class: "muted small", title: summaryTitle }, ` ${countParts.join(" · ")}`);

    const isSolo = services.length <= 1;
    const searchInput = isSolo
      ? null
      : h("input", {
          class: "search",
          type: "search",
          placeholder: "Search services…",
          "aria-label": "Search services",
          maxlength: "60",
          oninput: (e) => {
            dashQuery = e.target.value;
            renderGroups();
          },
          onkeydown: (e) => {
            if (e.key === "Escape") {
              e.target.value = "";
              dashQuery = "";
              renderGroups();
            }
          },
        });

    groupsEl = h("div", { class: "groups" });
    els.view.append(
      h("div", { class: "page-head" }, h("p", { class: "page-title" }, "Services"), searchInput, summary),
      groupsEl,
    );
    if (!services.length) {
      groupsEl.append(
        h(
          "div",
          { class: "empty" },
          h("h2", {}, "No services assigned yet"),
          "An administrator needs to assign services to your account.",
        ),
      );
      return;
    }
    if (isSolo) {
      const grid = h("section", { class: "grid single" }, ...services.map((s) => serviceCard(s, {})));
      groupsEl.append(grid);
    } else {
      renderGroups();
    }
  } catch (err) {
    els.view.innerHTML = "";
    if (err.code === 401) return;
    els.view.append(h("div", { class: "empty" }, h("h2", {}, "Could not be loaded"), err.message));
  }
}

// ---------- settings (user / admin own profile) ----------------------------
function fileToDataUrl(file, maxBytes = 1_500_000) {
  return new Promise((resolve, reject) => {
    if (!file.type.startsWith("image/")) return reject(new Error("Choose an image."));
    if (file.size > maxBytes) return reject(new Error("The image must be smaller than 1.5 MB."));
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("Could not read the image."));
    reader.readAsDataURL(file);
  });
}

function mountSettings(root, me) {
  root.innerHTML = "";
  const preview = me.avatar
    ? h("span", { class: "avatar-preview" }, h("img", { src: me.avatar, alt: "" }))
    : h("span", { class: "avatar-preview" }, initials(me.display_name || me.username));

  const displayName = h("input", { value: me.display_name, placeholder: "Display name", required: false });
  const avatarFile = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp,image/svg+xml" });
  const removeAvatar = h("button", { class: "btn ghost", type: "button" }, "Remove");
  const themeSel = h(
    "select",
    {},
    ...THEMES.map((t) => h("option", { value: t, selected: t === me.theme ? "selected" : null }, t)),
  );

  let pendingAvatar = me.avatar || null;
  const onPick = async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file) return;
    try {
      pendingAvatar = await fileToDataUrl(file);
      preview.replaceChildren(h("img", { src: pendingAvatar, alt: "" }));
    } catch (err) {
      toast(err.message, "err");
    }
  };
  avatarFile.addEventListener("change", onPick);
  removeAvatar.onclick = () => {
    pendingAvatar = null;
    preview.replaceChildren(initials(displayName.value || me.username));
  };

  const save = async (e) => {
    e.preventDefault();
    try {
      const body = { display_name: displayName.value.trim(), theme: themeSel.value, avatar: pendingAvatar };
      const updated = await api("/api/me", { method: "PATCH", body });
      Object.assign(me, updated);
      paintChrome(me);
      toast("Settings saved.");
      initUser(); // re-render to refresh chip
    } catch (err) {
      toast(err.message, "err");
    }
  };

  const back = h(
    "button",
    { class: "linknav", type: "button", title: "Back to the dashboard", onclick: () => { location.hash = ""; } },
    "← Dashboard",
  );
  root.append(h("div", { class: "page-head" }, h("p", { class: "page-title" }, "Account settings"), back));
  root.append(
    h(
      "section",
      { class: "panel" },
      h("h2", {}, "Profile"),
      h(
        "div",
        { class: "avatar-row" },
        preview,
        h(
          "div",
          { class: "row-actions" },
          h("label", { class: "btn" }, "Choose photo", avatarFile),
          removeAvatar,
        ),
      ),
      h("form", { onsubmit: save }, h("label", { class: "field" }, h("span", {}, "Display name"), displayName),
        h("div", { class: "form-grid" }, h("label", { class: "field" }, h("span", {}, "Theme"), themeSel)),
        h("div", { class: "row-actions" }, h("button", { class: "btn primary", type: "submit" }, "Save changes"))),
    ),
  );

  const curPw = h("input", { type: "password", autocomplete: "current-password" });
  const newPw = h("input", { type: "password", autocomplete: "new-password", minlength: 8 });
  const confPw = h("input", { type: "password", autocomplete: "new-password", minlength: 8 });
  const pwErr = h("div", { class: "form-error" });
  const changePw = async (e) => {
    e.preventDefault();
      if (newPw.value !== confPw.value) {
        pwErr.textContent = "The new passwords do not match.";
      return;
    }
    try {
      const msg = await api("/api/me/password", {
        method: "POST",
        body: { current_password: curPw.value, new_password: newPw.value },
      });
      pwErr.textContent = "";
      curPw.value = "";
      newPw.value = "";
      confPw.value = "";
      toast(msg.message);
    } catch (err) {
      pwErr.textContent = err.message;
    }
  };
  root.append(
    h(
      "section",
      { class: "panel" },
      h("h2", {}, "Change password"),
      h("p", { class: "sub" }, "Minimum 8 characters."),
      h("form", { onsubmit: changePw }, h("label", { class: "field" }, h("span", {}, "Current password"), curPw),
        h("label", { class: "field" }, h("span", {}, "New password"), newPw),
        h("label", { class: "field" }, h("span", {}, "Confirm new password"), confPw),
        h("div", { class: "row-actions" }, h("button", { class: "btn primary", type: "submit" }, "Change password")),
        pwErr),
    ),
  );
}

// ---------- auth exit -------------------------------------------------------
async function logout() {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch {
    /* ignore */
  }
  location.hash = "";
  showLogin("Signed out.");
}

// ---------- wiring ----------------------------------------------------------
setUnauthorizedHandler(() => {
  if (state.me) {
    state.me = null;
    els.topbar.hidden = true;
    showLogin("Signed out. Please sign in again.");
  }
});

els.navSettings.addEventListener("click", () => (location.hash = "#/settings"));
els.navAdmin.addEventListener("click", () => (location.hash = "#/admin"));
els.themeToggle.addEventListener("click", cycleTheme);
els.logout.addEventListener("click", logout);
window.addEventListener("hashchange", () => route());

// ---------- PWA shell -------------------------------------------------------
// Install the service worker on secure contexts so the dashboard can be
// installed to the start screen and its shell opens offline. Health states
// are always computed server-side, so an offline shell shows last-known
// status and the live view returns as soon as the server is reachable.
(function registerServiceWorker() {
  const secure =
    location.protocol === "https:" ||
    (location.protocol === "http:" && (location.hostname === "localhost" || location.hostname === "127.0.0.1"));
  if (secure && "serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
      /* ignored: unsupported/disabled — the app works fine without it */
    });
  }
})();

(async function start() {
  startClock();
  loadBrand();
  try {
    state.me = await api("/api/me");
    await initUser();
  } catch {
    showLogin();
  }
})();
