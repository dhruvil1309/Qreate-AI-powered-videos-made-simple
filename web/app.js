/* ==========================================================================
   Qreate studio — no build step, no framework.
   Live job state arrives over Server-Sent Events, so progress is pushed
   rather than polled. Scene edits live in a local draft map, which is why a
   push mid-typing never clobbers what you are writing.
   ========================================================================== */
"use strict";

/* ------------------------------------------------------------------ helpers */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** Build an element. Strings/nodes become children; `false`/`null` are skipped. */
const el = (tag, props = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null) continue;
    if (k === "dataset") Object.assign(e.dataset, v);
    else if (k in e) e[k] = v;
    else e.setAttribute(k, v);
  }
  kids.flat(Infinity).forEach((k) => {
    if (k === null || k === undefined || k === false) return;
    e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  });
  return e;
};

/** Inline SVG icon. Paths are drawn on a 24x24 grid with a 2px stroke. */
const icon = (d, { fill = "none" } = {}) => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", fill);
  svg.setAttribute("stroke", fill === "none" ? "currentColor" : "none");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = d.map((p) => `<path d="${p}"/>`).join("");
  return svg;
};

const ICONS = {
  sun: ["M12 4v2M12 18v2M4 12H2M22 12h-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M6.3 17.7 4.9 19.1M19.1 4.9l-1.4 1.4", "M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z"],
  moon: ["M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"],
  play: ["M8 5.5v13l11-6.5-11-6.5Z"],
  download: ["M12 4v11M7.5 11 12 15.5 16.5 11M5 19.5h14"],
  copy: ["M9 9h10v11H9zM15 5H5v10"],
  pkg: ["M12 3 3.5 7.5v9L12 21l8.5-4.5v-9L12 3ZM3.5 7.5 12 12l8.5-4.5M12 12v9"],
  trash: ["M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"],
  retry: ["M20 11a8 8 0 1 0-2.5 5.8M20 5v6h-6"],
  shuffle: ["M4 7h4l9 10h3M17 7h3M20 7l-2.5-2.5M20 17l-2.5 2.5M4 17h4l2-2.3"],
  external: ["M14 5h5v5M19 5l-8 8M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-10A1.5 1.5 0 0 1 5 18.5v-10A1.5 1.5 0 0 1 6.5 7H11"],
  warn: ["M12 4.5 2.8 20h18.4L12 4.5ZM12 10v4.5M12 17.2v.3"],
  save: ["M5 5h11l3 3v11H5zM9 5v5h6V5M8.5 19v-5h7v5"],
};

const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : d?.[0]?.msg || `Request failed (${r.status})`);
  }
  return data;
};

const toast = (msg, kind = "", action) => {
  const node = el("div", { className: `toast ${kind}` }, el("span", { textContent: msg }));
  if (action) {
    node.append(el("button", {
      textContent: action.label,
      onclick: () => { node.remove(); action.run(); },
    }));
  }
  $("#toasts").append(node);
  setTimeout(() => node.remove(), action ? 7000 : 3200);
};

const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;

const ago = (ts) => {
  const s = Math.max(0, (Date.now() - ts * 1000) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};

const secs = (n) => (n >= 60 ? `${Math.floor(n / 60)}m ${Math.round(n % 60)}s` : `${n.toFixed(1)}s`);

/** How long a stage took, blank when it was too fast to be worth showing. */
const took = (st) => {
  const t = st.started && st.ended ? st.ended - st.started : 0;
  return t >= 0.1 ? secs(t) : "";
};

const STATUS_TEXT = {
  queued: "Queued", running: "Making the video", done: "Ready to post",
  needs_review: "Ready — check the warnings", failed: "Failed",
};
const BUSY = (s) => s === "queued" || s === "running";

/* ------------------------------------------------------------------ state */
const state = {
  mode: "one",
  currentId: null,
  job: null,
  tab: "script",
  jobs: [],
  stats: null,
  filter: "all",
  query: "",
  /** jobId -> sceneIndex -> {caption, voiceover, visual} the user has typed but not saved. */
  drafts: new Map(),
  /** jobId -> {title, description, hashtags} typed in the Post tab. */
  postDrafts: new Map(),
  activeShot: 0,
  options: { language: "english", visual_style: "mix", target_seconds: 45 },
};

const draftFor = (idx) => {
  const perJob = state.drafts.get(state.currentId) || new Map();
  state.drafts.set(state.currentId, perJob);
  return perJob.get(idx);
};
const setDraft = (idx, patch) => {
  const perJob = state.drafts.get(state.currentId) || new Map();
  perJob.set(idx, { ...(perJob.get(idx) || {}), ...patch });
  state.drafts.set(state.currentId, perJob);
};
const clearDraft = (idx) => state.drafts.get(state.currentId)?.delete(idx);

/* ------------------------------------------------------------------ theme */
const paintThemeBtn = () => {
  const dark = document.documentElement.dataset.theme === "dark";
  const btn = $("#themeBtn");
  btn.textContent = "";
  btn.append(icon(dark ? ICONS.sun : ICONS.moon));
  btn.title = dark ? "Switch to light theme" : "Switch to dark theme";
};
$("#themeBtn").onclick = () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("qreate-theme", next); } catch { /* private mode */ }
  paintThemeBtn();
};
paintThemeBtn();

