const els = {
  body: document.body,
  heroCopy: document.getElementById("hero-copy"),
  modeChip: document.getElementById("mode-chip"),
  phaseChip: document.getElementById("phase-chip"),
  targetKicker: document.getElementById("target-kicker"),
  targetFocus: document.getElementById("target-focus"),
  targetLine: document.getElementById("target-line"),
  displayPanel: document.querySelector(".display-panel"),
  displayValue: document.getElementById("display-value"),
  displayHint: document.getElementById("display-hint"),
  playersTableBoard: document.getElementById("players-table-board"),
  doubletapBoard: document.getElementById("doubletap-board"),
  metricHeading: document.getElementById("metric-heading"),
  detailHeading: document.getElementById("detail-heading"),
  scoreBoard: document.getElementById("scoreboard"),
  scoreHeadline: document.getElementById("score-headline"),
  scoreSubline: document.getElementById("score-subline"),
  advanceButton: document.getElementById("advance-button"),
  resetButton: document.getElementById("reset-button"),
  fullscreenButton: document.getElementById("fullscreen-button"),
  menuToggle: document.getElementById("menu-toggle"),
  closeMenu: document.getElementById("close-menu"),
  modePanel: document.getElementById("mode-panel"),
  modeGrid: document.getElementById("mode-grid"),
  players: {
    J1: {
      card: document.getElementById("player-j1"),
      metricValue: document.getElementById("j1-metric-value"),
      detailValue: document.getElementById("j1-detail-value"),
      status: document.getElementById("j1-status"),
      tapProgress: document.getElementById("j1-tap-progress"),
      tap1: document.getElementById("j1-tap-1"),
      tap2: document.getElementById("j1-tap-2"),
    },
    J2: {
      card: document.getElementById("player-j2"),
      metricValue: document.getElementById("j2-metric-value"),
      detailValue: document.getElementById("j2-detail-value"),
      status: document.getElementById("j2-status"),
      tapProgress: document.getElementById("j2-tap-progress"),
      tap1: document.getElementById("j2-tap-1"),
      tap2: document.getElementById("j2-tap-2"),
    },
  },
  impactPlayers: {
    J1: {
      card: document.getElementById("impact-card-j1"),
      status: document.getElementById("j1-impact-status"),
      step1: document.getElementById("j1-impact-step-1"),
      step2: document.getElementById("j1-impact-step-2"),
      metricLabel: document.getElementById("j1-impact-metric-label"),
      metricValue: document.getElementById("j1-impact-metric-value"),
      detailLabel: document.getElementById("j1-impact-detail-label"),
      detailValue: document.getElementById("j1-impact-detail-value"),
    },
    J2: {
      card: document.getElementById("impact-card-j2"),
      status: document.getElementById("j2-impact-status"),
      step1: document.getElementById("j2-impact-step-1"),
      step2: document.getElementById("j2-impact-step-2"),
      metricLabel: document.getElementById("j2-impact-metric-label"),
      metricValue: document.getElementById("j2-impact-metric-value"),
      detailLabel: document.getElementById("j2-impact-detail-label"),
      detailValue: document.getElementById("j2-impact-detail-value"),
    },
  },
};

let currentState = null;
let currentStateReceivedAt = 0;
let animationFrame = null;
let modeButtons = [];
let eventSource = null;

function openMenu() {
  els.body.classList.add("menu-open");
  els.modePanel.setAttribute("aria-hidden", "false");
  els.menuToggle.setAttribute("aria-expanded", "true");
}

function closeMenu() {
  els.body.classList.remove("menu-open");
  els.modePanel.setAttribute("aria-hidden", "true");
  els.menuToggle.setAttribute("aria-expanded", "false");
}

async function enterFullscreen() {
  if (document.fullscreenElement) {
    return;
  }
  try {
    await document.documentElement.requestFullscreen();
  } catch (error) {
    console.debug(error);
  }
}

async function postAction(action, extra = {}) {
  const response = await fetch("/api/game", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ action, ...extra }),
  });

  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || "Action impossible.");
  }

  applyState(payload.state);
}

function buildModeGrid(modes) {
  if (modeButtons.length > 0) {
    return;
  }

  modes.forEach((mode) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mode-card";
    button.dataset.mode = mode.key;
    button.innerHTML = `
      <small>${mode.kind === "reflex" ? "Reflexe" : mode.kind === "doubletap" ? "Rythme" : "Precision"}</small>
      <strong>${mode.name}</strong>
      <p>${mode.description}</p>
      <span>${mode.hero}</span>
    `;

    button.addEventListener("click", async () => {
      try {
        await postAction("select_mode", { mode: mode.key });
        closeMenu();
      } catch (error) {
        window.alert(error.message);
      }
    });

    els.modeGrid.appendChild(button);
    modeButtons.push(button);
  });
}

