const STEP_ORDER = [
  "load", "diverge", "critique", "polish", "anchor", "caption", "images", "video", "save",
];
const IMAGE_STEPS = new Set(["image", "images"]);
const ELEVATE_STEPS = ["load", "diverge", "critique", "polish", "anchor"];
const TIMELINE_STEPS = ["seed", "diverge", "critique", "polish", "anchor"];

const STEP_LABELS = {
  seed: "Seed idea",
  diverge: "Brainstorm (8 concepts)",
  critique: "Critique & winner",
  polish: "Polish brief",
  anchor: "Intent check",
};

let currentPlan = null;
let currentIdeaBrief = null;
let ideaState = emptyIdeaState();
let timelineRunning = false;

function emptyIdeaState() {
  return {
    seed: "",
    audience: "",
    preset: "",
    diverge_candidates: [],
    critique: {},
    winner: {},
    winner_title: "",
    polished_concept: {},
    anchor: {},
    plan: null,
  };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function initBrandPanels() {
  const select = document.getElementById("gen-brand");
  if (!select) return;

  function showBrand(brandId) {
    document.querySelectorAll(".asset-group").forEach((el) => {
      el.hidden = el.id !== `assets-brand-${brandId}`;
    });
    document.querySelectorAll(".brand-preview-panel").forEach((el) => {
      el.hidden = el.id !== `brand-preview-${brandId}`;
    });
  }

  showBrand(select.value);
  select.addEventListener("change", () => showBrand(select.value));
}

function setVideoStepVisible(isVideo) {
  const step = document.querySelector('.progress-steps [data-step="video"]');
  if (step) step.hidden = !isVideo;
}

function stepIndex(step, steps) {
  if (IMAGE_STEPS.has(step)) return steps.indexOf("images");
  return steps.indexOf(step);
}

function updateProgressUi(step, detail, steps) {
  const detailEl = document.getElementById("progress-detail");
  if (detailEl) detailEl.textContent = detail;

  const idx = stepIndex(step, steps);
  if (idx < 0) return;

  document.querySelectorAll(".progress-steps li").forEach((li) => {
    const liStep = li.dataset.step;
    const liIdx = steps.indexOf(liStep);
    if (li.hidden) return;
    li.classList.remove("step-active", "step-done");
    if (liIdx < idx) li.classList.add("step-done");
    else if (liIdx === idx) li.classList.add("step-active");
  });
}

function showProgressPanel(format, title, steps) {
  const progressPanel = document.getElementById("generate-progress-panel");
  if (progressPanel) progressPanel.hidden = false;
  const titleEl = document.getElementById("progress-title");
  if (titleEl) titleEl.textContent = title;
  setVideoStepVisible(format === "video");
  updateProgressUi("load", "Starting…", steps);
}

function hideProgressPanel() {
  const progressPanel = document.getElementById("generate-progress-panel");
  if (progressPanel) progressPanel.hidden = true;
  const errorEl = document.getElementById("progress-error");
  const backEl = document.getElementById("progress-back");
  const spinner = document.querySelector(".progress-panel .spinner");
  if (errorEl) errorEl.hidden = true;
  if (backEl) backEl.hidden = true;
  if (spinner) spinner.hidden = false;
}

function showError(message) {
  const detailEl = document.getElementById("progress-detail");
  const errorEl = document.getElementById("progress-error");
  const backEl = document.getElementById("progress-back");
  const spinner = document.querySelector(".progress-panel .spinner");
  if (detailEl) detailEl.textContent = "Failed";
  if (errorEl) {
    errorEl.textContent = message;
    errorEl.hidden = false;
  }
  if (backEl) backEl.hidden = false;
  if (spinner) spinner.hidden = true;
}

function showTimelineStatus(detail) {
  const status = document.getElementById("timeline-status");
  const text = document.getElementById("timeline-status-text");
  if (status) status.hidden = false;
  if (text) text.textContent = detail || "Working…";
}

function hideTimelineStatus() {
  const status = document.getElementById("timeline-status");
  if (status) status.hidden = true;
}

function showTimeline() {
  const timeline = document.getElementById("idea-timeline");
  if (timeline) {
    timeline.hidden = false;
    timeline.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function setTimelineStepStatus(activeStep) {
  document.querySelectorAll(".timeline-step").forEach((el) => {
    const step = el.dataset.step;
    el.classList.remove("step-active", "step-done", "step-pending");
    if (activeStep === "complete") {
      el.classList.add("step-done");
      return;
    }
    const stepIdx = TIMELINE_STEPS.indexOf(step);
    const activeIdx = TIMELINE_STEPS.indexOf(activeStep);
    if (activeIdx < 0) return;
    if (stepIdx < activeIdx) el.classList.add("step-done");
    else if (stepIdx === activeIdx) el.classList.add("step-active");
    else el.classList.add("step-pending");
  });
}

function mergeStepDone(step, data) {
  if (step === "diverge" && data.concepts) {
    ideaState.diverge_candidates = data.concepts;
  }
  if (step === "critique") {
    if (data.critique) ideaState.critique = data.critique;
    if (data.winner) ideaState.winner = data.winner;
    ideaState.winner_title = data.critique?.winner_title || ideaState.winner?.title || ideaState.winner_title;
  }
  if (step === "polish") {
    if (data.polished_concept) ideaState.polished_concept = data.polished_concept;
    if (data.plan) ideaState.plan = data.plan;
  }
  if (step === "anchor") {
    if (data.anchor) ideaState.anchor = data.anchor;
    if (data.plan) ideaState.plan = data.plan;
    if (data.idea_brief) {
      currentIdeaBrief = data.idea_brief;
      ideaState = { ...ideaState, ...data.idea_brief };
    }
  }
  if (data.plan) currentPlan = data.plan;
}

function syncHiddenInputs(plan, brief) {
  document.getElementById("refined-plan-input").value = JSON.stringify(plan || {});
  document.getElementById("idea-brief-input").value = JSON.stringify(brief || {});
}

function readSeedFromForm() {
  const form = document.getElementById("generate-form");
  if (!form) return "";
  return (form.querySelector('[name="topic_hint"]')?.value || "").trim();
}

function readFormMeta() {
  const form = document.getElementById("generate-form");
  if (!form) return { audience: "", preset: "" };
  return {
    audience: (form.querySelector('[name="audience"]')?.value || "").trim(),
    preset: form.querySelector('[name="preset"]')?.value || "",
  };
}

function truncateText(text, max = 100) {
  const value = String(text || "").trim();
  if (value.length <= max) return value;
  return `${value.slice(0, max)}…`;
}

function isWinnerTitle(title, winnerTitle) {
  if (!winnerTitle || !title) return false;
  const a = title.trim().toLowerCase();
  const b = winnerTitle.trim().toLowerCase();
  return a === b || a.includes(b) || b.includes(a);
}

function getWinnerConcept() {
  const winnerTitle = ideaState.winner_title || ideaState.critique?.winner_title || "";
  if (ideaState.winner?.title) return ideaState.winner;
  const concepts = ideaState.diverge_candidates || [];
  return concepts.find((c) => isWinnerTitle(c.title, winnerTitle)) || ideaState.winner || {};
}

function readConceptFromCard(card) {
  return {
    title: card.querySelector('[data-field="title"]')?.value?.trim() || "",
    strategic_rationale: card.querySelector('[data-field="strategic_rationale"]')?.value?.trim() || "",
    scroll_stop_moment: card.querySelector('[data-field="scroll_stop_moment"]')?.value?.trim() || "",
    hook: card.querySelector('[data-field="hook"]')?.value?.trim() || "",
    visual_gag: card.querySelector('[data-field="visual_gag"]')?.value?.trim() || "",
    caption_arc: (card.querySelector('[data-field="caption_arc"]')?.value || "")
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean),
    caption_angle: card.querySelector('[data-field="caption_angle"]')?.value?.trim() || "",
    differentiation: card.querySelector('[data-field="differentiation"]')?.value?.trim() || "",
    facts_to_keep: (card.querySelector('[data-field="facts_to_keep"]')?.value || "")
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean),
    risk_level: card.querySelector('[data-field="risk_level"]')?.value || "medium",
  };
}

function readStateFromDom() {
  const seedEl = document.getElementById("timeline-seed-input");
  const seed = seedEl ? seedEl.value.trim() : readSeedFromForm();
  const meta = readFormMeta();

  const concepts = [...document.querySelectorAll(".concept-card")].map(readConceptFromCard);
  const winnerRadio = document.querySelector('input[name="winner_pick"]:checked');
  const winnerTitle = winnerRadio?.value || ideaState.winner_title || ideaState.critique?.winner_title || "";

  const polished = {
    ...(ideaState.polished_concept || {}),
    creative_title: document.getElementById("tl-edit-title")?.value?.trim() || "",
    hook: document.getElementById("tl-edit-hook")?.value?.trim() || "",
    angle: document.getElementById("tl-edit-angle")?.value?.trim() || "",
    topic: document.getElementById("tl-edit-topic")?.value?.trim() || "",
    visual_concept: document.getElementById("tl-edit-visual")?.value?.trim() || "",
    image_prompt_en: document.getElementById("tl-edit-image-prompt")?.value?.trim() || "",
    caption_structure: (document.getElementById("tl-edit-caption-structure")?.value || "")
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean),
  };

  const winner = concepts.find((c) => isWinnerTitle(c.title, winnerTitle)) || ideaState.winner || {};

  return {
    seed,
    audience: meta.audience,
    preset: meta.preset,
    diverge_candidates: concepts.length ? concepts : ideaState.diverge_candidates,
    critique: ideaState.critique,
    winner,
    winner_title: winnerTitle,
    polished_concept: polished,
    anchor: ideaState.anchor,
    plan: ideaState.plan,
  };
}