/* ------------------------------------------------------------------ composer */
$$(".seg[data-name]").forEach((seg) =>
  seg.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    const v = b.dataset.v;
    state.options[seg.dataset.name] = isNaN(+v) ? v : +v;
  })
);

const topicLines = () => $("#topic").value.split("\n").map((s) => s.trim()).filter(Boolean);

function updateGo() {
  const n = topicLines().length;
  $("#goLabel").textContent = state.mode === "one"
    ? "Make video"
    : n ? `Make ${plural(n, "video")}` : "Make videos";
  $("#topicHint").textContent = `${$("#topic").value.length}/600`;
}

function setMode(m) {
  state.mode = m;
  $("#modeOne").setAttribute("aria-pressed", String(m === "one"));
  $("#modeBatch").setAttribute("aria-pressed", String(m === "batch"));
  const topic = $("#topic");
  $("#topicLabel").textContent = m === "one" ? "What should the video be about?" : "Topics, one per line";
  topic.placeholder = m === "one"
    ? "Why ISRO missions cost so little"
    : "Why ISRO missions cost so little\nHow UPI changed payments in India\n5 study habits backed by science";
  topic.rows = m === "one" ? 3 : 5;
  updateGo();
}
$("#modeOne").onclick = () => setMode("one");
$("#modeBatch").onclick = () => setMode("batch");
$("#topic").addEventListener("input", updateGo);
updateGo();

async function submit() {
  const lines = topicLines();
  if (!lines.length) {
    $("#topic").focus();
    toast("Type a topic first.", "err");
    return;
  }
  const common = {
    community: $("#community").value.trim() || "General",
    tone: $("#tone").value,
    ...state.options,
  };
  const btn = $("#go");
  btn.disabled = true;
  try {
    if (state.mode === "one") {
      const r = await api("/api/jobs", { method: "POST", body: JSON.stringify({ topic: lines.join(" "), ...common }) });
      selectJob(r.id);
      toast("Video started", "ok");
    } else {
      const r = await api("/api/batch", { method: "POST", body: JSON.stringify({ topics: lines, ...common }) });
      selectJob(r.ids[0]);
      toast(`${plural(r.ids.length, "video")} queued`, "ok");
    }
  } catch (e) {
    toast(e.message, "err");
  } finally {
    btn.disabled = false;
  }
}
$("#go").onclick = submit;

/* keyboard: Ctrl/Cmd+Enter submits from anywhere, "/" jumps to the topic box */
const isMac = /Mac|iP(hone|ad)/.test(navigator.platform || navigator.userAgent);
$("#goKbd").textContent = isMac ? "⌘ ↵" : "Ctrl ↵";
document.addEventListener("keydown", (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); submit(); return; }
  if (e.key === "/" && !typing) { e.preventDefault(); $("#topic").focus(); return; }
  if (e.key === "Escape") $("#lightbox")?.remove();
});

/* ------------------------------------------------------------------ health + trends */
(async () => {
  const dot = $("#healthDot");
  const body = $("#enginesBody");
  try {
    const h = await api("/api/health");
    dot.className = "live-dot up";
    const providers = h.llm_providers.length ? h.llm_providers.join(", ") : "offline template";
    $("#enginesSummary").textContent = h.offline_mode
      ? "Offline mode — templates and generated cards"
      : `Engines: ${providers}`;

    const line = (label, value, hint) =>
      body.append(el("div", { className: "engine-line" },
        el("span", {}, label),
        el("span", {}, value, hint && el("em", {}, " — " + hint))));

    line("Script", providers, h.llm_providers.length ? null : "add GEMINI_API_KEY for AI scripts");
    line("Research", h.research.join(", "), h.research.includes("tavily") ? null : "add TAVILY_API_KEY for live search");
    line("Visuals", h.visuals.join(", "), h.visuals.includes("pexels") ? null : "add PEXELS_API_KEY for real footage");
    line("Voice", h.voice[0]);
    line("Critic", h.critic === "llm" ? "LLM judge" : "heuristic");
    line("Workers", `${h.workers} parallel`, h.ffmpeg ? null : "ffmpeg not found — renders will fail");
    if (h.wan2_1?.enabled) line("Wan 2.1", h.wan2_1.ready ? "ready" : "not ready", h.wan2_1.ready ? null : h.wan2_1.detail);
    if (!h.ffmpeg) toast("ffmpeg is not on PATH — videos cannot be rendered.", "err");
  } catch {
    dot.className = "live-dot down";
    $("#enginesSummary").textContent = "Can't reach the server";
    body.append(el("div", { className: "hint", style: "margin:0" },
      "Start it with: uvicorn app.main:app --reload"));
    $("#engines").open = true;
  }
})();

async function loadTrends() {
  const box = $("#trends");
  try {
    const { topics } = await api("/api/trends");
    box.textContent = "";
    topics.slice(0, 6).forEach((t) =>
      box.append(el("button", {
        className: "chip", textContent: t, title: t, type: "button",
        onclick: () => {
          const ta = $("#topic");
          ta.value = state.mode === "one" ? t : (ta.value ? ta.value + "\n" : "") + t;
          updateGo();
          ta.focus();
        },
      })));
    box.append(el("button", {
      className: "chip tiny", type: "button", title: "Load different ideas",
      onclick: loadTrends,
    }, icon(ICONS.shuffle), " New ideas"));
  } catch {
    box.textContent = "";
  }
}
loadTrends();

