"use strict";

// ------------------------------------------------------------------ helpers
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

async function api(method, url, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  const type = response.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = (data && data.detail) || data || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

let toastTimer;
function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), isError ? 7000 : 3500);
}
const fail = (error) => toast(error.message || String(error), true);

function fmtBytes(n) {
  if (n === null || n === undefined) return "";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
}

function fmtDuration(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  const hh = Math.floor(seconds / 3600), mm = Math.floor(seconds % 3600 / 60), ss = seconds % 60;
  return (hh ? `${hh}h ` : "") + `${mm}m ${String(ss).padStart(2, "0")}s`;
}

const store = {
  get(key, fallback) { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } },
};

// ------------------------------------------------------------------ state
let INFO = {};
let SETTINGS = {};
let TOMLS = [];
let GAMES = [];
const selected = new Set();
let outputIds = 0;

// ------------------------------------------------------------------ tabs
function showTab(name) {
  $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  store.set("tab", name);
  if (name === "tomls") loadTomls();
  if (name === "jobs") refreshJobs();
}
$("#nav").addEventListener("click", (e) => {
  const button = e.target.closest("button[data-tab]");
  if (button) showTab(button.dataset.tab);
});

// ------------------------------------------------------------------ folder picker
const picker = { dialog: $("#picker"), target: null, current: null };

async function pickerLoad(path, keep = null) {
  try {
    let data;
    try {
      data = await api("GET", "/api/browse" + (path ? `?path=${encodeURIComponent(path)}` : ""));
    } catch (error) {
      // A folder that does not exist yet (e.g. a new output folder): show its nearest
      // existing parent but keep the requested path in the field so it can be selected.
      const parent = path && path.replace(/\/+$/, "").replace(/\/[^/]*$/, "");
      if (keep !== null && path && parent !== path) return pickerLoad(parent, keep || path);
      throw error;
    }
    picker.current = data.path;
    $("#picker-path").value = keep || data.path || "";
    $("#picker-select").disabled = !(keep || data.path);
    $("#picker-disk").textContent = data.disk ? `${fmtBytes(data.disk.free)} free of ${fmtBytes(data.disk.total)}` : "";
    const list = $("#picker-list");
    list.replaceChildren();
    if (data.path) {
      list.append(h("div", { class: "picker-item", onclick: () => pickerLoad(data.parent || "") }, "⬆ ..",));
    }
    for (const entry of data.entries) {
      list.append(h("div", { class: "picker-item", onclick: () => pickerLoad(entry.path) },
        "📁 ", entry.name,
        entry.is_packed ? h("span", { class: "tag ok" }, "AMPR packed") : entry.is_game ? h("span", { class: "tag" }, "PS5 game") : null));
    }
    if (!data.entries.length) list.append(h("div", { class: "empty" }, data.path ? "No subfolders" : "No folders are mounted. Check the container paths."));
  } catch (error) { fail(error); }
}

function openPicker(targetId) {
  picker.target = $("#" + targetId);
  picker.dialog.showModal();
  pickerLoad(picker.target.value.trim(), "");
}
document.addEventListener("click", (e) => {
  const button = e.target.closest("[data-pick]");
  if (button) { e.preventDefault(); openPicker(button.dataset.pick); }
  const close = e.target.closest("[data-close]");
  if (close) close.closest("dialog").close();
});
$("#picker-go").addEventListener("click", () => pickerLoad($("#picker-path").value.trim()));
$("#picker-path").addEventListener("keydown", (e) => { if (e.key === "Enter") pickerLoad(e.target.value.trim()); });
$("#picker-select").addEventListener("click", () => {
  const chosen = $("#picker-path").value.trim() || picker.current;
  if (!chosen) return;
  picker.target.value = chosen;
  picker.target.dispatchEvent(new Event("change"));
  picker.dialog.close();
});

// ------------------------------------------------------------------ games
async function scanGames() {
  const path = $("#games-path").value.trim();
  if (!path) return;
  store.set("gamesPath", path);
  $("#games-scan").disabled = true;
  try {
    const data = await api("GET", `/api/games?path=${encodeURIComponent(path)}`);
    GAMES = data.games;
    selected.clear();
    renderGames();
  } catch (error) { fail(error); } finally { $("#games-scan").disabled = false; }
}