function renderConceptCard(concept, index, winnerTitle, dimLosers) {
  const title = concept.title || `Concept ${index + 1}`;
  const isWinner = isWinnerTitle(title, winnerTitle);
  const checked = isWinner ? "checked" : "";
  const dimClass = dimLosers && winnerTitle && !isWinner ? "concept-card-dimmed" : "";
  const winnerClass = isWinner ? "concept-card-winner" : "";
  const captionArc = (concept.caption_arc || []).join("\n");
  return `
    <article class="concept-card ${winnerClass} ${dimClass}" data-index="${index}" id="concept-card-${index}">
      <header class="concept-card-header">
        <label class="winner-pick">
          <input type="radio" name="winner_pick" value="${escapeHtml(title)}" ${checked}>
          <span>Pick as winner</span>
        </label>
        <div class="concept-card-badges">
          ${isWinner ? '<span class="winner-badge">Chosen</span>' : ""}
          <span class="risk-tag risk-${escapeHtml(concept.risk_level || "medium")}">${escapeHtml(concept.risk_level || "medium")}</span>
        </div>
      </header>
      <label>Title
        <input type="text" data-field="title" value="${escapeHtml(title)}">
      </label>
      <label>Why this works (strategy)
        <textarea data-field="strategic_rationale" rows="3">${escapeHtml(concept.strategic_rationale || "")}</textarea>
      </label>
      <label>Scroll-stop moment
        <textarea data-field="scroll_stop_moment" rows="2">${escapeHtml(concept.scroll_stop_moment || "")}</textarea>
      </label>
      <label>Hook
        <textarea data-field="hook" rows="2">${escapeHtml(concept.hook || "")}</textarea>
      </label>
      <label>Visual gag (shot direction)
        <textarea data-field="visual_gag" rows="4">${escapeHtml(concept.visual_gag || "")}</textarea>
      </label>
      <label>Caption arc (one beat per line)
        <textarea data-field="caption_arc" rows="3">${escapeHtml(captionArc)}</textarea>
      </label>
      <label>Caption angle (summary)
        <textarea data-field="caption_angle" rows="2">${escapeHtml(concept.caption_angle || "")}</textarea>
      </label>
      <label>Differentiation
        <textarea data-field="differentiation" rows="2">${escapeHtml(concept.differentiation || "")}</textarea>
      </label>
      <label>Facts to keep (one per line)
        <textarea data-field="facts_to_keep" rows="2">${escapeHtml((concept.facts_to_keep || []).join("\n"))}</textarea>
      </label>
    </article>
  `;
}