/* ------------------------------------------------------------------ history */
const FILTERS = [
  ["all", "All"], ["running", "In progress"], ["done", "Ready"], ["failed", "Failed"],
];

function renderFilters() {
  const box = $("#jobFilters");
  if (box.childElementCount) {
    $$("button", box).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.f === state.filter)));
    return;
  }
  FILTERS.forEach(([f, label]) =>
    box.append(el("button", {
      type: "button", textContent: label, dataset: { f },
      "aria-pressed": String(f === state.filter),
      onclick: () => { state.filter = f; renderFilters(); renderHistory(); },
    })));
}

const matchesFilter = (j) => {
  if (state.filter === "all") return true;
  if (state.filter === "running") return BUSY(j.status);
  if (state.filter === "done") return j.status === "done" || j.status === "needs_review";
  return j.status === "failed";
};

const rowSummary = (j) => {
  const parts = [];
  if (BUSY(j.status)) parts.push(j.progress?.label || STATUS_TEXT[j.status]);
  else if (j.status === "failed") parts.push("Failed");
  else {
    if (j.duration) parts.push(`${j.duration.toFixed(0)}s`);
    if (j.scenes) parts.push(plural(j.scenes, "scene"));
    if (j.score) parts.push(`${j.score}/10`);
  }
  parts.push(ago(j.created));
  return parts.join(" · ");
};

/* A running job pushes several updates a second. Rebuilding the list each time
   would drop hover and focus, so only a change of membership, order, status or
   selection rebuilds; progress alone is patched into the existing rows. */
let histKey = null;
const rowRefs = new Map();

function renderHistory() {
  const ul = $("#history");
  const q = state.query.toLowerCase();
  const shown = state.jobs.filter(
    (j) => matchesFilter(j) && (!q || `${j.title || ""} ${j.topic}`.toLowerCase().includes(q))
  );

  $("#jobCount").hidden = !state.jobs.length;
  $("#jobCount").textContent = state.jobs.length;

  const key = shown.map((j) => `${j.id}:${j.status}:${j.title || ""}`).join("|") + "#" + state.currentId;
  if (key === histKey) {
    shown.forEach((j) => {
      const r = rowRefs.get(j.id);
      if (!r) return;
      r.sub.textContent = rowSummary(j);
      if (r.bar) r.bar.style.width = Math.round((j.progress?.ratio || 0) * 100) + "%";
    });
    return;
  }
  histKey = key;
  rowRefs.clear();
  ul.textContent = "";

  if (!shown.length) {
    ul.append(el("li", { className: "placeholder" },
      state.jobs.length ? "Nothing matches that filter." : "Videos you make show up here."));
    return;
  }

  shown.forEach((j) => {
    const name = j.title || j.topic;
    const sub = el("span", { className: "sub", textContent: rowSummary(j) });
    const bar = BUSY(j.status)
      ? el("i", { style: `width:${Math.round((j.progress?.ratio || 0) * 100)}%` })
      : null;
    rowRefs.set(j.id, { sub, bar });

    ul.append(el("li", { className: "job-row" },
      el("button", {
        className: "open", type: "button",
        "aria-current": String(j.id === state.currentId),
        onclick: () => selectJob(j.id),
      },
        el("span", { className: "dot " + j.status, title: STATUS_TEXT[j.status] || j.status }),
        el("span", {},
          el("span", { className: "t", textContent: name, title: name }),
          sub,
          bar && el("span", { className: "mini-bar" }, bar))),
      el("div", { className: "job-actions" },
        j.status === "failed" && el("button", {
          className: "icon-btn ghost", type: "button", title: "Run this topic again",
          "aria-label": `Retry ${name}`,
          onclick: (e) => { e.stopPropagation(); retryJob(j.id); },
        }, icon(ICONS.retry)),
        !BUSY(j.status) && el("button", {
          className: "icon-btn ghost", type: "button", title: "Delete",
          "aria-label": `Delete ${name}`,
          onclick: (e) => { e.stopPropagation(); deleteJob(j); },
        }, icon(ICONS.trash)))));
  });
}

$("#jobSearch").addEventListener("input", (e) => {
  state.query = e.target.value.trim();
  renderHistory();
});

function renderStats() {
  const s = state.stats;
  const box = $("#stats");
  box.textContent = "";
  if (!s || !s.total) return;
  const stat = (label, value, optional) =>
    el("div", { className: "stat" + (optional ? " optional" : "") }, el("b", {}, value), label);
  box.append(stat("made", s.total));
  if (s.running) box.append(stat("running", s.running));
  if (s.ready) box.append(stat("ready", s.ready, true));
  if (s.avg_score) box.append(stat("avg score", s.avg_score, true));
  if (s.avg_seconds) box.append(stat("avg build", secs(s.avg_seconds), true));
}

async function deleteJob(j) {
  if (!confirm(`Delete "${j.title || j.topic}"? The video and package are removed from disk.`)) return;
  try {
    await api("/api/jobs/" + j.id, { method: "DELETE" });
    if (state.currentId === j.id) {
      state.currentId = null;
      state.job = null;
      closeJobStream();
      renderStage();
      renderInspector();
    }
    toast("Deleted");
  } catch (e) {
    toast(e.message, "err");
  }
}