function tomlSelect(game) {
  const select = h("select", {},
    h("option", { value: "__auto__" }, "Auto (match / traces / scan)"),
    h("option", { value: "__none__" }, "None — always scan"),
    TOMLS.map((t) => h("option", { value: t.name }, t.name)));
  if (game.toml_source === "manual") select.value = game.toml || "__none__";
  else select.value = "__auto__";
  select.addEventListener("change", async () => {
    try {
      let updated;
      if (select.value === "__auto__") updated = await api("POST", "/api/games/auto-link", { path: game.path });
      else updated = await api("POST", "/api/games/link", { path: game.path, toml: select.value === "__none__" ? null : select.value });
      Object.assign(game, updated);
      renderGames();
    } catch (error) { fail(error); }
  });
  return select;
}

function gameCard(game) {
  const initials = (game.title || "?").slice(0, 2).toUpperCase();
  const icon = game.has_icon
    ? h("img", { class: "game-icon", src: `/api/icon?path=${encodeURIComponent(game.path)}`, alt: "" })
    : h("div", { class: "game-icon" }, initials);
  const checkbox = h("input", { type: "checkbox", checked: selected.has(game.path) });
  checkbox.addEventListener("change", () => {
    checkbox.checked ? selected.add(game.path) : selected.delete(game.path);
    updateSelection();
  });
  const output = h("input", { type: "text", value: game.default_output, spellcheck: "false", id: `out-${++outputIds}` });
  output.addEventListener("change", () => { game.custom_output = output.value.trim(); });
  if (game.custom_output) output.value = game.custom_output;

  const tags = [
    h("span", { class: "tag" }, game.title_id),
    h("span", { class: "tag" }, `v${game.version}`),
    game.toml ? h("span", { class: "tag ok", title: "Linked TOML profile" }, `TOML: ${game.toml}`) : null,
    !game.toml && game.traces ? h("span", { class: "tag ok" }, "traces found") : null,
    !game.toml && !game.traces ? h("span", { class: "tag warn", title: "No TOML or traces: the profile is generated by scanning the folder (less reliable)" }, "no profile") : null,
    game.is_packed ? h("span", { class: "tag warn" }, "already packed") : null,
    game.output_exists ? h("span", { class: "tag warn", title: "The output folder already exists" }, "output exists") : null,
  ];

  return h("div", { class: "game" + (selected.has(game.path) ? " selected" : "") },
    h("div", { class: "game-head" }, icon,
      h("div", {}, h("div", { class: "game-title" }, game.title), h("div", { class: "game-meta" }, game.path)),
      h("label", { class: "check", title: "Select for batch" }, checkbox)),
    h("div", { class: "tags" }, tags),
    h("div", {}, h("div", { class: "label" }, "TOML profile"), tomlSelect(game)),
    h("div", {}, h("div", { class: "label" }, "Output folder"),
      h("div", { class: "row" }, output, h("button", { class: "secondary small", "data-pick": output.id, type: "button" }, "…"))),
    h("div", { class: "game-actions" },
      h("button", { onclick: () => packGames([game]) }, "Pack"),
      game.traces ? h("button", { class: "secondary", onclick: () => generateProfile(game) }, "TOML from traces") : null,
      game.is_packed ? h("button", { class: "secondary", onclick: () => { $("#extract-source").value = game.path; showTab("extract"); } }, "Extract…") : null));
}

function renderGames() {
  const grid = $("#games-grid");
  grid.replaceChildren(...GAMES.map(gameCard));
  $("#games-empty").classList.toggle("hidden", GAMES.length > 0);
  $("#games-toolbar").classList.toggle("hidden", GAMES.length === 0);
  updateSelection();
}

function updateSelection() {
  $("#games-pack-selected").textContent = `Pack selected (${selected.size})`;
  $("#games-pack-selected").disabled = selected.size === 0;
  $("#games-select-all").checked = GAMES.length > 0 && selected.size === GAMES.length;
  $$("#games-grid .game").forEach((card, i) => card.classList.toggle("selected", selected.has(GAMES[i].path)));
}