function renderDimensionScores(scores, notes) {
  if (!scores || typeof scores !== "object") return "";
  const dims = ["engagement", "intent_fidelity", "brand_fit", "depth", "visual_feasibility"];
  return `
    <dl class="dimension-scores">
      ${dims.map((dim) => {
    const label = dim.replace(/_/g, " ");
    const score = scores[dim] ?? "—";
    const note = notes?.[dim] || "";
    return `
          <div class="dimension-row">
            <dt>${escapeHtml(label)} <span class="score-badge">${escapeHtml(score)}/10</span></dt>
            ${note ? `<dd>${escapeHtml(note)}</dd>` : ""}
          </div>
        `;
  }).join("")}
    </dl>
  `;
}

function renderCritiqueRankings(critique, winnerTitle) {
  const ranked = critique?.ranked || [];
  if (!ranked.length) return '<p class="muted">No rankings yet.</p>';
  return `
    <div class="critique-rankings-wrap">
      ${ranked.map((row, index) => {
    const isWinner = isWinnerTitle(row.title, winnerTitle);
    const overall = row.overall_score ?? row.score ?? "—";
    return `
          <details class="critique-entry ${isWinner ? "critique-entry-winner" : ""}" ${isWinner ? "open" : ""}>
            <summary>
              <span class="critique-rank">#${index + 1}</span>
              <strong>${escapeHtml(row.title || "Concept")}</strong>
              <span class="score-badge">${escapeHtml(overall)}/10</span>
              ${isWinner ? '<span class="winner-badge">Winner</span>' : ""}
            </summary>
            ${renderDimensionScores(row.scores, row.dimension_notes)}
            ${row.reject_reason ? `<p class="reject-note"><strong>Not chosen:</strong> ${escapeHtml(row.reject_reason)}</p>` : ""}
            ${row.improve_notes ? `<p class="improve-note"><strong>Could improve:</strong> ${escapeHtml(row.improve_notes)}</p>` : ""}
          </details>
        `;
  }).join("")}
    </div>
  `;
}