async function retryJob(id) {
  try {
    await api(`/api/jobs/${id}/retry`, { method: "POST" });
    selectJob(id);
    toast("Running again", "ok");
  } catch (e) {
    toast(e.message, "err");
  }
}

/* ------------------------------------------------------------------ live streams */
function openListStream() {
  const es = new EventSource("/api/stream/jobs");
  es.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    state.jobs = d.jobs;
    state.stats = d.stats;
    renderHistory();
    renderStats();
  };
  es.addEventListener("end", () => es.close());
}

let jobStream = null;
const closeJobStream = () => { jobStream?.close(); jobStream = null; };

function openJobStream(id) {
  closeJobStream();
  const es = new EventSource(`/api/stream/jobs/${id}`);
  jobStream = es;
  es.onmessage = (ev) => {
    if (state.currentId !== id) return;
    applyJob(JSON.parse(ev.data));
  };
  es.addEventListener("end", () => es.close());
  es.addEventListener("gone", () => {
    es.close();
    if (state.currentId === id) { state.currentId = null; state.job = null; renderStage(); renderInspector(); }
  });
}

/** A short signature of everything the inspector lays out, so we only rebuild on real change. */
const shapeOf = (j) =>
  JSON.stringify([
    j.id, j.status, j.plan?.scenes?.map((s) => [s.caption, s.voiceover, s.visual.mode, s.visual.query, s.visual.prompt]),
    j.plan?.title, j.plan?.description, j.plan?.hashtags, j.plan?.hook_options,
    j.critique?.overall, j.qa?.checks?.length, j.scene_assets, j.log?.length, state.tab,
  ]);

let lastShape = null;

function applyJob(job) {
  state.job = job;
  renderStage();
  const shape = shapeOf(job);
  if (shape !== lastShape) {
    lastShape = shape;
    renderInspector();
  }
}

async function selectJob(id) {
  if (state.currentId !== id) {
    state.currentId = id;
    state.job = null;
    state.activeShot = 0;
    lastShape = null;
    state.tab = "script";
  }
  renderHistory();
  try {
    applyJob(await api("/api/jobs/" + id));
  } catch (e) {
    toast(e.message, "err");
    return;
  }
  if (BUSY(state.job.status)) openJobStream(id);
  else closeJobStream();
}

/* ------------------------------------------------------------------ stage */
/** Rendered scene start times. render_one pads each scene (+0.3s, +0.9s on the last). */
function sceneStarts(job) {
  const out = [];
  let t = 0;
  const assets = job.scene_assets || [];
  assets.forEach((a, i) => {
    out.push(t);
    t += (a.duration || 0) + (i === assets.length - 1 ? 0.9 : 0.3);
  });
  return out;
}

/* Posters only exist once a scene has rendered, and `updated` is stable while a
   job is idle — so busting the cache with it refetches exactly once per render. */
const posterUrl = (job, i) => `/api/jobs/${job.id}/scenes/${i + 1}/poster?t=${Math.round(job.updated)}`;

function renderStage() {
  const job = state.job;
  const screen = $("#screen");

  if (!job) {
    $("#strip").hidden = true;
    $("#stageActions").textContent = "";
    screen.textContent = "";
    screen.append(el("div", { className: "idle" },
      el("h3", {}, "Type an idea.", el("br"), "Get a reel."),
      el("p", {}, "Qreate researches the topic, writes a hook-first script, critiques itself, then edits a captioned 9:16 video."),
      el("div", { className: "steps-inline" },
        ["Research", "Script", "Critic", "Visuals", "Voice", "Captions", "QA"].map((s) => el("span", {}, s)))));
    return;
  }

  if (!BUSY(job.status) && job.outputs.video) {
    // Keep the existing <video> alive across pushes so playback is not interrupted.
    const existing = screen.querySelector("video");
    const src = job.outputs.video + "?t=" + Math.round(job.updated);
    if (!existing || !existing.src.endsWith(src)) {
      screen.textContent = "";
      screen.append(el("video", {
        src, poster: job.outputs.thumbnail + "?t=" + Math.round(job.updated),
        controls: true, playsInline: true, preload: "metadata",
      }));
    }
    const qa = job.qa;
    if (qa) {
      const ok = qa.passed;
      screen.querySelector(".badge-float")?.remove();
      screen.append(el("div", { className: "badge-float " + (ok ? "ok" : "warn") },
        ok ? "QA passed" : `${qa.checks.filter((c) => !c.pass).length} warnings`));
    }
    renderStrip(job);
    renderStageActions(job);
    return;
  }

  renderStrip(job);
  renderStageActions(job);

  const p = job.progress || { ratio: 0, done: 0, total: 8 };
  const pct = Math.round(p.ratio * 100);
  const C = 2 * Math.PI * 19;

  const ring = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  ring.setAttribute("viewBox", "0 0 46 46");
  ring.setAttribute("class", "ring");
  ring.innerHTML =
    `<circle class="track" cx="23" cy="23" r="19"/>` +
    `<circle class="fill" cx="23" cy="23" r="19" stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - p.ratio)}"/>`;

  const wrap = el("div", { className: "run" },
    el("div", { className: "run-top" }, ring,
      el("div", {},
        el("div", { className: "pct" }, pct + "%"),
        el("div", { className: "who" }, job.status === "queued" ? "Waiting for a worker" : p.label || "Working"))),
    el("h3", {}, job.plan?.title || job.request.topic));

  const ol = el("ol", { className: "steps" });
  Object.values(job.stages).forEach((st) => {
    const mark = st.status === "done" ? "✓" : st.status === "failed" ? "!" : st.status === "running" ? "●" : "";
    ol.append(el("li", { className: st.status },
      el("span", { className: "mark" + (st.status === "running" ? " spin" : "") }, mark),
      el("span", {}, st.label, st.detail && el("small", {}, st.detail)),
      el("span", { className: "ms" }, took(st))));
  });
  wrap.append(ol);
  if (job.error) wrap.append(el("div", { className: "err" }, job.error));

  screen.textContent = "";
  screen.append(wrap);
}

