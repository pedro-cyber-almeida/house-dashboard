// Admin panel: manage the services catalogue and per-user permissions.
import { api, upload } from "./api.js";

const ROLES = ["admin", "user"];

// Heuristic category guesses by service-name keyword (first match wins).
// Purely a convenience for the form — the admin can type anything else.
const CATEGORY_HINTS = [
  ["Media", /\b(radarr|sonarr|bazarr|lidarr|prowlarr|plexarr|jellyfin|jellyseerr|plex|emby|qbittorrent|deluge|transmission|mediamtx)\b/i],
  ["Home automation", /\b(home\s?-?assistant|zigbee|zha|esphome|shelly|tado|thermostat)\b/i],
  ["Network", /\b(pihole|adguard|unifi|pf\s?-?sense|opnsense|mikrotik|tailscale|wireguard|speedtest|netdata)\b/i],
  ["AI", /\b(ollama|open\s?-?webui|whisper|stable\s?-?diffusion|comfyui|comfy|-?llama|vllm)\b/i],
  ["Security", /\b(vaultwarden|bitwarden|authentik|keycloak|2fas|fail2ban|crowdsec)\b/i],
  ["Files & cloud", /\b(nextcloud|pydio|seafile|filebrowser|megadrive)\b/i],
  ["Devops", /\b(gitea|gitlab|gogs?|jenkins|argocd|grafana|prometheus|portainer|watchtower|traefik)\b/i],
  ["Chat", /\b(mattermost|matrix|synapse|zulip|redlib)\b/i],
  ["Finance", /\b(fynbos|firefly|ghostfolio)\b/i],
];

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
  document.getElementById("toasts").append(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 250);
  }, 3400);
}