function renderPipelineSummary(seed, winner, polished, critique) {
  const winnerTitle = winner?.title || critique?.winner_title || "";
  const finalTitle = polished?.creative_title || polished?.topic || "";
  const hasWinner = Boolean(winnerTitle);
  const hasFinal = Boolean(finalTitle && (polished?.hook || polished?.topic));

  return `
    <div class="pipeline-summary" aria-label="How we got here">
      <div class="pipeline-chip">
        <span class="pipeline-chip-label">1 · Seed</span>
        <span class="pipeline-chip-value">${escapeHtml(truncateText(seed, 120) || "—")}</span>
      </div>
      <span class="pipeline-arrow" aria-hidden="true">→</span>
      <div class="pipeline-chip ${hasWinner ? "pipeline-chip-active" : "pipeline-chip-empty"}">
        <span class="pipeline-chip-label">2 · Chosen concept</span>
        <span class="pipeline-chip-value">${escapeHtml(winnerTitle || "Not picked yet")}</span>
      </div>
      <span class="pipeline-arrow" aria-hidden="true">→</span>
      <div class="pipeline-chip ${hasFinal ? "pipeline-chip-active" : "pipeline-chip-empty"}">
        <span class="pipeline-chip-label">3 · Polished brief</span>
        <span class="pipeline-chip-value">${escapeHtml(finalTitle || "Not polished yet")}</span>
      </div>
    </div>
  `;
}