function renderStrip(job) {
  const box = $("#strip");
  const n = job.plan?.scenes?.length || 0;
  // While a job is building, `updated` changes constantly and posters do not
  // exist yet, so the strip stays hidden rather than thrashing the network.
  if (!n || BUSY(job.status) || !job.outputs.video) { box.hidden = true; return; }

  const starts = sceneStarts(job);
  box.hidden = false;
  box.textContent = "";
  box.append(el("div", { className: "strip-head" },
    el("span", {}, plural(n, "scene")),
    el("span", { style: "text-transform:none;font-weight:500" },
      job.qa?.duration ? `${job.qa.duration.toFixed(1)}s total` : "")));

  const rail = el("div", { className: "strip-rail" });
  job.plan.scenes.forEach((_, i) => {
    rail.append(el("button", {
      className: "shot" + (i === state.activeShot ? " active" : ""),
      type: "button", title: `Jump to scene ${i + 1}`,
      "aria-label": `Jump to scene ${i + 1}`,
      onclick: () => {
        state.activeShot = i;
        const v = $("#screen video");
        if (v && starts[i] !== undefined) { v.currentTime = starts[i]; v.play().catch(() => {}); }
        renderStrip(job);
      },
    },
      el("img", { src: posterUrl(job, i), alt: "", loading: "lazy", onerror: (e) => e.target.remove() }),
      el("span", { className: "n" }, i + 1)));
  });
  box.append(rail);
}

function renderStageActions(job) {
  const box = $("#stageActions");
  box.textContent = "";
  if (BUSY(job.status) || !job.outputs.video) return;
  box.append(
    el("a", { className: "btn primary sm", href: job.outputs.video + "?download=true" },
      icon(ICONS.download), "Download video"),
    el("a", { className: "btn sm", href: job.outputs.package }, icon(ICONS.pkg), "Package"),
    el("button", {
      className: "btn sm", type: "button",
      onclick: () => window.open(job.outputs.video, "_blank", "noopener"),
    }, icon(ICONS.external), "Open full size"));
}

/* ------------------------------------------------------------------ inspector */
const TABS = [["script", "Script"], ["review", "Review"], ["post", "Post"], ["activity", "Activity"]];

/** Remember what was focused so a rebuild does not steal the caret. */
function withFocusKept(render) {
  const active = document.activeElement;
  const key = active?.dataset?.focusKey;
  const sel = key && "selectionStart" in active ? [active.selectionStart, active.selectionEnd] : null;
  render();
  if (!key) return;
  const next = $(`[data-focus-key="${key}"]`, $("#inspector"));
  if (!next) return;
  next.focus({ preventScroll: true });
  if (sel && "setSelectionRange" in next) {
    try { next.setSelectionRange(sel[0], sel[1]); } catch { /* not a text input */ }
  }
}

function renderInspector() {
  withFocusKept(() => {
    const d = $("#inspector");
    const job = state.job;
    d.textContent = "";

    if (!job) {
      d.append(el("div", { className: "insp-head" }, el("h2", {}, "Nothing selected")));
      d.append(el("p", { className: "hint", style: "margin-top:9px" },
        "Make a video, or pick one from your list, to see its script, review and post."));
      return;
    }

    const plan = job.plan;
    d.append(el("div", { className: "insp-head" },
      el("h2", {}, plan?.title || job.request.topic),
      job.status === "failed" && el("button", {
        className: "btn sm", type: "button", onclick: () => retryJob(job.id),
      }, icon(ICONS.retry), "Retry")));

    const statusClass = { done: "ok", needs_review: "warn", failed: "bad" }[job.status] || "accent";
    const chips = el("div", { className: "meta-chips" },
      el("span", { className: "tag " + statusClass }, STATUS_TEXT[job.status] || job.status),
      el("span", { className: "tag" }, job.request.community),
      el("span", { className: "tag" }, job.request.language),
      el("span", { className: "tag" }, `${job.request.target_seconds}s target`),
      el("span", { className: "tag" }, job.request.visual_style === "ai" ? "AI images" : job.request.visual_style === "stock" ? "Real footage" : "Mixed visuals"),
      plan?.generated_by && el("span", { className: "tag" }, "script: " + plan.generated_by));
    d.append(chips);

    if (job.error) {
      d.append(el("div", { className: "ai-note", style: "margin-top:14px;background:var(--bad-wash);border-color:var(--bad)" },
        icon(ICONS.warn), el("span", {}, job.error)));
    }

    const tabs = el("div", { className: "tabs", role: "tablist" });
    TABS.forEach(([k, label]) => {
      const n = k === "review" ? job.qa?.checks?.length : k === "script" ? plan?.scenes?.length : null;
      tabs.append(el("button", {
        role: "tab", type: "button", id: "tab-" + k,
        "aria-selected": String(state.tab === k), "aria-controls": "panel",
        onclick: () => { state.tab = k; lastShape = shapeOf(job); renderInspector(); },
      }, label, n ? el("span", { className: "n" }, n) : null));
    });
    d.append(tabs);

    const panel = el("div", { className: "panel", id: "panel", role: "tabpanel", "aria-labelledby": "tab-" + state.tab });
    d.append(panel);

    if (!plan) {
      panel.append(el("p", { className: "placeholder" }, "The script appears here once it is written."));
      return;
    }
    ({ script: renderScript, review: renderReview, post: renderPost, activity: renderActivity })[state.tab](panel, job);
  });
}