function updateModeSelection(modeKey) {
  modeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === modeKey);
  });
}

function updatePlayerCard(playerKey, player) {
  const refs = els.players[playerKey];
  const impactRefs = els.impactPlayers[playerKey];
  const isDoubletap = currentState?.modeInfo?.kind === "doubletap";
  const resultsVisible = ["idle", "round_over", "between_rounds", "match_over"].includes(
    currentState?.phase || "",
  );
  const tapCount = player.tapCount || 0;
  let impactState = "waiting";
  let impactOutcome = "";

  if (resultsVisible) {
    impactState = "result";
    if (player.status === "Parfait") {
      impactOutcome = "perfect";
    } else if (player.status === "Trop court") {
      impactOutcome = "short";
    } else if (player.status === "Trop long") {
      impactOutcome = "long";
    }
  } else if (tapCount >= 2) {
    impactState = "locked";
  } else if (tapCount === 1) {
    impactState = "running";
  }

  refs.metricValue.textContent = player.metricValue;
  refs.detailValue.textContent = player.detailValue;
  const showInlineStatus = !(
    player.detailLabel === "Statut" && player.detailValue === player.status
  );
  refs.status.textContent = showInlineStatus ? player.status : "";
  refs.tapProgress.hidden = !isDoubletap;
  refs.tap1.classList.toggle("active", isDoubletap && tapCount >= 1);
  refs.tap2.classList.toggle("active", isDoubletap && tapCount >= 2);
  refs.card.classList.toggle("winner", Boolean(player.winner));

  impactRefs.status.textContent = player.status;
  impactRefs.metricLabel.textContent = player.metricLabel;
  impactRefs.metricValue.textContent = player.metricValue;
  impactRefs.detailLabel.textContent = player.detailLabel;
  impactRefs.detailValue.textContent = player.detailValue;
  impactRefs.card.dataset.taps = String(tapCount);
  impactRefs.card.dataset.state = impactState;
  impactRefs.card.dataset.outcome = impactOutcome;
  impactRefs.card.classList.toggle("winner", Boolean(player.winner));
  impactRefs.step1.classList.toggle("done", tapCount >= 1);
  impactRefs.step2.classList.toggle("done", tapCount >= 2);
  impactRefs.step1.classList.toggle("current", isDoubletap && !resultsVisible && tapCount === 0);
  impactRefs.step2.classList.toggle("current", isDoubletap && !resultsVisible && tapCount === 1);
}

function updateScoreboard(scoreboard) {
  if (!els.scoreBoard || !els.scoreHeadline || !els.scoreSubline) {
    return;
  }

  els.scoreHeadline.textContent = scoreboard.headline;
  els.scoreSubline.textContent = scoreboard.subline;
  els.scoreBoard.classList.toggle("masked", !scoreboard.visible);
}

function serverNowSeconds() {
  if (!currentState) {
    return null;
  }
  const drift = (performance.now() - currentStateReceivedAt) / 1000;
  return currentState.timing.serverTime + drift;
}

function liveDisplayValue() {
  if (!currentState) {
    return currentState?.display?.value || "--";
  }

  const { display, timing, phase } = currentState;
  if (!display.dynamicTimer || phase !== "live" || !timing.roundStartedAt) {
    return display.value;
  }

  const now = serverNowSeconds();
  const elapsed = Math.max(0, now - timing.roundStartedAt);
  const hideAfter = timing.hideAfter;

  if (hideAfter !== null && hideAfter !== undefined && elapsed >= hideAfter) {
    return timing.blackout ? "" : "...";
  }

  return elapsed.toFixed(3);
}

function liveTargetFocus() {
  return currentState?.display?.targetValue || "--";
}

function liveTargetLine() {
  return currentState?.display?.targetText || "";
}

function animateStage() {
  if (!currentState) {
    animationFrame = window.requestAnimationFrame(animateStage);
    return;
  }

  els.displayValue.textContent = liveDisplayValue();
  els.targetFocus.textContent = liveTargetFocus();
  els.targetLine.textContent = liveTargetLine();
  animationFrame = window.requestAnimationFrame(animateStage);
}

