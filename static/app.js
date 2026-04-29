const els = {
  body: document.body,
  heroCopy: document.getElementById("hero-copy"),
  modeChip: document.getElementById("mode-chip"),
  phaseChip: document.getElementById("phase-chip"),
  targetLine: document.getElementById("target-line"),
  displayValue: document.getElementById("display-value"),
  displayHint: document.getElementById("display-hint"),
  message: document.getElementById("message"),
  scoreBoard: document.getElementById("scoreboard"),
  scoreHeadline: document.getElementById("score-headline"),
  scoreSubline: document.getElementById("score-subline"),
  roundNumber: document.getElementById("round-number"),
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
      metricLabel: document.getElementById("j1-metric-label"),
      metricValue: document.getElementById("j1-metric-value"),
      detailLabel: document.getElementById("j1-detail-label"),
      detailValue: document.getElementById("j1-detail-value"),
      status: document.getElementById("j1-status"),
    },
    J2: {
      card: document.getElementById("player-j2"),
      metricLabel: document.getElementById("j2-metric-label"),
      metricValue: document.getElementById("j2-metric-value"),
      detailLabel: document.getElementById("j2-detail-label"),
      detailValue: document.getElementById("j2-detail-value"),
      status: document.getElementById("j2-status"),
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
}

function closeMenu() {
  els.body.classList.remove("menu-open");
  els.modePanel.setAttribute("aria-hidden", "true");
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
  refs.metricLabel.textContent = player.metricLabel;
  refs.metricValue.textContent = player.metricValue;
  refs.detailLabel.textContent = player.detailLabel;
  refs.detailValue.textContent = player.detailValue;
  refs.status.textContent = player.status;
  refs.card.classList.toggle("winner", Boolean(player.winner));
}

function updateScoreboard(scoreboard) {
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

function liveTargetLine() {
  if (!currentState) {
    return "";
  }

  const { display, timing, phase } = currentState;
  if (!display.dynamicTimer || phase !== "live" || !timing.roundStartedAt) {
    return display.targetText;
  }

  const now = serverNowSeconds();
  const elapsed = Math.max(0, now - timing.roundStartedAt);
  const hideAfter = timing.hideAfter;

  if (hideAfter !== null && hideAfter !== undefined && elapsed >= hideAfter) {
    if (timing.kind === "doubletap") {
      return "Intervalle memorise";
    }
    return "Cible memorisee";
  }

  return display.targetText;
}

function animateStage() {
  if (!currentState) {
    animationFrame = window.requestAnimationFrame(animateStage);
    return;
  }

  els.displayValue.textContent = liveDisplayValue();
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
  els.heroCopy.textContent = state.modeInfo.hero;
  els.modeChip.textContent = state.modeInfo.name;
  els.phaseChip.textContent = state.phaseLabel;
  els.targetLine.textContent = state.display.targetText;
  els.displayValue.textContent = state.display.value;
  els.displayValue.dataset.style = state.display.style;
  els.displayHint.textContent = state.display.hint;
  els.message.textContent = state.message;
  els.roundNumber.textContent = String(state.round || 0);
  els.advanceButton.textContent = state.controls.advanceLabel;
  els.advanceButton.disabled = !state.controls.canAdvance;

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