/* The plan asks for stock or AI, but the provider chain falls back, so the badge
   describes what actually ended up in the scene. */
function assetKind(asset, plannedAi) {
  const src = (asset?.visual_source || "").toLowerCase();
  if (!src) return plannedAi ? "AI" : "Stock";
  if (src.includes("wan")) return "Wan 2.1";
  if (src.includes("ai image")) return "AI";
  if (src.includes("card")) return "Card";
  return "Stock";
}

/* ---- script tab ---- */
function renderScript(panel, job) {
  const busy = BUSY(job.status);
  const plan = job.plan;
  const current = plan.scenes[0].voiceover.trim();
  const options = [current, ...plan.hook_options.filter((h) => h.trim() !== current)];

  if (options.length > 1) {
    panel.append(el("h3", { className: "sec" }, "Opening hook"));
    panel.append(el("p", { className: "hint" },
      "The first three seconds decide whether anyone watches. Pick a different opener and only scene 1 is re-rendered."));
    const hooks = el("div", { className: "hooks" });
    options.forEach((text, i) =>
      hooks.append(el("button", {
        className: "hook", type: "button", disabled: busy,
        "aria-pressed": String(i === 0),
        onclick: () => i !== 0 && pickHook(text),
      }, el("span", { className: "radio" }), el("span", {}, text))));
    panel.append(hooks);
  }

  panel.append(el("h3", { className: "sec" }, "Scenes"));
  panel.append(el("p", { className: "hint" },
    busy ? "Editing is available once the video finishes." : "Edit any scene and only that scene is re-rendered."));

  plan.scenes.forEach((sc, i) => {
    const asset = job.scene_assets?.[i];
    const isAi = sc.visual.mode === "ai_image";
    const serverVals = {
      caption: sc.caption,
      voiceover: sc.voiceover,
      visual: isAi ? sc.visual.prompt || sc.visual.query : sc.visual.query,
    };
    const draft = draftFor(i);
    const vals = { ...serverVals, ...(draft || {}) };
    const isDirty = () => Object.keys(serverVals).some((k) => (draftFor(i) || {})[k] !== undefined
      && (draftFor(i) || {})[k] !== serverVals[k]);

    const card = el("div", { className: "scene" + (isDirty() ? " dirty" : "") });
    const flag = el("span", { className: "unsaved", hidden: !isDirty() }, "Unsaved");

    const field = (key, label, long) => {
      const input = el(long ? "textarea" : "input", {
        className: long ? "small" : "", type: long ? null : "text",
        value: vals[key], dataset: { focusKey: `s${i}-${key}` },
        "aria-label": `Scene ${i + 1} ${label.toLowerCase()}`,
        oninput: (e) => {
          setDraft(i, { [key]: e.target.value });
          const d = isDirty();
          card.classList.toggle("dirty", d);
          flag.hidden = !d;
        },
      });
      return el("div", { className: "field" }, el("label", {}, label), input);
    };

    const save = el("button", { className: "btn primary sm", type: "button", disabled: busy },
      icon(ICONS.save), "Save and re-render");
    const reroll = el("button", { className: "btn sm", type: "button", disabled: busy },
      icon(ICONS.shuffle), "Try another visual");

    save.onclick = () => {
      const d = draftFor(i) || {};
      clearDraft(i);
      regenerate(i + 1, {
        caption: d.caption ?? serverVals.caption,
        voiceover: d.voiceover ?? serverVals.voiceover,
        ...(isAi ? { visual_prompt: d.visual ?? serverVals.visual } : { visual_query: d.visual ?? serverVals.visual }),
      });
    };
    reroll.onclick = () => { clearDraft(i); regenerate(i + 1, {}); };

    const thumb = el("button", {
      className: "thumb", type: "button", title: `Play scene ${i + 1}`,
      "aria-label": `Play scene ${i + 1}`, disabled: busy,
      onclick: () => lightbox(`/api/jobs/${job.id}/scenes/${i + 1}/clip?t=${Math.round(job.updated)}`),
    }, el("span", { className: "play" }, icon(ICONS.play, { fill: "currentColor" })));
    if (!busy && job.outputs.video) {
      thumb.prepend(el("img", { src: posterUrl(job, i), alt: "", loading: "lazy", onerror: (e) => e.target.remove() }));
    }

    card.append(
      el("header", {}, thumb,
        el("div", { style: "min-width:0" },
          el("b", {}, `Scene ${i + 1}`),
          el("span", { className: "src", title: asset?.visual_source },
            asset ? `${asset.visual_source} · ${asset.duration}s` : isAi ? "AI image" : "Footage")),
        el("span", { className: "tag", title: "What was actually used" }, assetKind(asset, isAi))),
      el("div", { className: "fields" },
        field("caption", "On-screen text"),
        field("voiceover", "Voiceover", true),
        field("visual", isAi ? "Image prompt" : "Footage search")),
      el("div", { className: "actions" }, save, reroll, flag));

    panel.append(card);
  });
}