async function packGames(list) {
  const level = Number($("#games-level").value);
  const skipVerify = $("#games-skip-verify").checked;
  let queued = 0;
  for (const game of list) {
    try {
      await api("POST", "/api/jobs/pack", {
        path: game.path,
        output: game.custom_output || game.default_output,
        lz4_level: level,
        skip_verify: skipVerify,
      });
      queued++;
    } catch (error) { toast(`${game.title}: ${error.message}`, true); }
  }
  if (queued) { toast(`${queued} job(s) queued`); refreshJobs(); }
}

async function generateProfile(game) {
  try {
    await api("POST", "/api/jobs/profile", { path: game.path, traces: game.traces });
    toast("TOML generation queued — see Jobs");
    refreshJobs();
  } catch (error) { fail(error); }
}

$("#games-scan").addEventListener("click", scanGames);
$("#games-path").addEventListener("change", scanGames);
$("#games-select-all").addEventListener("change", (e) => {
  selected.clear();
  if (e.target.checked) GAMES.forEach((g) => selected.add(g.path));
  updateSelection();
  $$("#games-grid .game input[type=checkbox]").forEach((c) => { c.checked = e.target.checked; });
});
$("#games-level").addEventListener("input", (e) => { $("#games-level-value").textContent = e.target.value; });
$("#games-pack-selected").addEventListener("click", () => packGames(GAMES.filter((g) => selected.has(g.path))));

// ------------------------------------------------------------------ extract
$("#extract-start").addEventListener("click", async () => {
  try {
    await api("POST", "/api/jobs/extract", {
      path: $("#extract-source").value.trim(),
      output: $("#extract-output").value.trim() || null,
    });
    toast("Extraction queued");
    showTab("jobs");
  } catch (error) { fail(error); }
});

// ------------------------------------------------------------------ jobs
const jobViews = new Map(); // id -> {el, cursor, open}

function jobView(job) {
  let view = jobViews.get(job.id);
  if (!view) {
    const log = h("pre", { class: "log hidden" });
    const toggle = h("button", { class: "secondary small" }, "Show log");
    const cancel = h("button", { class: "danger small" }, "Cancel");
    const remove = h("button", { class: "secondary small" }, "Remove");
    const el = h("div", { class: "job" },
      h("div", { class: "job-head" },
        h("span", { class: "job-kind" }, job.kind),
        h("span", { class: "job-title" }, job.title),
        h("span", { class: "state" }),
        h("span", { class: "spacer" }),
        toggle, cancel, remove),
      h("div", { class: "progress" }, h("div", { style: "width:0%" })),
      h("div", { class: "job-status" }),
      log);
    view = { el, log, cursor: 0, open: false, toggle, cancel, remove };
    toggle.addEventListener("click", () => {
      view.open = !view.open;
      log.classList.toggle("hidden", !view.open);
      toggle.textContent = view.open ? "Hide log" : "Show log";
      if (view.open) pollLog(job.id);
    });
    cancel.addEventListener("click", () => api("POST", `/api/jobs/${job.id}/cancel`).then(refreshJobs, fail));
    remove.addEventListener("click", () => api("DELETE", `/api/jobs/${job.id}`).then(refreshJobs, fail));
    jobViews.set(job.id, view);
  }
  const active = job.state === "queued" || job.state === "running";
  view.el.className = `job ${job.state}`;
  $(".state", view.el).className = `state ${job.state}`;
  $(".state", view.el).textContent = job.state;
  $(".progress > div", view.el).style.width = `${job.progress}%`;
  const elapsed = job.started ? ((job.finished || Date.now() / 1000) - job.started) : 0;
  const parts = [
    `${job.progress}%`,
    job.state === "failed" ? job.message.split("\n").slice(-2).join(" ") : job.status,
    job.eta,
    elapsed ? `⏱ ${fmtDuration(elapsed)}` : "",
    job.params.output ? `→ ${job.params.output}` : "",
    job.params.toml ? `TOML: ${job.params.toml}` : "",
  ].filter(Boolean);
  $(".job-status", view.el).replaceChildren(...parts.map((p) => h("span", {}, p)));
  view.cancel.classList.toggle("hidden", !active);
  view.remove.classList.toggle("hidden", active);
  return view;
}