function field(labelText, input) {
  return h("label", { class: "field" }, h("span", {}, labelText), input);
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

export async function mountAdmin(root) {
  root.innerHTML = "";
  const back = h(
    "button",
    { class: "linknav", type: "button", title: "Back to the dashboard", onclick: () => { location.hash = ""; } },
    "← Dashboard",
  );
  root.append(h("div", { class: "page-head" }, h("p", { class: "page-title" }, "Admin · services & users"), back));
  const grid = h("div", { class: "admin-grid" });
  grid.append(buildServices());
  grid.append(buildUsers());
  root.append(grid);
}

// ---------------- services ----------------
const MAX_LOGO_BYTES = 512 * 1024;
const LOGO_TYPES = ["image/png", "image/jpeg", "image/svg+xml"];

function buildServices() {
  const listEl = h("ul", { class: "admin-list" });
  let services = [];
  let editingId = null;
  let editingIcon = null; // current logo of the service being edited
  let clearIcon = false;

  const nameIn = h("input", { required: true, placeholder: "e.g.: Sonarr" });
  const url = h("input", { required: true, type: "url", placeholder: "https://…" });
  const descIn = h("input", { placeholder: "optional" });
  const catIn = h("input", { placeholder: "Media, Downloads…", list: "svc-categories" });
  const catList = h("datalist", { id: "svc-categories" });
  const logoFile = h("input", { type: "file", accept: "image/png,image/jpeg,image/svg+xml" });
  const iconPreview = h("span", { class: "icon-preview" });
  const clearIconBtn = h("button", { class: "btn ghost", type: "button" }, "Remove");
  const submitBtn = h("button", { class: "btn primary", type: "submit" }, "Add service");
  let pendingFile = null;
  let pendingPreview = null;

  // Auto-suggest a category from the service name while the category field
  // is still untouched (new-service form only; manual input always wins).
  let catTouched = false;
  let catAuto = null;
  const suggestCategory = (name) => {
    const n = (name || "").trim();
    if (!n) return null;
    for (const [category, pattern] of CATEGORY_HINTS) if (pattern.test(n)) return category;
    return null;
  };
  const applyCategorySuggestion = () => {
    if (editingId || catTouched) return;
    const suggestion = suggestCategory(nameIn.value);
    if (suggestion !== catAuto) {
      catAuto = suggestion;
      if (suggestion) catIn.value = suggestion;
    }
  };
  nameIn.addEventListener("input", applyCategorySuggestion);
  catIn.addEventListener("input", () => {
    catTouched = true;
  });

  const showIconPreview = () => iconPreview.replaceChildren(
    iconTile("tile sm", pendingPreview || editingIcon, nameIn.value.trim() || "?"),
  );
  logoFile.addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file) return;
    if (!LOGO_TYPES.includes(file.type)) {
      toast("Unsupported format — use PNG, JPEG or SVG.", "err");
      return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      toast("Logo too large (max. 512 KB).", "err");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      pendingFile = file;
      pendingPreview = reader.result;
      clearIcon = false;
      showIconPreview();
    };
    reader.onerror = () => toast("Could not read the file.", "err");
    reader.readAsDataURL(file);
  });
  clearIconBtn.addEventListener("click", () => {
    pendingFile = null;
    pendingPreview = null;
    clearIcon = true;
    showIconPreview();
  });

  const fetchIcon = async (s, btn) => {
    if (btn.disabled) return;
    btn.disabled = true;
    try {
      const updated = await api(`/api/services/${s.id}/fetch-icon`, { method: "POST" });
      s.icon = updated.icon;
      toast(`Icon fetched for "${s.name}".`);
      load();
    } catch (err) {
      toast(err.message, "err");
    }
  };

  function render() {
    listEl.replaceChildren(
      ...services.map((s) =>
        h(
          "li",
          { class: "admin-row" },
          iconTile("tile sm", s.icon, s.name),
          h(
            "div",
            { class: "admin-row-main" },
            h("div", { class: "admin-row-title" }, s.name, s.category ? h("span", { class: "cat-tag" }, s.category) : null),
            h("div", { class: "muted small" }, s.url),
          ),
          h(
            "div",
            { class: "row-actions" },
            h("button", { class: "btn ghost", type: "button", title: "Fetch the favicon from the service itself", onclick: (e) => fetchIcon(s, e.currentTarget) }, "Fetch icon"),
            h("button", { class: "btn ghost", type: "button", onclick: () => edit(s) }, "Edit"),
            h("button", { class: "btn ghost danger", type: "button", onclick: () => del(s) }, "Remove"),
          ),
        ),
      ),
    );
  }

  function syncCategoryList() {
    const cats = [...new Set(services.map((s) => (s.category || "").trim()).filter(Boolean))].sort((a, b) =>
      a.localeCompare(b, undefined, { sensitivity: "base" }),
    );
    catList.replaceChildren(...cats.map((c) => h("option", { value: c })));
  }

  async function load() {
    try {
      services = await api("/api/admin/services");
      syncCategoryList();
      render();
    } catch (err) {
      toast(err.message, "err");
    }
  }

  function edit(s) {
    editingId = s.id;
    editingIcon = s.icon;
    pendingFile = null;
    pendingPreview = null;
    clearIcon = false;
    catTouched = true;
    catAuto = null;
    nameIn.value = s.name;
    url.value = s.url;
    descIn.value = s.description || "";
    catIn.value = s.category || "";
    showIconPreview();
    submitBtn.textContent = "Save changes";
    nameIn.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function resetForm() {
    editingId = null;
    editingIcon = null;
    pendingFile = null;
    pendingPreview = null;
    clearIcon = false;
    catTouched = false;
    catAuto = null;
    nameIn.value = "";
    url.value = "";
    descIn.value = "";
    catIn.value = "";
    showIconPreview();
    submitBtn.textContent = "Add service";
  }

  async function del(s) {
    if (!confirm(`Remove "${s.name}" from the services list?`)) return;
    try {
      await api(`/api/admin/services/${s.id}`, { method: "DELETE" });
      toast(`Service "${s.name}" removed.`);
      load();
    } catch (err) {
      toast(err.message, "err");
    }
  }

  const form = h(
    "form",
    {
      onsubmit: async (e) => {
        e.preventDefault();
        const payload = {
          name: nameIn.value.trim(),
          url: url.value.trim(),
          description: descIn.value.trim() || null,
          category: catIn.value.trim() || null,
        };
        const hadFile = !!pendingFile;
        try {
          if (editingId) {
            if (clearIcon && !pendingFile) payload.icon = null;
            await api(`/api/admin/services/${editingId}`, { method: "PATCH", body: payload });
            if (hadFile) await upload(`/api/services/${editingId}/logo`, pendingFile);
          } else {
            const created = await api("/api/admin/services", { method: "POST", body: payload });
            if (hadFile) await upload(`/api/services/${created.id}/logo`, pendingFile);
          }
          toast(hadFile ? "Service saved with logo." : "Service saved.");
          resetForm();
          load();
        } catch (err) {
          toast(err.message, "err");
        }
      },
    },
    h("div", { class: "form-grid" }, field("Name", nameIn), field("URL", url)),
    h("div", { class: "form-grid" }, field("Description", descIn), field("Category (optional)", catIn)),
    catList,
    h(
      "div",
      { class: "field" },
      h("span", {}, "Logo · PNG, JPEG or SVG, up to 512 KB (optional)"),
      h(
        "div",
        { class: "row-actions" },
        h("label", { class: "btn" }, "Choose image", logoFile),
        clearIconBtn,
        iconPreview,
      ),
    ),
    submitBtn,
  );

  load();
  return h(
    "section",
    { class: "panel" },
    h("h2", {}, "Services"),
    h("p", { class: "sub" }, "Global catalogue. Each user only sees the services assigned to their account. A suggested category is auto-filled from the name — override it freely."),
    form,
    listEl,
  );
}