function renderWinnerSpotlight(winner, critique) {
  if (!winner?.title && !critique?.winner_title) return "";
  const title = winner?.title || critique?.winner_title || "Chosen concept";
  const rationale = critique?.winner_rationale || "";
  const polishNotes = critique?.polish_directives || critique?.winner_improvements || "";
  const runnerUp = critique?.runner_up_title || "";
  const runnerGap = critique?.runner_up_gap || "";
  const captionArc = (winner?.caption_arc || []).join(" → ");

  return `
    <div class="winner-spotlight" id="winner-spotlight">
      <div class="winner-spotlight-header">
        <span class="winner-spotlight-label">Chosen for polish &amp; anchor</span>
        <h4 class="winner-spotlight-title">${escapeHtml(title)}</h4>
      </div>
      <div class="winner-spotlight-body">
        ${winner?.hook ? `<p><strong>Hook:</strong> ${escapeHtml(winner.hook)}</p>` : ""}
        ${winner?.scroll_stop_moment ? `<p><strong>Scroll-stop:</strong> ${escapeHtml(winner.scroll_stop_moment)}</p>` : ""}
        ${winner?.strategic_rationale ? `<p><strong>Strategy:</strong> ${escapeHtml(winner.strategic_rationale)}</p>` : ""}
        ${winner?.visual_gag ? `<p><strong>Visual:</strong> ${escapeHtml(winner.visual_gag)}</p>` : ""}
        ${captionArc ? `<p><strong>Caption arc:</strong> ${escapeHtml(captionArc)}</p>` : ""}
        ${rationale ? `<div class="winner-rationale"><strong>Why it won:</strong><p>${escapeHtml(rationale)}</p></div>` : ""}
        ${runnerUp && runnerGap ? `<p class="runner-up-note"><strong>Beat runner-up "${escapeHtml(runnerUp)}":</strong> ${escapeHtml(runnerGap)}</p>` : ""}
        ${polishNotes ? `<p class="polish-directives"><strong>Polish notes:</strong> ${escapeHtml(polishNotes)}</p>` : ""}
      </div>
      <a href="#concept-card-0" class="winner-jump-link" data-jump-winner>Jump to concept in brainstorm ↓</a>
    </div>
  `;
}

function findWinnerCardIndex(concepts, winnerTitle) {
  const idx = concepts.findIndex((c) => isWinnerTitle(c.title, winnerTitle));
  return idx >= 0 ? idx : 0;
}

function renderPolishFields(plan, polished, sourceTitle) {
  const p = polished || {};
  const structure = (p.caption_structure || []).join("\n");
  const source = sourceTitle || p.source_concept_title || "";
  return `
    ${source ? `<p class="polish-source-line">Polishing brainstorm concept: <strong>${escapeHtml(source)}</strong></p>` : ""}
    <div class="idea-edit-grid">
      <label>Creative title
        <input type="text" id="tl-edit-title" value="${escapeHtml(p.creative_title || plan?.topic || "")}">
      </label>
      <label>Hook
        <input type="text" id="tl-edit-hook" value="${escapeHtml(p.hook || plan?.hook || "")}">
      </label>
      <label>Angle
        <input type="text" id="tl-edit-angle" value="${escapeHtml(p.angle || plan?.angle || "")}">
      </label>
      <label>Topic
        <input type="text" id="tl-edit-topic" value="${escapeHtml(p.topic || plan?.topic || "")}">
      </label>
      <label>Visual concept
        <textarea id="tl-edit-visual" rows="3">${escapeHtml(p.visual_concept || plan?.visual_style || "")}</textarea>
      </label>
      <label>Image prompt (English)
        <textarea id="tl-edit-image-prompt" rows="4">${escapeHtml(p.image_prompt_en || plan?.image_prompt_en || "")}</textarea>
      </label>
      <label>Caption structure (one beat per line)
        <textarea id="tl-edit-caption-structure" rows="4">${escapeHtml(structure)}</textarea>
      </label>
    </div>
  `;
}

function stepRegenButton(step, label) {
  return `<button type="button" class="btn btn-sm step-regen-btn" data-regen-from="${step}">${label}</button>`;
}