async function regenerate(n, edit) {
  try {
    await api(`/api/jobs/${state.currentId}/scenes/${n}/regenerate`, { method: "POST", body: JSON.stringify(edit) });
    toast(`Re-rendering scene ${n}`);
    lastShape = null;
    openJobStream(state.currentId);
    applyJob(await api("/api/jobs/" + state.currentId));
  } catch (e) {
    toast(e.message, "err");
  }
}

async function pickHook(text) {
  try {
    await api(`/api/jobs/${state.currentId}/hook`, { method: "POST", body: JSON.stringify({ text }) });
    toast("New hook — re-rendering scene 1");
    lastShape = null;
    openJobStream(state.currentId);
    applyJob(await api("/api/jobs/" + state.currentId));
  } catch (e) {
    toast(e.message, "err");
  }
}

function lightbox(src) {
  $("#lightbox")?.remove();
  const box = el("div", {
    className: "lightbox", id: "lightbox", role: "dialog", "aria-modal": "true",
    "aria-label": "Scene preview", tabIndex: -1,
    onclick: (e) => e.target === box && box.remove(),
  },
    el("video", { src, controls: true, autoplay: true, playsInline: true }),
    el("button", {
      className: "btn sm", type: "button",
      style: "position:absolute;top:18px;right:18px",
      onclick: () => box.remove(),
    }, "Close  Esc"));
  document.body.append(box);
  box.focus();
}

/* ---- review tab ---- */
function renderReview(panel, job) {
  const c = job.critique;
  panel.append(el("h3", { className: "sec" }, "Critic"));
  if (c) {
    panel.append(el("div", { className: "overall" },
      el("div", { className: "big" }, String(c.overall), el("small", {}, "/10")),
      el("div", {},
        el("div", { style: "font-weight:600" },
          c.rounds ? `Rewritten ${plural(c.rounds, "time")} to get here` : "Approved on the first pass"),
        el("div", { className: "who" }, "judged by " + c.judged_by))));
    Object.entries(c.scores).forEach(([k, v]) =>
      panel.append(el("div", { className: "score" },
        el("span", {}, k.replace(/_/g, " ")),
        el("div", { className: "bar" },
          el("i", { className: v >= 8 ? "good" : v >= 6.5 ? "mid" : "poor", style: `width:${v * 10}%` })),
        el("b", {}, String(v)))));
    if (c.issues.length) {
      panel.append(el("h3", { className: "sec", style: "margin-top:20px" }, "What the critic flagged"));
      panel.append(el("ul", { className: "issues" }, c.issues.map((t) => el("li", {}, t))));
    }
  } else {
    panel.append(el("p", { className: "placeholder" }, "Scores appear once the critic runs."));
  }

  panel.append(el("h3", { className: "sec", style: "margin-top:26px" }, "Quality checks"));
  if (job.qa) {
    const failed = job.qa.checks.filter((c2) => !c2.pass);
    panel.append(el("p", { className: "hint" },
      failed.length
        ? `${plural(failed.length, "check")} did not pass. Blocking checks stop a video from being marked ready.`
        : "Everything passed. The file is formatted for a vertical mobile feed."));
    panel.append(el("ul", { className: "checks" }, job.qa.checks.map((ch) =>
      el("li", {},
        el("span", { className: "mk " + (ch.pass ? "yes" : ch.blocking ? "no" : "soft") },
          ch.pass ? "✓" : "!", el("span", { className: "sr" }, ch.pass ? "passed" : "failed")),
        el("span", {}, ch.check,
          !ch.pass && !ch.blocking && el("span", { className: "tag warn", style: "margin-left:6px" }, "advisory"),
          el("small", {}, ch.detail))))));
  } else {
    panel.append(el("p", { className: "placeholder" }, "Checks run after the video is edited."));
  }
}

