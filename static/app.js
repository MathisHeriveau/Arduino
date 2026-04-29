/**
 * Jeu de Buzzer – Frontend
 *
 * Connexion temps réel via Server-Sent Events (/events).
 * Le chrono est animé côté client à partir du timestamp "go_ts" envoyé par le serveur.
 * Anti-triche : les temps ne sont pas révélés pendant la phase active/partial.
 *
 * Raccourcis clavier (simulation / sans Arduino) :
 *   Q ou Espace  → Joueur 1
 *   P ou Entrée  → Joueur 2
 */

const App = (() => {
  // ── État local ────────────────────────────────────────────────────────
  let _state = {};          // dernier snapshot reçu du serveur
  let _timerRaf = null;     // requestAnimationFrame handle du chrono
  let _timerStart = null;   // Date.now() correspondant à go_ts

  // ── Références DOM ────────────────────────────────────────────────────
  const $ = id => document.getElementById(id);
  const dom = {
    scoreJ1:     $("score-j1"),
    scoreJ2:     $("score-j2"),
    modeLabel:   $("mode-label"),
    roundIndicator: $("round-indicator"),
    signalRing:  $("signal-ring"),
    signalText:  $("signal-text"),
    timerWrap:   $("timer-wrap"),
    timerBar:    $("timer-bar"),
    timerDisplay:$("timer-display"),
    resultPanel: $("result-panel"),
    winnerCrown: $("winner-crown"),
    resultTimes: $("result-times"),
    modeSelector:$("mode-selector"),
    btnStart:    $("btn-start"),
    btnReset:    $("btn-reset"),
    simNotice:   $("sim-notice"),
    blackout:    $("blackout-overlay"),
  };

  // ── SSE connection ────────────────────────────────────────────────────
  function _connectSSE() {
    const es = new EventSource("/events");
    es.addEventListener("state", e => {
      try { _applyState(JSON.parse(e.data)); }
      catch (_) {}
    });
    es.onerror = () => {
      // Brief pause then reconnect
      es.close();
      setTimeout(_connectSSE, 2000);
    };
  }

  // ── Apply server state snapshot ───────────────────────────────────────
  function _applyState(s) {
    _state = s;
    _renderHeader(s);
    _renderStage(s);
    _renderControls(s);
  }

  // ── Header ────────────────────────────────────────────────────────────
  function _renderHeader(s) {
    dom.scoreJ1.textContent = s.scores?.J1 ?? 0;
    dom.scoreJ2.textContent = s.scores?.J2 ?? 0;

    const meta = s.modes?.[s.mode] ?? {};
    dom.modeLabel.textContent = meta.label ?? s.mode;

    if (s.total_rounds > 1) {
      dom.roundIndicator.textContent = `Manche ${s.round_num} / ${s.total_rounds}`;
    } else {
      dom.roundIndicator.textContent = "";
    }
  }

  // ── Stage ─────────────────────────────────────────────────────────────
  function _renderStage(s) {
    _stopTimer();
    _hideBlackout();

    switch (s.phase) {
      case "idle":
        _setSignal("idle", "—");
        _hideTimer();
        _hideResult();
        break;

      case "countdown":
        _setSignal("countdown", "…");
        _hideTimer();
        _hideResult();
        _startCountdownVisual(s);
        break;

      case "active":
        _onGoSignal(s);
        break;

      case "partial": {
        // One player has finished; don't reveal times yet (anti-cheat)
        const pressed = s.pressed ?? [];
        _setSignal("partial", pressed.length === 2 ? "⏳" : "½");
        if (s.mode !== "ghost" && s.mode !== "blackout") {
          _startLiveTimer(s);
        }
        // Keep blackout up during active+partial
        if (s.mode === "blackout") {
          _showBlackout();
        }
        _hideResult();
        break;
      }

      case "finished":
        _setSignal("finished", "✓");
        _hideTimer();
        if (s.mode === "blackout") _hideBlackout();
        _showResult(s);
        break;

      default:
        break;
    }
  }

  function _onGoSignal(s) {
    _setSignal("go", "GO !");

    if (s.mode === "blackout") {
      _showBlackout();
    }

    if (s.mode !== "ghost" && s.mode !== "blackout") {
      _showTimer();
      _startLiveTimer(s);
    } else {
      _hideTimer();
    }
    _hideResult();
  }

  // ── Signal ring helpers ───────────────────────────────────────────────
  function _setSignal(cls, text) {
    dom.signalRing.className = `signal-ring ${cls}`;
    dom.signalText.textContent = text;
  }

  // ── Countdown visual (pulsing before GO) ─────────────────────────────
  function _startCountdownVisual(s) {
    // We don't show a numeric count; just let the ring pulse.
    // The server holds the true random delay.
  }

  // ── Live timer (client-side RAF loop) ────────────────────────────────
  function _startLiveTimer(s) {
    if (!s.go_ts) return;
    const goMs = s.go_ts * 1000;
    _showTimer();

    function tick() {
      const elapsed = (Date.now() - goMs) / 1000;
      const clamped = Math.max(0, elapsed);
      const pct = Math.min((clamped / 5) * 100, 100);
      dom.timerBar.style.setProperty("--progress", `${pct.toFixed(1)}%`);
      dom.timerDisplay.textContent = `${clamped.toFixed(3)} s`;
      _timerRaf = requestAnimationFrame(tick);
    }
    tick();
  }

  function _stopTimer() {
    if (_timerRaf !== null) {
      cancelAnimationFrame(_timerRaf);
      _timerRaf = null;
    }
  }

  function _showTimer() { dom.timerWrap.classList.remove("hidden"); }
  function _hideTimer() {
    dom.timerWrap.classList.add("hidden");
    dom.timerBar.style.setProperty("--progress", "0%");
  }

  // ── Result panel ──────────────────────────────────────────────────────
  function _showResult(s) {
    const r = s.result;
    if (!r) { _hideResult(); return; }

    const { winner, t1_ms, t2_ms, dnf = [], taps = {} } = r;

    // Crown emoji
    let crown = "";
    if (winner === "tie")       crown = "🤝";
    else if (winner === "J1")   crown = "🏆 Joueur 1";
    else if (winner === "J2")   crown = "🏆 Joueur 2";
    else                        crown = "⏰ Temps écoulé";
    dom.winnerCrown.textContent = crown;

    // Time blocks
    function timeBlock(player, ms, isWinner) {
      const cls = dnf.includes(player)
        ? "dnf"
        : winner === "tie"
          ? "tie"
          : isWinner
            ? `winner-${player.toLowerCase()}`
            : "loser";
      const val = dnf.includes(player)
        ? "DNF"
        : ms !== null
          ? `${(ms / 1000).toFixed(3)} s`
          : "—";
      const label = player === "J1" ? "Joueur 1" : "Joueur 2";

      let tapHtml = "";
      if (s.mode === "double_tap" && taps[player]?.length) {
        tapHtml = taps[player]
          .map((t, i) => `<small>Tap ${i + 1}: ${(t / 1000).toFixed(3)} s</small>`)
          .join("");
      }

      return `
        <div class="result-time-block ${cls}">
          <span class="player-name">${label}</span>
          <span class="time-val">${val}</span>
          ${tapHtml}
        </div>`;
    }

    dom.resultTimes.innerHTML =
      timeBlock("J1", t1_ms, winner === "J1") +
      timeBlock("J2", t2_ms, winner === "J2");

    dom.resultPanel.classList.remove("hidden");
  }

  function _hideResult() {
    dom.resultPanel.classList.add("hidden");
    dom.winnerCrown.textContent = "";
    dom.resultTimes.innerHTML = "";
  }

  // ── Blackout overlay ──────────────────────────────────────────────────
  function _showBlackout() { dom.blackout.classList.remove("hidden"); }
  function _hideBlackout() { dom.blackout.classList.add("hidden"); }

  // ── Controls ──────────────────────────────────────────────────────────
  function _renderControls(s) {
    // Mode selector
    _buildModeSelector(s);

    // Start/reset button states
    const inProgress = ["countdown", "active", "partial"].includes(s.phase);
    dom.btnStart.disabled = inProgress;
    dom.btnReset.disabled = s.phase === "idle";

    // Simulation notice
    if (s.sim) {
      dom.simNotice.classList.remove("hidden");
    } else {
      dom.simNotice.classList.add("hidden");
    }
  }

  function _buildModeSelector(s) {
    const modes = s.modes ?? {};
    const current = s.mode;
    const inProgress = ["countdown", "active", "partial"].includes(s.phase);

    // Only rebuild if mode list changed (avoid flicker)
    const existing = [...dom.modeSelector.querySelectorAll(".mode-btn")]
      .map(b => b.dataset.mode).join(",");
    const incoming = Object.keys(modes).join(",");
    if (existing !== incoming) {
      dom.modeSelector.innerHTML = Object.entries(modes)
        .map(([key, meta]) =>
          `<button class="mode-btn${key === current ? " active" : ""}"
                   data-mode="${key}"
                   title="${meta.desc}"
                   onclick="App.setMode('${key}')"
                   ${inProgress ? "disabled" : ""}>
             ${meta.label}
           </button>`
        ).join("");
    } else {
      // Just update active state
      dom.modeSelector.querySelectorAll(".mode-btn").forEach(b => {
        b.classList.toggle("active", b.dataset.mode === current);
        b.disabled = inProgress;
      });
    }
  }

  // ── Public API ─────────────────────────────────────────────────────────
  function startGame() {
    const mode = _state.mode ?? "reflex";
    fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    }).catch(console.error);
  }

  function reset() {
    fetch("/api/reset", { method: "POST" }).catch(console.error);
  }

  function setMode(mode) {
    fetch("/api/set_mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    }).catch(console.error);
  }

  function simulatePress(player) {
    fetch("/api/simulate_press", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player }),
    }).catch(console.error);
  }

  // ── Keyboard fallback ─────────────────────────────────────────────────
  document.addEventListener("keydown", e => {
    if (!_state.sim) return;
    if (e.repeat) return;
    const active = ["active", "partial"].includes(_state.phase);
    if (!active) return;

    if (e.key === "q" || e.key === "Q" || e.key === " ") {
      e.preventDefault();
      simulatePress("J1");
    } else if (e.key === "p" || e.key === "P" || e.key === "Enter") {
      e.preventDefault();
      simulatePress("J2");
    }
  });

  // ── Init ──────────────────────────────────────────────────────────────
  _connectSSE();

  return { startGame, reset, setMode, simulatePress };
})();