function renderTimeline(activeStep) {
  const mount = document.getElementById("timeline-mount");
  if (!mount) return;

  const seed = ideaState.seed || readSeedFromForm();
  const concepts = ideaState.diverge_candidates || [];
  const winnerTitle = ideaState.winner_title || ideaState.critique?.winner_title || "";
  const winner = getWinnerConcept();
  const plan = ideaState.plan || currentPlan;
  const polished = ideaState.polished_concept || {};
  const anchor = ideaState.anchor || {};
  const critique = ideaState.critique || {};
  const hasConcepts = concepts.length > 0;
  const hasCritique = Boolean(critique.ranked?.length || critique.winner_title);
  const hasPolish = Boolean(polished.hook || polished.topic || plan?.topic);
  const hasAnchor = Boolean(anchor.passed !== undefined);
  const dimLosers = hasCritique && Boolean(winnerTitle);
  const winnerIdx = findWinnerCardIndex(concepts, winnerTitle);
  const spotlight = hasCritique ? renderWinnerSpotlight(winner, critique) : "";

  mount.innerHTML = `
    ${renderPipelineSummary(seed, winner, polished, critique)}
    <div class="timeline-track">
      <article class="timeline-step" data-step="seed">
        <div class="timeline-step-marker"><span class="step-num">1</span></div>
        <div class="timeline-step-body card-inner">
          <header class="timeline-step-head">
            <h3>${STEP_LABELS.seed}</h3>
            ${stepRegenButton("diverge", "Re-run from here")}
          </header>
          <label>Your seed (edit to change intent)
            <textarea id="timeline-seed-input" rows="3">${escapeHtml(seed)}</textarea>
          </label>
        </div>
      </article>

      <article class="timeline-step" data-step="diverge">
        <div class="timeline-step-marker"><span class="step-num">2</span></div>
        <div class="timeline-step-body card-inner">
          <header class="timeline-step-head">
            <h3>${STEP_LABELS.diverge}</h3>
            ${hasConcepts ? stepRegenButton("diverge", "Regenerate concepts") : ""}
          </header>
          ${hasConcepts
    ? `<div class="concept-grid">${concepts.map((c, i) => renderConceptCard(c, i, winnerTitle, dimLosers)).join("")}</div>`
    : '<p class="muted step-placeholder">Waiting for brainstorm…</p>'}
          ${hasConcepts ? `<div class="step-actions">${stepRegenButton("critique", "Continue → critique")}</div>` : ""}
        </div>
      </article>

      <article class="timeline-step" data-step="critique">
        <div class="timeline-step-marker"><span class="step-num">3</span></div>
        <div class="timeline-step-body card-inner">
          <header class="timeline-step-head">
            <h3>${STEP_LABELS.critique}</h3>
            ${hasCritique ? stepRegenButton("critique", "Regenerate critique") : ""}
          </header>
          ${hasCritique
    ? `
            ${spotlight}
            ${renderCritiqueRankings(critique, winnerTitle)}
            <p class="hint">Change winner by selecting a concept above, then regenerate critique or continue to polish.</p>
            <div class="step-actions">${stepRegenButton("polish", "Continue → polish")}</div>
          `
    : '<p class="muted step-placeholder">Waiting for critique…</p>'}
        </div>
      </article>

      <article class="timeline-step" data-step="polish">
        <div class="timeline-step-marker"><span class="step-num">4</span></div>
        <div class="timeline-step-body card-inner">
          <header class="timeline-step-head">
            <h3>${STEP_LABELS.polish}</h3>
            ${hasPolish ? stepRegenButton("polish", "Regenerate polish") : ""}
          </header>
          ${hasPolish
    ? `${spotlight}${renderPolishFields(plan, polished, winnerTitle)}<div class="step-actions">${stepRegenButton("anchor", "Continue → anchor")}</div>`
    : hasCritique
      ? `${spotlight}<p class="muted step-placeholder">Waiting for polish…</p>`
      : '<p class="muted step-placeholder">Waiting for polish…</p>'}
        </div>
      </article>

      <article class="timeline-step" data-step="anchor">
        <div class="timeline-step-marker"><span class="step-num">5</span></div>
        <div class="timeline-step-body card-inner">
          <header class="timeline-step-head">
            <h3>${STEP_LABELS.anchor}</h3>
            ${hasAnchor ? stepRegenButton("anchor", "Re-check intent") : ""}
          </header>
          ${hasAnchor
    ? `
            ${spotlight}
            <p class="anchor-result ${anchor.passed ? "anchor-pass" : "anchor-fail"}">
              ${anchor.passed ? "✓ Intent preserved" : "⚠ Intent drift — auto-repolished"}
            </p>
            ${anchor.notes ? `<p class="anchor-notes">${escapeHtml(anchor.notes)}</p>` : ""}
            ${anchor.missing_facts?.length
      ? `<p class="anchor-missing"><strong>Missing facts:</strong> ${escapeHtml(anchor.missing_facts.join(", "))}</p>`
      : ""}
          `
    : hasPolish
      ? `${spotlight}<p class="muted step-placeholder">Waiting for intent check…</p>`
      : '<p class="muted step-placeholder">Waiting for intent check…</p>'}
        </div>
      </article>
    </div>
  `;

  setTimelineStepStatus(activeStep || "seed");
  bindTimelineEvents(winnerIdx);
  updateTimelineFooter();
}