// ---------------- users ----------------
function buildUsers() {
  const listEl = h("ul", { class: "admin-list" });
  let users = [];
  let services = [];

  const username = h("input", { required: true, placeholder: "admin" });
  const password = h("input", { type: "password", required: true, autocomplete: "new-password", minlength: 8 });
  const display = h("input", { placeholder: "display name (optional)" });
  const roleSel = h("select", {}, ...ROLES.map((r) => h("option", { value: r }, r)));
  const activeChk = h("label", { class: "switch" }, h("input", { type: "checkbox", checked: true }), "active");

  async function loadServices() {
    services = await api("/api/admin/services");
  }

  async function loadUsers() {
    users = await api("/api/admin/users");
    render();
  }

  function assignControls(userId, currentIds) {
    const box = h("div", { class: "assign-list" });
    const boxes = {};
    services.forEach((s) => {
      const id = s.id;
      const cb = h("input", { type: "checkbox", id: `svc-${userId}-${id}`, checked: currentIds.includes(id) });
      boxes[id] = cb;
      box.append(h("label", { for: `svc-${userId}-${id}` }, cb, s.name));
    });
    const selected = () => services.filter((s) => boxes[s.id].checked).map((s) => s.id);
    const save = h(
      "button",
      {
        class: "btn primary",
        type: "button",
        onclick: async () => {
          try {
            await api(`/api/admin/users/${userId}/services`, { method: "PUT", body: { service_ids: selected() } });
            toast("Services updated.");
          } catch (err) {
            toast(err.message, "err");
          }
        },
      },
      "Save assignment",
    );
    return h("div", { class: "assign-save" }, box, save);
  }

  async function updateUser(userId, body, method) {
    try {
      await api(`/api/admin/users/${userId}`, { method, body });
      toast("User updated.");
      loadUsers();
    } catch (err) {
      toast(err.message, "err");
    }
  }

  async function delUser(u) {
    if (!confirm(`Delete the user "${u.username}"?`)) return;
    try {
      await api(`/api/admin/users/${u.id}`, { method: "DELETE" });
      toast("User deleted.");
      loadUsers();
    } catch (err) {
      toast(err.message, "err");
    }
  }

  function render() {
    listEl.replaceChildren(
      ...users.map((u) => {
        const role = h(
          "select",
          {
            value: u.role,
            onchange: async (e) => updateUser(u.id, { role: e.target.value }, "POST"),
          },
          ...ROLES.map((r) => h("option", { value: r, selected: r === u.role ? "selected" : null }, r)),
        );
        const atv = h(
          "input",
          {
            type: "checkbox",
            checked: u.active,
            onchange: (e) => updateUser(u.id, { active: e.target.checked }, "PATCH"),
          },
        );
        const detail = h(
          "details",
          { class: "row-detail" },
          h("summary", { class: "linknav" }, `Services (${u.service_ids.length})`),
          assignControls(u.id, u.service_ids),
        );
        return h(
          "li",
          { class: "admin-row" },
          iconTile("tile sm", u.avatar, u.display_name || u.username),
          h(
            "div",
            { class: "admin-row-main" },
            h("div", {}, u.display_name || u.username),
            h("div", { class: "muted small" }, u.username),
          ),
          role,
          h("label", { class: "switch", title: "active" }, atv),
          detail,
          h("button", { class: "btn ghost danger", type: "button", onclick: () => delUser(u) }, "Delete"),
        );
      }),
    );
  }

  const form = h(
    "form",
    {
      onsubmit: async (e) => {
        e.preventDefault();
        const role = ROLES.find((r) => r === roleSel.value) || "user";
        try {
          await api("/api/admin/users", {
            method: "POST",
            body: {
              username: username.value.trim(),
              password: password.value,
              display_name: display.value.trim(),
              role,
              active: activeChk.querySelector("input").checked,
            },
          });
          username.value = "";
          password.value = "";
          display.value = "";
          toast("User created.");
          loadUsers();
        } catch (err) {
          toast(err.message, "err");
        }
      },
    },
    h("div", { class: "form-grid" }, field("Username", username), field("Password (initial)", password)),
    field("Display name", display),
    h("div", { class: "form-grid" }, field("Role", roleSel), activeChk),
    h("button", { class: "btn primary", type: "submit" }, "Create user"),
  );

  (async () => {
    try {
      await loadServices();
      await loadUsers();
    } catch (err) {
      toast(err.message, "err");
    }
  })();

  return h(
    "section",
    { class: "panel" },
      h("h2", {}, "Users"),
      h("p", { class: "sub" }, "Create accounts, set roles and assign the services each user sees."),
    form,
    listEl,
  );
}