async function pollLog(id) {
  const view = jobViews.get(id);
  if (!view || !view.open) return;
  try {
    const data = await api("GET", `/api/jobs/${id}?since=${view.cursor}`);
    if (data.log.length) {
      const stick = view.log.scrollTop + view.log.clientHeight >= view.log.scrollHeight - 20;
      view.log.append(data.log.join("\n") + "\n");
      view.cursor = data.cursor;
      if (stick) view.log.scrollTop = view.log.scrollHeight;
    }
  } catch { /* job removed */ }
}

async function refreshJobs() {
  try {
    const data = await api("GET", "/api/jobs");
    const list = $("#jobs-list");
    const seen = new Set();
    data.jobs.forEach((job, index) => {
      const view = jobView(job);
      seen.add(job.id);
      if (list.children[index] !== view.el) list.insertBefore(view.el, list.children[index] || null);
      if (view.open) pollLog(job.id);
    });
    for (const [id, view] of jobViews) {
      if (!seen.has(id)) { view.el.remove(); jobViews.delete(id); }
    }
    $("#jobs-empty").classList.toggle("hidden", data.jobs.length > 0);
    const active = data.jobs.filter((j) => j.state === "queued" || j.state === "running").length;
    $("#jobs-badge").textContent = active;
    $("#jobs-badge").classList.toggle("hidden", active === 0);
  } catch { /* server restarting */ }
}
$("#jobs-clear").addEventListener("click", () => api("DELETE", "/api/jobs").then(refreshJobs, fail));
setInterval(refreshJobs, 1500);

// ------------------------------------------------------------------ TOML profiles
async function loadTomls() {
  try {
    const data = await api("GET", "/api/tomls");
    TOMLS = data.tomls;
    $("#toml-dir").textContent = data.dir;
    const list = $("#toml-list");
    list.replaceChildren(...TOMLS.map((t) => h("div", { class: "toml-row" },
      h("span", { class: "name" }, t.name),
      h("span", { class: "muted" }, fmtBytes(t.size)),
      t.games.length ? h("span", { class: "tag ok" }, `used by: ${t.games.join(", ")}`) : null,
      h("span", { class: "spacer" }),
      h("button", { class: "secondary small", onclick: () => openEditor(t.name) }, "View / edit"),
      h("a", { class: "button secondary small", href: `/api/tomls/${encodeURIComponent(t.name)}`, download: t.name }, "Download"),
      h("button", { class: "danger small", onclick: () => deleteToml(t.name) }, "Delete"))));
    if (!TOMLS.length) list.append(h("div", { class: "empty" }, "No TOML profiles yet."));
    if (GAMES.length) renderGames();
  } catch (error) { fail(error); }
}

async function deleteToml(name) {
  if (!confirm(`Delete ${name}?`)) return;
  try { await api("DELETE", `/api/tomls/${encodeURIComponent(name)}`); loadTomls(); } catch (error) { fail(error); }
}

async function openEditor(name) {
  $("#editor-error").textContent = "";
  $("#editor-name").value = name || "";
  $("#editor-name").dataset.original = name || "";
  $("#editor-text").value = "";
  $("#editor").showModal();
  if (name) {
    try { $("#editor-text").value = await api("GET", `/api/tomls/${encodeURIComponent(name)}`); } catch (error) { fail(error); }
  }
}

$("#editor-save").addEventListener("click", async () => {
  let name = $("#editor-name").value.trim();
  if (name && !name.toLowerCase().endsWith(".toml")) name += ".toml";
  if (!name) { $("#editor-error").textContent = "Enter a file name"; return; }
  const original = $("#editor-name").dataset.original;
  const exists = TOMLS.some((t) => t.name === name);
  if (exists && name !== original && !confirm(`${name} already exists. Overwrite?`)) return;
  try {
    await api("PUT", `/api/tomls/${encodeURIComponent(name)}`, { content: $("#editor-text").value, overwrite: true });
    $("#editor").close();
    toast(`Saved ${name}`);
    loadTomls();
  } catch (error) { $("#editor-error").textContent = error.message; }
});
$("#toml-new").addEventListener("click", () => openEditor(null));