function scrollToWinnerCard(index) {
  const card = document.getElementById(`concept-card-${index}`);
  if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
}

function updateTimelineFooter() {
  const footer = document.getElementById("timeline-footer");
  if (!footer) return;
  footer.hidden = !ideaState.plan && !currentPlan;
}

function bindTimelineEvents(winnerIdx) {
  const seedInput = document.getElementById("timeline-seed-input");
  if (seedInput) {
    seedInput.addEventListener("input", () => {
      ideaState.seed = seedInput.value.trim();
      const formSeed = document.querySelector('#generate-form [name="topic_hint"]');
      if (formSeed) formSeed.value = seedInput.value;
    });
  }

  document.querySelectorAll("[data-jump-winner]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      scrollToWinnerCard(winnerIdx);
    });
    link.setAttribute("href", `#concept-card-${winnerIdx}`);
  });

  document.querySelectorAll(".step-regen-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const fromStep = btn.dataset.regenFrom;
      if (fromStep) runIdeaStep(fromStep);
    });
  });

  const polishIds = [
    "tl-edit-title", "tl-edit-hook", "tl-edit-angle", "tl-edit-topic",
    "tl-edit-visual", "tl-edit-image-prompt", "tl-edit-caption-structure",
  ];
  polishIds.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("input", syncPlanFromEditors);
  });
}

function syncPlanFromEditors() {
  const state = readStateFromDom();
  ideaState.polished_concept = state.polished_concept;
  const plan = {
    ...(ideaState.plan || currentPlan || {}),
    hook: state.polished_concept.hook,
    angle: state.polished_concept.angle,
    topic: state.polished_concept.topic,
    visual_style: state.polished_concept.visual_concept,
    image_prompt_en: state.polished_concept.image_prompt_en,
  };
  ideaState.plan = plan;
  currentPlan = plan;
  currentIdeaBrief = buildBriefFromState(state);
  syncHiddenInputs(plan, currentIdeaBrief);
}

function buildBriefFromState(state) {
  return {
    seed: state.seed,
    audience: state.audience,
    preset: state.preset,
    diverge_candidates: state.diverge_candidates,
    critique: state.critique,
    winner: state.winner,
    polished_concept: state.polished_concept,
    anchor: state.anchor,
  };
}

function applyDonePayload(payload) {
  if (payload.plan) {
    currentPlan = payload.plan;
    ideaState.plan = payload.plan;
  }
  if (payload.idea_brief) {
    currentIdeaBrief = payload.idea_brief;
    ideaState = { ...ideaState, ...payload.idea_brief };
  }
  syncHiddenInputs(currentPlan, currentIdeaBrief);
  renderTimeline("anchor");
  setTimelineStepStatus("complete");
}

async function streamSse(url, formData, steps, onDone, onEvent) {
  const response = await fetch(url, { method: "POST", body: formData });
  if (!response.ok) throw new Error(`Server error (${response.status})`);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payload = JSON.parse(line.slice(6));
      if (payload.type === "progress") {
        if (onEvent) onEvent(payload);
        else updateProgressUi(payload.step, payload.detail, steps);
      } else if (payload.type === "step_done") {
        if (onEvent) onEvent(payload);
      } else if (payload.type === "done") {
        await onDone(payload);
        return;
      } else if (payload.type === "error") {
        throw new Error(payload.message || "Something went wrong");
      }
    }
  }
}