function applyState(state) {
  currentState = state;
  currentStateReceivedAt = performance.now();

  buildModeGrid(state.modes);
  updateModeSelection(state.mode);

  els.body.dataset.phase = state.phase;
  els.body.dataset.theme = state.modeInfo.theme || state.modeInfo.key;
  els.body.dataset.modeKind = state.modeInfo.kind;
  els.heroCopy.textContent = state.modeInfo.hero;
  els.modeChip.textContent = state.modeInfo.name;
  els.phaseChip.textContent = state.phaseLabel;
  const isDoubletap = state.modeInfo.kind === "doubletap";
  els.playersTableBoard.hidden = isDoubletap;
  els.doubletapBoard.hidden = !isDoubletap;
  els.targetKicker.textContent = state.display.targetLabel;
  els.targetFocus.textContent = state.display.targetValue;
  const targetLine = state.display.targetText?.trim() || "";
  const showTargetLine = targetLine.length > 0 && state.modeInfo.kind !== "reflex";
  els.targetLine.textContent = targetLine;
  els.targetLine.hidden = !showTargetLine;
  els.displayValue.textContent = state.display.value;
  els.displayValue.dataset.style = state.display.style;
  els.displayPanel.dataset.style = state.display.style;
  const displayHint = state.display.hint?.trim() || "";
  const showHint = displayHint.length > 0
    && state.display.style !== "reveal"
    && !(state.display.style === "live" && state.modeInfo.kind !== "doubletap");

  els.displayHint.textContent = displayHint;
  els.displayHint.hidden = !showHint;
  els.advanceButton.textContent = state.controls.advanceLabel;
  els.advanceButton.disabled = !state.controls.canAdvance;
  els.metricHeading.textContent = state.players.J1.metricLabel;
  els.detailHeading.textContent = state.players.J1.detailLabel;

  updateScoreboard(state.scoreboard);
  updatePlayerCard("J1", state.players.J1);
  updatePlayerCard("J2", state.players.J2);

  if (state.phase === "live") {
    closeMenu();
  }
}

async function refreshState() {
  const response = await fetch("/api/state");
  const payload = await response.json();
  applyState(payload);
}

function connectStream() {
  if (eventSource) {
    eventSource.close();
  }

  eventSource = new EventSource("/api/stream");

  eventSource.onmessage = (event) => {
    try {
      applyState(JSON.parse(event.data));
    } catch (error) {
      console.error(error);
    }
  };

  eventSource.onerror = () => {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }

    window.setTimeout(async () => {
      try {
        await refreshState();
      } catch (error) {
        console.error(error);
      }
      connectStream();
    }, 1200);
  };
}

function bindControls() {
  els.advanceButton.addEventListener("click", async () => {
    try {
      await enterFullscreen();
      await postAction("advance");
    } catch (error) {
      window.alert(error.message);
    }
  });

  els.resetButton.addEventListener("click", async () => {
    try {
      await postAction("reset");
    } catch (error) {
      window.alert(error.message);
    }
  });

  els.fullscreenButton.addEventListener("click", async () => {
    await enterFullscreen();
  });

  els.menuToggle.addEventListener("click", () => {
    if (els.body.classList.contains("menu-open")) {
      closeMenu();
    } else {
      openMenu();
    }
  });

  els.closeMenu.addEventListener("click", closeMenu);

  document.addEventListener("keydown", async (event) => {
    try {
      if (event.key === "Escape") {
        closeMenu();
        return;
      }

      if (event.key.toLowerCase() === "m") {
        if (els.body.classList.contains("menu-open")) {
          closeMenu();
        } else {
          openMenu();
        }
        return;
      }

      if (event.key.toLowerCase() === "f") {
        await enterFullscreen();
        return;
      }

      if (event.key.toLowerCase() === "r") {
        await postAction("reset");
        return;
      }

      if (
        (event.key === " " || event.key === "Enter") &&
        currentState?.controls.canAdvance
      ) {
        event.preventDefault();
        await enterFullscreen();
        await postAction("advance");
        return;
      }

      if (!currentState?.connection.connected) {
        if (event.key.toLowerCase() === "a") {
          await postAction("simulate_press", { player: "J1" });
        }
        if (event.key.toLowerCase() === "l") {
          await postAction("simulate_press", { player: "J2" });
        }
      }
    } catch (error) {
      window.alert(error.message);
    }
  });
}

async function start() {
  bindControls();
  await refreshState();
  connectStream();
  animationFrame = window.requestAnimationFrame(animateStage);
}

start();