$("#toml-upload").addEventListener("change", async (e) => {
  for (const file of e.target.files) {
    try {
      const content = await file.text();
      await api("PUT", `/api/tomls/${encodeURIComponent(file.name)}`, { content, overwrite: true });
      toast(`Imported ${file.name}`);
    } catch (error) { toast(`${file.name}: ${error.message}`, true); }
  }
  e.target.value = "";
  loadTomls();
});

$("#toml-fetch").addEventListener("click", async () => {
  const box = $("#toml-remote");
  box.replaceChildren(h("div", { class: "muted" }, "Fetching…"));
  try {
    const data = await api("POST", "/api/tomls/remote/list", { url: $("#toml-url").value.trim() });
    box.replaceChildren(...data.tomls.map((t) => {
      const button = h("button", { class: "small" + (t.exists ? " secondary" : "") }, t.exists ? "Re-download" : "Download");
      button.addEventListener("click", async () => {
        button.disabled = true;
        try { await api("POST", "/api/tomls/remote/download", t); button.textContent = "✓"; loadTomls(); } catch (error) { fail(error); button.disabled = false; }
      });
      return h("div", { class: "toml-row" }, h("span", { class: "name" }, t.name), h("span", { class: "spacer" }), button);
    }));
    if (!data.tomls.length) box.replaceChildren(h("div", { class: "muted" }, "No .toml files found at that URL."));
  } catch (error) { box.replaceChildren(); fail(error); }
});

// ------------------------------------------------------------------ settings
function fillSettings() {
  const form = $("#settings-form");
  for (const [key, value] of Object.entries(SETTINGS)) {
    const field = form.elements[key];
    if (!field) continue;
    if (field.type === "checkbox") field.checked = !!value;
    else field.value = value ?? "";
  }
  $("#s-lz4_level-value").textContent = SETTINGS.lz4_level;
  $("#games-level").value = SETTINGS.lz4_level;
  $("#games-level-value").textContent = SETTINGS.lz4_level;
  $("#games-skip-verify").checked = !!SETTINGS.skip_lz4_verification;
}

$("#s-lz4_level").addEventListener("input", (e) => { $("#s-lz4_level-value").textContent = e.target.value; });
$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const body = {
    output_dir: form.elements.output_dir.value.trim(),
    lz4_level: Number(form.elements.lz4_level.value),
    block_size_kib: Number(form.elements.block_size_kib.value),
    workers: form.elements.workers.value ? Number(form.elements.workers.value) : null,
    decoded_cache_mib: Number(form.elements.decoded_cache_mib.value),
    physical_cache_mib: Number(form.elements.physical_cache_mib.value),
    skip_lz4_verification: form.elements.skip_lz4_verification.checked,
    auto_loose_large: form.elements.auto_loose_large.checked,
    use_hardlinks: form.elements.use_hardlinks.checked,
  };
  try {
    SETTINGS = await api("PUT", "/api/settings", body);
    fillSettings();
    $("#settings-saved").classList.remove("hidden");
    setTimeout(() => $("#settings-saved").classList.add("hidden"), 2500);
  } catch (error) { fail(error); }
});

// ------------------------------------------------------------------ boot
(async function boot() {
  try {
    [INFO, SETTINGS] = await Promise.all([api("GET", "/api/info"), api("GET", "/api/settings")]);
    $("#version").textContent = `v${INFO.version}`;
    $("#s-workers").placeholder = `auto (${Math.max(1, (INFO.cpu_count || 2) - 1)})`;
    fillSettings();
    await loadTomls();
    const firstRoot = (INFO.roots.find((r) => r.exists) || {}).path || "";
    $("#games-path").value = store.get("gamesPath", firstRoot);
    if ($("#games-path").value) scanGames();
  } catch (error) { fail(error); }
  refreshJobs();
  showTab(store.get("tab", "games"));
})();