function buildIdeaFormData(fromStep) {
  const form = document.getElementById("generate-form");
  const formData = new FormData(form);
  const state = readStateFromDom();
  if (fromStep) formData.set("from_step", fromStep);
  formData.set("idea_state", JSON.stringify({
    diverge_candidates: state.diverge_candidates,
    critique: state.critique,
    winner: state.winner,
    winner_title: state.winner_title,
    polished_concept: state.polished_concept,
    anchor: state.anchor,
  }));
  const seedEl = document.getElementById("timeline-seed-input");
  if (seedEl) formData.set("topic_hint", seedEl.value.trim());
  return formData;
}

async function runIdeaPipeline(url, fromStep) {
  if (timelineRunning) return;
  timelineRunning = true;

  const form = document.getElementById("generate-form");
  const format = form?.querySelector('input[name="format"]:checked')?.value || "post";
  const elevateBtn = document.getElementById("elevate-btn");
  if (elevateBtn) elevateBtn.disabled = true;

  showTimeline();
  showTimelineStatus(fromStep ? `Running from ${fromStep}…` : "Elevating idea…");

  const formData = buildIdeaFormData(fromStep);

  try {
    await streamSse(url, formData, ELEVATE_STEPS, async (payload) => {
      applyDonePayload(payload);
      hideTimelineStatus();
    }, (payload) => {
      if (payload.type === "progress") {
        showTimelineStatus(payload.detail);
        const map = { load: "seed", diverge: "diverge", critique: "critique", polish: "polish", anchor: "anchor" };
        setTimelineStepStatus(map[payload.step] || payload.step);
      }
      if (payload.type === "step_done") {
        mergeStepDone(payload.step, payload);
        const map = { diverge: "diverge", critique: "critique", polish: "polish", anchor: "anchor" };
        renderTimeline(map[payload.step] || payload.step);
        showTimelineStatus(`Done: ${STEP_LABELS[map[payload.step]] || payload.step}`);
        if (payload.step === "critique") {
          const idx = findWinnerCardIndex(
            ideaState.diverge_candidates || [],
            ideaState.winner_title || ideaState.critique?.winner_title,
          );
          scrollToWinnerCard(idx);
        }
      }
    });
  } catch (err) {
    showTimelineStatus(`Error: ${err.message}`);
    alert(err.message || "Something went wrong");
  } finally {
    timelineRunning = false;
    hideTimelineStatus();
    if (elevateBtn) elevateBtn.disabled = false;
  }
}

function runIdeaStep(fromStep) {
  runIdeaPipeline("/api/idea-step", fromStep);
}

function initElevateButton() {
  const btn = document.getElementById("elevate-btn");
  if (!btn) return;

  btn.addEventListener("click", () => {
    ideaState = emptyIdeaState();
    ideaState.seed = readSeedFromForm();
    const meta = readFormMeta();
    ideaState.audience = meta.audience;
    ideaState.preset = meta.preset;
    currentPlan = null;
    currentIdeaBrief = null;
    renderTimeline("seed");
    runIdeaPipeline("/api/elevate-idea", null);
  });
}

function initTimelineGenerateButton() {
  const btn = document.getElementById("timeline-generate-btn");
  const submitBtn = document.getElementById("generate-submit");
  if (!btn || !submitBtn) return;
  btn.addEventListener("click", () => submitBtn.click());
}

function initGenerateForm() {
  const form = document.getElementById("generate-form");
  if (!form) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    syncPlanFromEditors();

    const format = form.querySelector('input[name="format"]:checked')?.value || "post";
    const formPanel = document.getElementById("generate-form-panel");
    const timeline = document.getElementById("idea-timeline");
    if (formPanel) formPanel.hidden = true;
    if (timeline) timeline.hidden = true;
    showProgressPanel(format, "Generating full post…", STEP_ORDER);

    const submitBtn = document.getElementById("generate-submit");
    if (submitBtn) submitBtn.disabled = true;

    try {
      await streamSse("/api/generate", new FormData(form), STEP_ORDER, async (payload) => {
        window.location.href = `/posts/${payload.post_id}`;
      });
    } catch (err) {
      showError(err.message || "Something went wrong");
      if (formPanel) formPanel.hidden = false;
      if (timeline && currentPlan) timeline.hidden = false;
      if (submitBtn) submitBtn.disabled = false;
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initBrandPanels();
  initElevateButton();
  initTimelineGenerateButton();
  initGenerateForm();
});