/* ---- post tab ---- */
function renderPost(panel, job) {
  const p = job.plan;
  const busy = BUSY(job.status);
  const stored = state.postDrafts.get(job.id) || {};
  const vals = {
    title: stored.title ?? p.title,
    description: stored.description ?? p.description,
    hashtags: stored.hashtags ?? p.hashtags.join(" "),
  };
  const caption = () => `${vals.title}\n\n${vals.description}\n\n${vals.hashtags}`.trim();

  panel.append(el("div", { className: "ai-note" }, icon(ICONS.warn),
    el("span", {}, "Qreate does not post for you. Download the video, paste this caption, and mark the post as AI-generated on Qoneqt.")));

  const preview = el("div", { className: "post-preview" }, caption());

  const bind = (key, node) => {
    node.dataset.focusKey = "post-" + key;
    node.oninput = (e) => {
      vals[key] = e.target.value;
      state.postDrafts.set(job.id, { ...state.postDrafts.get(job.id), [key]: e.target.value });
      preview.textContent = caption();
      saveBtn.disabled = busy || !changed();
    };
    return node;
  };
  // The API requires a title, so an empty one is never offered as saveable.
  const changed = () =>
    !!vals.title.trim() && (
      vals.title.trim() !== p.title ||
      vals.description.trim() !== p.description ||
      vals.hashtags.trim() !== p.hashtags.join(" "));

  const saveBtn = el("button", { className: "btn primary sm", type: "button", disabled: busy || !changed() },
    icon(ICONS.save), "Save copy");
  saveBtn.onclick = async () => {
    saveBtn.disabled = true;
    try {
      await api(`/api/jobs/${job.id}/plan`, {
        method: "PATCH",
        body: JSON.stringify({
          title: vals.title.trim(),
          description: vals.description.trim(),
          hashtags: vals.hashtags.split(/[\s,]+/).filter(Boolean),
        }),
      });
      state.postDrafts.delete(job.id);
      toast("Caption saved and repackaged", "ok");
      lastShape = null;
      applyJob(await api("/api/jobs/" + job.id));
    } catch (e) {
      toast(e.message, "err");
      saveBtn.disabled = false;
    }
  };

  panel.append(
    el("h3", { className: "sec" }, "Caption"),
    el("div", { className: "fields", style: "display:flex;flex-direction:column;gap:10px;margin-bottom:12px" },
      el("div", { className: "field" }, el("label", {}, "Title"),
        bind("title", el("input", { type: "text", value: vals.title, maxLength: 200, "aria-label": "Post title" }))),
      el("div", { className: "field" }, el("label", {}, "Description"),
        bind("description", el("textarea", { className: "small", value: vals.description, "aria-label": "Post description" }))),
      el("div", { className: "field" }, el("label", {}, "Hashtags"),
        bind("hashtags", el("input", { type: "text", value: vals.hashtags, "aria-label": "Hashtags, space separated" })))),
    el("h3", { className: "sec" }, "Preview"),
    preview);

  const dl = el("div", { className: "dl" }, saveBtn,
    el("button", {
      className: "btn sm", type: "button",
      onclick: async () => {
        try { await navigator.clipboard.writeText(caption()); toast("Caption copied", "ok"); }
        catch { toast("Clipboard blocked — select the text and copy it.", "err"); }
      },
    }, icon(ICONS.copy), "Copy caption"));
  if (job.outputs.video) {
    dl.append(el("a", { className: "btn sm", href: job.outputs.video + "?download=true" }, icon(ICONS.download), "Video"));
    dl.append(el("a", { className: "btn sm", href: job.outputs.package }, icon(ICONS.pkg), "Package"));
  }
  panel.append(dl);

  panel.append(el("h3", { className: "sec" }, "Post it on Qoneqt"));
  panel.append(el("ol", { className: "howto" },
    el("li", {}, "Download the video and copy the caption."),
    el("li", {}, `Open Qoneqt and create a post in ${job.request.community} or the Global Feed.`),
    el("li", {}, "Upload the video, paste the caption, and mark it as AI-generated.")));

  if (p.sources?.length) {
    panel.append(el("h3", { className: "sec" }, "Sources used"));
    panel.append(el("ul", { className: "sources" }, p.sources.map((s) =>
      el("li", {}, el("a", { href: s.url, target: "_blank", rel: "noopener" }, s.title)))));
  }
}

/* ---- activity tab ---- */
function renderActivity(panel, job) {
  panel.append(el("h3", { className: "sec" }, "Pipeline"));
  const stages = Object.values(job.stages);
  const total = stages.reduce((sum, s) => sum + (s.started && s.ended ? s.ended - s.started : 0), 0);
  panel.append(el("p", { className: "hint" },
    total ? `${secs(total)} of compute across ${plural(stages.length, "stage")}.` : "Timings appear as stages finish."));

  panel.append(el("ul", { className: "timeline" }, stages.map((st) =>
    el("li", {},
      el("span", { className: "mk " + (st.status === "done" ? "yes" : st.status === "failed" ? "no" : "soft"),
        style: `color:var(--${st.status === "done" ? "ok" : st.status === "failed" ? "bad" : "text-3"})` },
        st.status === "done" ? "✓" : st.status === "failed" ? "!" : st.status === "running" ? "●" : "·"),
      el("span", {}, st.label, st.detail && el("small", {}, st.detail)),
      el("span", { className: "ms" }, took(st))))));

  panel.append(el("h3", { className: "sec" }, "Log"));
  panel.append(job.log?.length
    ? el("pre", { className: "log" }, job.log.join("\n"))
    : el("p", { className: "placeholder" }, "Nothing logged yet."));
}

/* ------------------------------------------------------------------ boot */
renderFilters();
openListStream();
api("/api/jobs").then((d) => {
  state.jobs = d.jobs;
  state.stats = d.stats;
  renderHistory();
  renderStats();
}).catch(() => {});
