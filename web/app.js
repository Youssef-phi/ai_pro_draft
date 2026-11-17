/* VentureBoard boardroom UI. No build step. All agent text is inserted with textContent, never as HTML. */
(function () {
  "use strict";

  // Original personas: a name, a department, a colour and a voice profile each.
  const AGENTS = {
    orchestrator:   { name: "Kit",  dept: "Chief of staff", color: "#475569", pitch: 1.0,  rate: 1.05, v: 0 },
    researcher:     { name: "Rhea", dept: "Research",       color: "#0e7490", pitch: 1.25, rate: 1.0,  v: 1 },
    market_analyst: { name: "Milo", dept: "Market",         color: "#0369a1", pitch: 0.85, rate: 1.0,  v: 2 },
    strategist:     { name: "Sam",  dept: "Strategy",       color: "#7c3aed", pitch: 1.1,  rate: 0.95, v: 3 },
    engineer:       { name: "Cal",  dept: "Engineering",    color: "#b45309", pitch: 0.75, rate: 1.0,  v: 4 },
    finance:        { name: "Fin",  dept: "Finance",        color: "#15803d", pitch: 0.95, rate: 0.9,  v: 5 },
    policy_drafter: { name: "Lex",  dept: "Policy drafts",  color: "#57534e", pitch: 0.8,  rate: 0.9,  v: 6 },
    marketer:       { name: "Mara", dept: "Marketing",      color: "#be185d", pitch: 1.35, rate: 1.1,  v: 7 },
    sales_ops:      { name: "Sol",  dept: "Sales ops",      color: "#c2410c", pitch: 1.05, rate: 1.05, v: 8 },
    ops_analyst:    { name: "Otto", dept: "Operations",     color: "#4d7c0f", pitch: 0.9,  rate: 0.95, v: 9 },
    advocate:       { name: "Advocate", dept: "The board",  color: "#16a34a", pitch: 1.15, rate: 1.0,  v: 10, board: true },
    critic:         { name: "Critic",   dept: "The board",  color: "#dc2626", pitch: 0.7,  rate: 0.95, v: 11, board: true },
    chair:          { name: "Chair",    dept: "The board",  color: "#737373", pitch: 0.9,  rate: 0.9,  v: 12, board: true },
  };

  // Eye and mouth shapes per emotion: [left brow, right brow, eye radius-y, mouth path]
  const EMOTIONS = {
    neutral:   ["M30 40 L46 40", "M74 40 L90 40", 6,   "M46 80 L74 80"],
    happy:     ["M30 39 L46 37", "M74 37 L90 39", 6,   "M42 76 Q60 94 78 76"],
    excited:   ["M30 33 L46 31", "M74 31 L90 33", 8,   "M40 74 Q60 100 80 74"],
    thinking:  ["M30 38 L46 34", "M74 41 L90 41", 5,   "M50 82 L72 79"],
    skeptical: ["M30 42 L46 42", "M74 33 L90 37", 4.5, "M46 82 Q62 78 76 84"],
    worried:   ["M30 36 L46 41", "M74 41 L90 36", 6.5, "M44 86 Q60 76 76 86"],
    stern:     ["M30 35 L46 41", "M74 41 L90 35", 4.5, "M46 82 L74 82"],
  };

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  let runId = null, muted = false, queue = [], busy = false, voices = [];

  // ---------- faces ----------
  function faceSvg(a) {
    return `<svg viewBox="0 0 120 120" aria-hidden="true">
      <circle cx="60" cy="60" r="52" fill="${a.color}"/>
      <circle cx="60" cy="64" r="44" fill="#fff" opacity=".12"/>
      <ellipse class="eye" cx="40" cy="54" rx="5.5" ry="6" fill="#fff"/><ellipse class="eye" cx="80" cy="54" rx="5.5" ry="6" fill="#fff"/>
      <path class="brow-l" d="M30 40 L46 40" stroke="#fff" stroke-width="4" stroke-linecap="round" fill="none"/>
      <path class="brow-r" d="M74 40 L90 40" stroke="#fff" stroke-width="4" stroke-linecap="round" fill="none"/>
      <path class="mouth-shape" d="M46 80 L74 80" stroke="#fff" stroke-width="4.5" stroke-linecap="round" fill="none"/>
      <ellipse class="mouth-open" cx="60" cy="82" rx="11" ry="8" fill="#fff"/>
    </svg>`;
  }
  function buildFaces() {
    const box = $("faces");
    Object.entries(AGENTS).forEach(([id, a]) => {
      const card = el("div", "face" + (a.board ? " board" : ""));
      card.id = "face-" + id;
      card.innerHTML = faceSvg(a);           // static markup built from constants above, not from agent text
      card.appendChild(el("div", "name", a.name));
      card.appendChild(el("div", "dept", a.dept));
      box.appendChild(card);
    });
  }
  function setEmotion(id, emotion) {
    const card = $("face-" + id); if (!card) return;
    const e = EMOTIONS[emotion] || EMOTIONS.neutral;
    card.querySelector(".brow-l").setAttribute("d", e[0]);
    card.querySelector(".brow-r").setAttribute("d", e[1]);
    card.querySelectorAll(".eye").forEach((eye) => eye.setAttribute("ry", e[2]));
    card.querySelector(".mouth-shape").setAttribute("d", e[3]);
  }

  // ---------- speech: one agent at a time ----------
  function loadVoices() {
    if (!("speechSynthesis" in window)) return;
    const all = speechSynthesis.getVoices();
    const english = all.filter((v) => /^en/i.test(v.lang));
    voices = english.length ? english : all;
  }
  function speak(id, text) {
    return new Promise((resolve) => {
      const card = $("face-" + id), a = AGENTS[id] || AGENTS.chair;
      let done = false, flap = null;
      const finish = () => {
        if (done) return; done = true;
        clearInterval(flap);
        if (card) card.classList.remove("speaking", "talk");
        resolve();
      };
      if (card) card.classList.add("speaking");
      const spoken = text.length > 420 ? text.slice(0, 420) : text;
      const canSpeak = !muted && "speechSynthesis" in window && spoken.trim();
      if (!canSpeak) {                                  // text-only mode: hold the caption long enough to read
        flap = setInterval(() => card && card.classList.toggle("talk"), 180);
        setTimeout(finish, Math.min(9000, 1400 + spoken.length * 38));
        return;
      }
      const u = new SpeechSynthesisUtterance(spoken);
      if (voices.length) u.voice = voices[a.v % voices.length];
      u.pitch = a.pitch; u.rate = a.rate;
      let sawBoundary = false;
      u.onboundary = () => {                             // mouth follows word boundaries when the browser reports them
        sawBoundary = true;
        if (card) { card.classList.add("talk"); setTimeout(() => card.classList.remove("talk"), 110); }
      };
      u.onend = finish; u.onerror = finish;
      flap = setInterval(() => { if (!sawBoundary && card) card.classList.toggle("talk"); }, 170);   // fallback timer
      setTimeout(finish, 6000 + spoken.length * 95);     // safety net if the browser never fires onend
      speechSynthesis.speak(u);
    });
  }

  // ---------- event queue: everything is shown in the order the orchestrator emitted it ----------
  function enqueue(event) { queue.push(event); pump(); }
  async function pump() {
    if (busy) return;
    busy = true;
    while (queue.length) {
      const event = queue.shift();
      try { await handle(event); } catch (err) { console.error(err); }
    }
    busy = false;
  }

  async function handle(ev) {
    switch (ev.type) {
      case "run_started": break;
      case "phase_started": setPhase(ev.phase, ev.name, ev.attempt); break;
      case "speech": await showSpeech(ev); break;
      case "notice": addNotice(ev.level, ev.message); break;
      case "error": addNotice("error", ev.message); showBanner("The run stopped with an error: " + ev.message); break;
      case "threshold": addNotice("info", ev.text); break;
      case "artifact": addFile(ev.file, ev.mocked); break;
      case "gate": showGate(ev); break;
      case "gate_decided": addNotice(ev.override ? "warning" : "info",
        `Phase ${ev.phase} gate: you chose "${ev.decision}". Final: ${ev.final.toUpperCase()}.`); break;
      case "founder_request": showRequest(ev.request_id, ev.request); break;
      case "note_result": break;
      case "run_finished": showFinish(ev); break;
    }
    if (ev.type !== "speech") refreshLog();
  }

  function setPhase(phase, name, attempt) {
    $("phase-title").textContent = `Phase ${phase}: ${name}` + (attempt > 1 ? ` (attempt ${attempt})` : "");
    document.querySelectorAll("#phase-track li").forEach((li) => {
      const n = Number(li.dataset.phase);
      li.className = n < phase ? "done" : n === phase ? "now" : "";
    });
  }

  async function showSpeech(ev) {
    const a = AGENTS[ev.agent] || { name: ev.agent, dept: "" };
    setEmotion(ev.agent, ev.emotion);
    $("cap-who").textContent = `${a.name} · ${a.dept}` + (ev.model ? `  (${ev.model})` : "") +
      (ev.panel_mode === "single" ? "  (single-panel mode)" : "");
    $("cap-line").textContent = ev.speech || "(no spoken line)";
    const box = $("cap-claims"); box.replaceChildren();
    (ev.claims || []).slice(0, 6).forEach((c) => {
      const row = el("div", "claim");
      if (c.label === "SOURCED" && c.source_url) {
        const link = el("a", "badge sourced", "SOURCED");
        link.href = c.source_url; link.target = "_blank"; link.rel = "noopener noreferrer";
        row.appendChild(link);
      } else {
        row.appendChild(el("span", "badge assumption", "ASSUMPTION"));
      }
      row.appendChild(document.createTextNode(c.text));
      box.appendChild(row);
    });
    refreshLog();
    await speak(ev.agent, ev.speech || "");
  }

  function addNotice(level, message) {
    const li = el("li", level, message);
    $("notices").prepend(li);
  }
  function showBanner(text) { const b = $("banner"); b.textContent = text; b.hidden = false; }

  function addFile(name, mocked) {
    if ([...$("files").children].some((li) => li.dataset.name === name)) return;
    const li = el("li"); li.dataset.name = name;
    const link = el("a", null, name);
    link.href = `/api/runs/${runId}/files/${encodeURIComponent(name)}`; link.target = "_blank"; link.rel = "noopener";
    li.appendChild(link);
    if (mocked || /mocked|payment_test/.test(name)) { li.appendChild(document.createTextNode(" ")); li.appendChild(el("span", "mock", "MOCKED")); }
    $("files").prepend(li);
  }

  function showGate(ev) {
    $("gate-panel").hidden = false;
    const body = $("gate-body"); body.replaceChildren();
    const head = el("p");
    head.appendChild(document.createTextNode(`Phase ${ev.phase}: ${ev.name}  `));
    head.appendChild(el("span", "verdict " + ev.outcome, ev.outcome.toUpperCase()));
    body.appendChild(head);
    if (ev.overridden_by_code) body.appendChild(el("p", "hint",
      `The Chair recommended ${String(ev.chair_verdict).toUpperCase()}. The hard checks in code made it stricter.`));
    if (ev.explanation) body.appendChild(el("p", null, ev.explanation));
    if ((ev.checks || []).length) {
      const t = el("table"); t.appendChild(row(["Check (target set in advance)", "Target", "Actual", "Passed"], "th"));
      ev.checks.forEach((c) => { const r = row([c.name, c.target, c.actual, c.passed ? "yes" : "NO"]); r.lastChild.className = c.passed ? "yes" : "no"; t.appendChild(r); });
      body.appendChild(t);
    }
    if (ev.scores && Object.keys(ev.scores).length) {
      const t = el("table"); t.appendChild(row(["Chair's rubric", "0-4"], "th"));
      Object.entries(ev.scores).forEach(([k, v]) => t.appendChild(row([k.replace(/_/g, " "), v])));
      t.appendChild(row(["average", ev.chair_average]));
      body.appendChild(t);
    }
    (ev.reasons || []).forEach((r) => body.appendChild(el("p", "hint", "• " + r)));
    if (ev.best_pivot) body.appendChild(el("p", null, "Best pivot: " + ev.best_pivot));
  }
  function row(cells, tag) { const tr = el("tr"); cells.forEach((c) => tr.appendChild(el(tag || "td", null, String(c)))); return tr; }

  // ---------- founder decisions ----------
  async function answer(requestId, payload, card) {
    card.querySelectorAll("button,input,textarea").forEach((b) => (b.disabled = true));
    await fetch(`/api/runs/${runId}/answer`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: requestId, answer: payload }) });
    card.remove();
    if (!$("requests").children.length) $("requests").appendChild(el("p", "hint", "Nothing needs your decision right now."));
  }
  function button(label, cls, onClick) { const b = el("button", cls, label); b.type = "button"; b.addEventListener("click", onClick); return b; }

  function showRequest(id, req) {
    const box = $("requests");
    box.querySelectorAll("p.hint").forEach((p) => p.remove());
    const card = el("div", "request");
    const rowEl = el("div", "row");
    if (req.kind === "action") {
      const a = req.action;
      const title = el("p"); title.appendChild(el("strong", null, a.kind.toUpperCase() + " "));
      if (a.mocked) title.appendChild(el("span", "mock", "MOCKED"));
      card.appendChild(title);
      card.appendChild(el("p", null, a.description));
      if (a.preview) card.appendChild(el("div", "preview", a.preview));
      rowEl.appendChild(button("Approve", "ok", () => answer(id, { decision: "approve" }, card)));
      rowEl.appendChild(button("Reject", "danger", () => answer(id, { decision: "reject" }, card)));
    } else if (req.kind === "evidence") {
      card.appendChild(el("p", null, req.question));
      const n = el("input"); n.type = "number"; n.min = "0"; n.placeholder = "Real sign-ups (leave empty if none yet)";
      const notes = el("textarea"); notes.rows = 3; notes.placeholder = "Real interview notes, if you have any (optional)";
      card.appendChild(n); card.appendChild(notes);
      card.appendChild(el("p", "hint", "Only numbers you type here are used. The system never invents sign-ups."));
      rowEl.appendChild(button("Report to the board", "primary", () => answer(id, { waitlist_signups: n.value, interview_notes: notes.value }, card)));
    } else {
      const title = el("p"); title.appendChild(document.createTextNode(`Phase ${req.phase} gate. The board recommends `));
      title.appendChild(el("span", "verdict " + req.recommendation, req.recommendation.toUpperCase()));
      card.appendChild(title);
      if (req.warning) card.appendChild(el("p", "hint", "If you override: " + req.warning));
      const pivot = el("input"); pivot.placeholder = "Pivot idea (empty = use the board's suggestion)";
      rowEl.appendChild(button("Approve recommendation", "ok", () => answer(id, { decision: "approve" }, card)));
      if (req.recommendation !== "go") rowEl.appendChild(button("Override and go on", null, () => answer(id, { decision: "override_go" }, card)));
      rowEl.appendChild(button("Pivot", null, () => answer(id, { decision: "pivot", pivot_idea: pivot.value }, card)));
      rowEl.appendChild(button("Stop", "danger", () => answer(id, { decision: "stop" }, card)));
      card.appendChild(pivot);
    }
    card.appendChild(rowEl);
    box.appendChild(card);
  }

  function showFinish(ev) {
    const u = ev.usage || {};
    const tokens = (u.tokens_in || 0) + (u.tokens_out || 0);
    const p = el("div", "final");
    p.appendChild(el("strong", null, ev.status === "completed" ? "Run complete. " : ev.status === "stop" ? "Stopped. " : "Ended. "));
    p.appendChild(document.createTextNode(ev.summary + ` Cost of this run: $${Number(u.cost || 0).toFixed(4)} (${tokens} tokens, ${u.calls || 0} model calls).`));
    $("requests").replaceChildren(p);
    $("phase-title").textContent = ev.status === "completed" ? "All gates passed" : "Run ended: " + ev.status.toUpperCase();
  }

  async function refreshLog() {
    if (!runId) return;
    try {
      const entries = await (await fetch(`/api/runs/${runId}/log`)).json();
      const box = $("log"); box.replaceChildren();
      entries.slice(-40).reverse().forEach((e) => {
        const line = `${e.timestamp.slice(11, 19)}  ${e.agent}.${e.action}  model=${e.model || "none"}  cost=$${e.cost}  sources=${e.sources.length}` +
          (e.outcome ? `  outcome=${e.outcome}` : "") + (e.approved_by ? `  approved_by=${e.approved_by}` : "");
        box.appendChild(el("div", e.approved_by ? "founder" : null, line));
      });
    } catch (err) { /* the log is a convenience view; ignore transient errors */ }
  }

  // ---------- start-up ----------
  async function loadStatus() {
    try {
      const s = await (await fetch("/api/status")).json();
      const model = s.llm.primary === "ollama" ? s.local_model : (s.llm.models.chair || "");
      $("chip-model").textContent = `model: ${model} via ${s.llm.primary}`;
      $("chip-panel").textContent = `panel: ${s.panel_mode}`;
      $("mock-list").textContent = s.mocked.join(", ");
      const t = s.thresholds;
      $("threshold-list").textContent = `Phase 1 needs at least ${t["1"].min_sourced_claims} sourced market claims. ` +
        `Phase 2 needs ${t["2"].waitlist_target} real waitlist sign-ups in ${t["2"].waitlist_days} days. Later phases need their tests to pass.`;
      const track = $("phase-track"); track.replaceChildren();
      Object.entries(s.phases).forEach(([n, name]) => { const li = el("li", null, `${n} ${name.split(" (")[0]}`); li.dataset.phase = n; track.appendChild(li); });
      if (s.llm.primary === "ollama" && s.local_model_ready === false)
        showBanner(`The local model ${s.local_model} is still downloading (first start only). You can fill in the brief; runs will work once the download finishes.`);
    } catch (err) { $("chip-model").textContent = "model: status unavailable"; }
  }

  $("mute").addEventListener("click", () => {
    muted = !muted;
    $("mute").textContent = muted ? "Muted (text only)" : "Sound on";
    $("mute").setAttribute("aria-pressed", String(muted));
    if (muted && "speechSynthesis" in window) speechSynthesis.cancel();
  });

  $("brief-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const brief = Object.fromEntries(new FormData(event.target).entries());
    const res = await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(brief) });
    if (!res.ok) { showBanner("Could not start: " + ((await res.json()).detail || res.status)); return; }
    runId = (await res.json()).run_id;
    $("brief-section").hidden = true; $("room-section").hidden = false; $("banner").hidden = true;
    if ("speechSynthesis" in window) speechSynthesis.cancel();
    const source = new EventSource(`/api/runs/${runId}/events`);
    source.onmessage = (m) => enqueue(JSON.parse(m.data));
    source.addEventListener("end", () => source.close());
  });

  $("note-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = $("note-text").value.trim(); if (!text || !runId) return;
    const res = await (await fetch(`/api/runs/${runId}/note`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) })).json();
    $("note-result").textContent = res.message;
    $("note-result").style.color = res.accepted ? "" : "#b91c1c";
    $("note-text").value = "";
    refreshLog();
  });

  buildFaces();
  loadVoices();
  if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = loadVoices;
  loadStatus();
})();
