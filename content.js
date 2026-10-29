'use strict';
(() => {
  const VERSION = '1.3.2';
  const MIN = 60000;
  // Anchura (px del widget) que pierde la pastilla al plegar el reloj:
  // 54 del hueco del tiempo + 10 de un separador. En px físicos coincide.
  const PILL_DELTA = 64;
  const R_PILL = 15.5, C_PILL = 2 * Math.PI * R_PILL;
  const R_DIAL = 96, C_DIAL = 2 * Math.PI * R_DIAL;
  // Paleta del asistente de encuestas
  const COLORS = { focus: '#ff4f8b', short: '#10b981', long: '#4696ff' };
  const LABELS = { focus: 'Enfoque', short: 'Descanso corto', long: 'Descanso largo' };

  const ICONS = {
    pause: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="4" width="5" height="16" rx="2"/><rect x="14" y="4" width="5" height="16" rx="2"/></svg>',
    play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.8v14.4c0 .9 1 1.5 1.8 1L20 13c.8-.5.8-1.6 0-2.1L8.8 3.8C8 3.3 7 3.9 7 4.8z"/></svg>',
    skip: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 5.5v13c0 .8.9 1.3 1.6.9L15 14v4.5c0 .8.7 1.5 1.5 1.5s1.5-.7 1.5-1.5v-13C18 4.7 17.3 4 16.5 4S15 4.7 15 5.5V10L5.6 4.6C4.9 4.2 4 4.7 4 5.5z"/></svg>',
    stop: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    restart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3.4-7.06"/><path d="M3 3.6v5h5"/></svg>',
    chevL: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 5.5L8 12l6.5 6.5"/></svg>',
    chevR: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 5.5L16 12l-6.5 6.5"/></svg>',
    gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34 1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87 1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1z"/></svg>'
  };

  // Estilo calcado del panel del asistente de encuestas (cristal claro pastel)
  const STYLE = `
    :host { all: initial; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    :host {
      --glass-bg: rgba(255, 255, 255, 0.55);
      --glass-bg-input: rgba(255, 255, 255, 0.6);
      --glass-bg-hover: rgba(255, 255, 255, 0.78);
      --glass-border: rgba(255, 255, 255, 0.7);
      --glass-shadow: 0 12px 36px rgba(20, 30, 60, 0.10), 0 3px 10px rgba(20, 30, 60, 0.06);
      --glass-inset: inset 0 1px 0 rgba(255, 255, 255, 0.9);
      --text-primary: rgba(0, 0, 0, 0.88);
      --text-secondary: rgba(0, 0, 0, 0.55);
      --text-tertiary: rgba(0, 0, 0, 0.38);
      --accent: #10b981;
      --radius-card: 22px;
      --radius-button: 14px;
      /* Solo palabras clave del sistema: las páginas no pueden suplantarlas
         con @font-face, así que el reloj se ve igual en todas las pestañas. */
      --font-system: -apple-system, system-ui, sans-serif;
      --font-rounded: -apple-system-rounded, ui-rounded, var(--font-system);
    }
    @keyframes glassRise {
      from { opacity: 0; transform: translateY(6px) scale(0.98); }
      to   { opacity: 1; transform: translateY(0) scale(1); }
    }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
    .bg {
      background:
        radial-gradient(ellipse 520px 380px at 5% 0%, rgba(255, 110, 180, 0.42) 0%, transparent 60%),
        radial-gradient(ellipse 460px 460px at 100% 100%, rgba(70, 150, 255, 0.5) 0%, transparent 62%),
        radial-gradient(ellipse 380px 380px at 100% 0%, rgba(255, 200, 110, 0.38) 0%, transparent 70%),
        linear-gradient(140deg, #fdf2f6 0%, #eef3ff 100%);
    }

    /* ── Panel ── */
    .panel {
      width: 300px;
      max-height: 92vh;
      display: none;
      flex-direction: column;
      font-family: var(--font-system);
      color: var(--text-primary);
      -webkit-font-smoothing: antialiased;
      border-radius: var(--radius-card);
      overflow: hidden;
      border: 0.5px solid var(--glass-border);
      box-shadow: 0 22px 64px rgba(20, 30, 60, 0.30), 0 6px 18px rgba(20, 30, 60, 0.18);
      animation: glassRise 0.4s cubic-bezier(0.2, 0.8, 0.2, 1);
    }
    .panel.open { display: flex; }
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 13px 14px 6px 18px;
      cursor: grab;
      user-select: none;
      -moz-user-select: none;
    }
    .header:active { cursor: grabbing; }
    .header .eyebrow {
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--text-secondary);
      margin-bottom: 1px;
    }
    .header .title {
      font-family: var(--font-rounded);
      font-size: 18px;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--text-primary);
    }
    .round-btn {
      flex-shrink: 0;
      width: 26px;
      height: 26px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
      line-height: 1;
      color: var(--text-secondary);
      background: rgba(255, 255, 255, 0.5);
      border: 0.5px solid rgba(0, 0, 0, 0.06);
      border-radius: 50%;
      cursor: pointer;
      transition: background 0.15s ease, color 0.15s ease;
    }
    .round-btn:hover { background: rgba(255, 255, 255, 0.85); color: var(--text-primary); }
    .body {
      flex: 1 1 auto;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      padding: 0 16px 16px;
      scrollbar-width: thin;
      scrollbar-color: rgba(0, 0, 0, 0.16) transparent;
    }
    .tally-row { display: flex; justify-content: center; margin-bottom: 2px; }
    .tally {
      font-family: var(--font-rounded);
      font-size: 12px;
      font-weight: 650;
      color: var(--text-secondary);
      background: var(--glass-bg);
      border: 0.5px solid var(--glass-border);
      border-radius: 999px;
      padding: 4px 12px;
      box-shadow: var(--glass-shadow), var(--glass-inset);
    }
    .dial { position: relative; margin: 6px auto 0; width: 170px; height: 170px; }
    .dial svg { width: 100%; height: 100%; transform: rotate(-90deg); }
    .dial .track { fill: none; stroke: rgba(0, 0, 0, 0.08); stroke-width: 10; }
    .dial .prog {
      fill: none;
      stroke: var(--accent);
      stroke-width: 10;
      stroke-linecap: round;
      stroke-dasharray: ${C_DIAL};
      stroke-dashoffset: 0;
      transition: stroke-dashoffset 0.5s linear, stroke 0.3s ease, stroke-width 0.25s ease, filter 0.25s ease;
    }
    .panel[data-mode="paused"] .dial .prog { stroke: rgba(0, 0, 0, 0.18); }
    .dial .center {
      position: absolute; inset: 0;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      gap: 3px;
    }
    .dial .time {
      font-family: var(--font-rounded);
      font-size: 38px;
      font-weight: 700;
      letter-spacing: -0.01em;
      font-variant-numeric: tabular-nums;
      line-height: 1;
      color: var(--text-primary);
    }
    .panel[data-mode="paused"] .dial .time { color: var(--text-tertiary); }
    .dial .phase {
      font-family: var(--font-rounded);
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--accent);
    }
    .panel[data-mode="paused"] .dial .phase { color: var(--text-tertiary); }

    /* ── Ajuste del tiempo restante arrastrando el círculo ──────────────── */
    /* El dial solo reacciona cuando hay una fase en curso (running/paused). */
    .panel[data-mode="running"] .dial,
    .panel[data-mode="paused"] .dial {
      cursor: pointer;
      transition: transform 0.25s cubic-bezier(0.34, 1.4, 0.64, 1);
    }
    /* Resorte dopamínico: al acercar el ratón el círculo late y resplandece */
    .panel[data-mode="running"] .dial:hover,
    .panel[data-mode="paused"] .dial:hover { transform: scale(1.035); }
    .panel[data-mode="running"] .dial:hover .prog,
    .panel[data-mode="paused"] .dial:hover .prog {
      stroke-width: 12;
      filter: drop-shadow(0 0 6px color-mix(in srgb, var(--accent) 65%, transparent));
    }
    .dial.grabbing { transform: scale(1.055) !important; }
    .dial.grabbing .prog {
      stroke-width: 13 !important;
      transition: stroke 0.3s ease; /* el arco sigue al dedo al instante */
      filter: drop-shadow(0 0 10px color-mix(in srgb, var(--accent) 85%, transparent));
    }
    /* Tirador: punto que marca el final del arco y se agarra para arrastrar */
    .dial .handle {
      position: absolute;
      left: 50%; top: 9px; /* reposicionado por JS */
      width: 20px; height: 20px;
      border-radius: 50%;
      background: #fff;
      border: 3px solid var(--accent);
      transform: translate(-50%, -50%) scale(0.9);
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.28);
      opacity: 0;
      pointer-events: none;
      z-index: 3;
      will-change: left, top, transform;
      /* left/top con la misma curva lineal que el arco: ambos se deslizan a la
         par entre tics, sin saltos (animación fluida en reposo). */
      transition: left 0.5s linear, top 0.5s linear, opacity 0.25s ease,
                  transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1),
                  box-shadow 0.3s ease;
    }
    .panel[data-mode="running"] .dial .handle,
    .panel[data-mode="paused"] .dial .handle { opacity: 0.85; }
    .panel[data-mode="running"] .dial:hover .handle,
    .panel[data-mode="paused"] .dial:hover .handle {
      opacity: 1;
      transform: translate(-50%, -50%) scale(1.25);
      animation: dialPulse 1.4s ease-in-out infinite;
    }
    .dial.grabbing .handle {
      animation: none;
      opacity: 1;
      transform: translate(-50%, -50%) scale(1.45);
      /* al arrastrar, el tirador sigue al dedo al instante (sin inercia en left/top) */
      transition: transform 0.14s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.25s ease;
      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35),
                  0 0 0 10px color-mix(in srgb, var(--accent) 26%, transparent),
                  0 0 24px color-mix(in srgb, var(--accent) 75%, transparent);
    }
    @keyframes dialPulse {
      0%, 100% {
        box-shadow: 0 3px 10px rgba(0, 0, 0, 0.3),
                    0 0 0 6px color-mix(in srgb, var(--accent) 20%, transparent),
                    0 0 14px color-mix(in srgb, var(--accent) 45%, transparent);
      }
      50% {
        box-shadow: 0 3px 10px rgba(0, 0, 0, 0.3),
                    0 0 0 12px color-mix(in srgb, var(--accent) 9%, transparent),
                    0 0 22px color-mix(in srgb, var(--accent) 65%, transparent);
      }
    }
    .dots { display: flex; justify-content: center; gap: 7px; margin: 8px 0 12px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: rgba(0, 0, 0, 0.10); transition: background 0.3s; }
    .dot.on { background: var(--accent); box-shadow: 0 0 6px color-mix(in srgb, var(--accent) 60%, transparent); }
    .controls { display: flex; gap: 8px; margin-bottom: 10px; }
    .controls button {
      all: unset;
      flex: 1;
      text-align: center;
      padding: 11px 8px;
      border-radius: var(--radius-button);
      font-family: var(--font-rounded);
      font-size: 14px;
      font-weight: 650;
      cursor: pointer;
      transition: filter 0.15s, background 0.15s, color 0.15s;
    }
    .primary {
      color: white;
      background: linear-gradient(180deg, #10b981 0%, #059669 100%);
      box-shadow: 0 6px 18px rgba(16, 185, 129, 0.30), inset 0 1px 0 rgba(255, 255, 255, 0.3);
    }
    .primary:hover { filter: brightness(1.06); }
    .ghost {
      color: var(--text-secondary);
      background: var(--glass-bg);
      border: 0.5px solid var(--glass-border) !important;
      box-shadow: var(--glass-shadow), var(--glass-inset);
    }
    .ghost:hover { background: var(--glass-bg-hover); color: var(--text-primary); }
    .icon-btn { flex: 0 0 42px !important; }
    .icon-btn svg { width: 16px; height: 16px; display: block; margin: 0 auto; }
    /* Con 4 botones (fase activa) el texto se compacta para que quepa */
    .panel[data-mode="running"] .controls button,
    .panel[data-mode="paused"] .controls button { font-size: 13px; padding: 11px 4px; }
    .danger:hover { color: #ff453a; background: rgba(255, 69, 58, 0.10); }
    .only-idle, .only-running, .only-paused, .only-active { display: none !important; }
    .panel[data-mode="idle"] .only-idle { display: block !important; }
    .panel[data-mode="running"] .only-running, .panel[data-mode="running"] .only-active { display: block !important; }
    .panel[data-mode="paused"] .only-paused, .panel[data-mode="paused"] .only-active { display: block !important; }
    .card {
      background: var(--glass-bg);
      border: 0.5px solid var(--glass-border);
      border-radius: 18px;
      box-shadow: var(--glass-shadow), var(--glass-inset);
      padding: 11px 12px 12px;
    }
    .card-title {
      font-family: var(--font-rounded);
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--text-tertiary);
      margin-bottom: 8px;
    }
    .grid4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 10px; }
    .grid4 label {
      display: flex; flex-direction: column; gap: 4px;
      font-size: 10px; font-weight: 650; color: rgba(0, 0, 0, 0.5); text-align: center;
      font-family: var(--font-system);
    }
    .grid4 input {
      width: 100%;
      padding: 6px 2px;
      border-radius: 10px;
      border: 0.5px solid rgba(255, 255, 255, 0.8);
      background: var(--glass-bg-input);
      box-shadow: inset 0 1px 2px rgba(20, 30, 60, 0.06);
      color: var(--text-primary);
      font-family: var(--font-rounded);
      font-size: 13px;
      font-weight: 600;
      font-variant-numeric: tabular-nums;
      text-align: center;
    }
    .grid4 input:focus { outline: none; border-color: var(--accent); }
    .check {
      display: flex; align-items: center; gap: 7px;
      font-size: 12px; color: var(--text-secondary);
      margin: 5px 0; cursor: pointer;
      font-family: var(--font-system);
    }
    .check input { accent-color: var(--accent); }
    .row { display: flex; gap: 8px; margin-top: 8px; }
    .mini {
      all: unset;
      flex: 1;
      text-align: center;
      padding: 7px 8px;
      border-radius: 10px;
      font-family: var(--font-rounded);
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      color: var(--text-secondary);
      background: rgba(255, 255, 255, 0.5);
      border: 0.5px solid var(--glass-border) !important;
      transition: background 0.15s;
    }
    .mini:hover { background: rgba(255, 255, 255, 0.85); color: var(--text-primary); }

    /* ── Estadísticas ── */
    .stats { margin-top: 10px; display: none; }
    .stats.open { display: block; }
    .chart { display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px; padding: 2px 2px 0; }
    .chart .col { display: flex; flex-direction: column; align-items: center; justify-content: flex-end; gap: 3px; height: 88px; }
    .chart .n {
      font-family: var(--font-rounded);
      font-size: 10px; font-weight: 700;
      font-variant-numeric: tabular-nums;
      color: var(--text-secondary);
      line-height: 1;
    }
    .chart .bar {
      width: 100%; max-width: 20px;
      border-radius: 6px 6px 3px 3px;
      background: color-mix(in srgb, var(--accent) 45%, rgba(255, 255, 255, 0.7));
      transition: height 0.3s ease;
    }
    .chart .col.today .bar { background: var(--accent); }
    .chart .d {
      font-family: var(--font-system);
      font-size: 9px; font-weight: 650;
      letter-spacing: 0.06em; text-transform: uppercase;
      color: var(--text-tertiary);
    }
    .chart .col.today .d { color: var(--accent); font-weight: 750; }
    .stats-total {
      margin-top: 9px; text-align: center;
      font-family: var(--font-rounded);
      font-size: 12px; font-weight: 650;
      color: var(--text-secondary);
    }

    /* ── Píldora ── */
    .pill {
      display: none;
      align-items: center;
      gap: 10px;
      padding: 9px 14px 9px 8px;
      border: 0.5px solid var(--glass-border);
      border-radius: 999px;
      box-shadow: 0 12px 36px rgba(20, 30, 60, 0.22), 0 3px 10px rgba(20, 30, 60, 0.12), var(--glass-inset);
      font-family: var(--font-system);
      color: var(--text-primary);
      -webkit-font-smoothing: antialiased;
      user-select: none;
      -moz-user-select: none;
      touch-action: none;
      cursor: grab;
      animation: glassRise 0.4s cubic-bezier(0.2, 0.8, 0.2, 1);
    }
    .pill.open { display: flex; }
    .pill:active { cursor: grabbing; }
    .grip { display: grid; grid-template-columns: repeat(2, 3px); gap: 2.5px; padding: 5px 2px; opacity: 0.6; flex: none; transition: opacity 0.2s; }
    .grip span { width: 3px; height: 3px; border-radius: 50%; background: rgba(0, 0, 0, 0.32); }
    .pill:hover .grip { opacity: 1; }
    .ring { width: 28px; height: 28px; flex: none; }
    .rot { transform: rotate(-90deg); transform-origin: center; }
    .ring .track { fill: none; stroke: rgba(0, 0, 0, 0.10); stroke-width: 3.5; }
    .ring .prog { fill: none; stroke: var(--accent); stroke-width: 3.5; stroke-linecap: round; transition: stroke-dashoffset 0.4s linear, stroke 0.3s ease; }
    .core { fill: var(--accent); transition: fill 0.3s ease; }
    /* Sin animacion continua: un pulso CSS infinito obliga a WebKit a
       recompositar en cada vsync (~60fps) para siempre y Xwayland se clava.
       El punto se queda solido; el estado "en marcha" ya se ve por el anillo. */
    .pill.running .core { fill: var(--accent); }
    .pill .time {
      font-family: var(--font-rounded);
      font-size: 18px; font-weight: 600;
      font-variant-numeric: tabular-nums;
      letter-spacing: 0.03em; min-width: 54px; max-width: 70px; text-align: center; line-height: 1;
      overflow: hidden; white-space: nowrap;
      color: var(--accent);
      transition: color 0.3s ease, min-width 0.3s ease, max-width 0.3s ease, opacity 0.3s ease, margin 0.3s ease;
    }
    /* Modo discreto: el reloj se pliega y la pastilla se estrecha */
    .pill.compact .time { min-width: 0; max-width: 0; opacity: 0; margin-left: -10px; }
    .pill.paused .time { color: var(--text-tertiary); }
    .pill.paused .prog { stroke: rgba(0, 0, 0, 0.18) !important; }
    .pill.paused .core { fill: rgba(0, 0, 0, 0.18) !important; }
    .pbtn {
      all: unset; width: 24px; height: 24px; border-radius: 50%;
      display: grid; place-items: center; cursor: pointer;
      color: var(--text-secondary); flex: none; background: rgba(255, 255, 255, 0.5);
      border: 0.5px solid rgba(0, 0, 0, 0.06);
      transition: background 0.15s ease, color 0.15s ease;
    }
    .pbtn:hover { background: rgba(255, 255, 255, 0.9); color: var(--text-primary); }
    .pbtn svg { width: 11px; height: 11px; display: block; }
    /* Botón casi invisible para plegar/desplegar el reloj */
    .phide {
      all: unset; width: 10px; height: 22px; margin: 0 -5px 0 -4px;
      display: grid; place-items: center; cursor: pointer;
      color: rgba(0, 0, 0, 0.35); opacity: 0.35; flex: none;
      transition: opacity 0.2s ease, color 0.2s ease;
    }
    .pill:hover .phide { opacity: 0.8; }
    .phide:hover { opacity: 1; color: var(--text-primary); }
    .phide svg { width: 9px; height: 9px; display: block; }
  `;

  const HTML = `<style>${STYLE}</style>
  <div class="panel bg" id="panel" data-mode="idle">
    <div class="header" id="panelDrag">
      <div class="titles">
        <div class="eyebrow">Estudio</div>
        <div class="title">Pomodoro</div>
      </div>
      <button class="round-btn" id="closeBtn" title="Plegar">×</button>
    </div>
    <div class="body">
      <div class="tally-row"><span class="tally" id="tally">🍅 0 hoy</span></div>
      <div class="dial" id="dial" title="Arrastra el círculo para ajustar el tiempo que queda">
        <svg viewBox="0 0 220 220">
          <circle class="track" cx="110" cy="110" r="${R_DIAL}"></circle>
          <circle class="prog" id="dialProg" cx="110" cy="110" r="${R_DIAL}"></circle>
        </svg>
        <div class="handle" id="dialHandle"></div>
        <div class="center">
          <div class="time" id="dialTime">25:00</div>
          <div class="phase" id="dialPhase">Listo para estudiar</div>
        </div>
      </div>
      <div class="dots" id="dots" title="Pomodoros hasta el descanso largo"></div>
      <div class="controls">
        <button id="bStartFocus" class="primary only-idle">Empezar enfoque</button>
        <button id="bStartBreak" class="ghost only-idle">Descanso</button>
        <button id="bPause" class="primary only-running">Pausar</button>
        <button id="bResume" class="primary only-paused">Reanudar</button>
        <button id="bRestart" class="ghost icon-btn only-active" title="Reiniciar la fase actual">${ICONS.restart}</button>
        <button id="bSkip" class="ghost only-active">Saltar</button>
        <button id="bStop" class="ghost danger only-active">Terminar</button>
      </div>
      <div class="card">
        <div class="card-title">Ajustes</div>
        <div class="grid4">
          <label>Enfoque<input id="s-focus" type="number" min="1" max="180" step="1"></label>
          <label>Corto<input id="s-short" type="number" min="1" max="60" step="1"></label>
          <label>Largo<input id="s-long" type="number" min="1" max="90" step="1"></label>
          <label>Cada 🍅<input id="s-longEvery" type="number" min="2" max="12" step="1"></label>
        </div>
        <label class="check"><input id="s-chain" type="checkbox"> Encadenar fases automáticamente</label>
        <label class="check"><input id="s-sound" type="checkbox"> Alarma al terminar el enfoque y los descansos</label>
        <div class="row">
          <button id="bTestSound" class="mini">Probar alarma</button>
          <button id="bResetCycle" class="mini">Reiniciar ciclo</button>
          <button id="bPim" class="mini" title="Que pase Pim">🎺</button>
        </div>
        <div class="row">
          <button id="bStats" class="mini">Estadísticas de la semana</button>
        </div>
      </div>
      <div class="card stats" id="statsCard">
        <div class="card-title">Última semana</div>
        <div class="chart" id="statsChart"></div>
        <div class="stats-total" id="statsTotal"></div>
      </div>
    </div>
  </div>
  <div class="pill bg" id="pill" title="Clic: abrir panel · Arrastra: mover">
    <div class="grip"><span></span><span></span><span></span><span></span><span></span><span></span></div>
    <svg class="ring" viewBox="0 0 36 36">
      <g class="rot">
        <circle class="track" cx="18" cy="18" r="${R_PILL}"></circle>
        <circle class="prog" id="pillProg" cx="18" cy="18" r="${R_PILL}"
          stroke-dasharray="${C_PILL}" stroke-dashoffset="0"></circle>
      </g>
      <circle class="core" cx="18" cy="18" r="3.4"></circle>
    </svg>
    <span class="time" id="pillTime">--:--</span>
    <button id="pp" class="pbtn" title="Pausar / Reanudar"></button>
    <button id="pg" class="pbtn" title="Ajustes">${ICONS.gear}</button>
    <button id="ph" class="phide" title="Ocultar / mostrar el reloj"></button>
  </div>`;

  let state = null;
  let host = null;
  let ui = null;
  let timer = null;
  let showsPlay = null;
  let panelOpen = false;
  let statsOpen = false;
  let pillCompact = false; // reloj plegado en la pastilla (compartido entre pestañas)
  let showsChevL = null;
  let pillPos = null;   // {fx, fy} fracción del viewport (sincronizada entre pestañas)
  let panelPos = null;

  function build() {
    host = document.createElement('div');
    host.id = 'pomodoro-estudio-host';
    host.style.cssText = 'all:initial;position:fixed;z-index:2147483647;';
    const root = host.attachShadow({ mode: 'closed' });
    root.innerHTML = HTML;
    const $ = (id) => root.getElementById(id);
    ui = {
      panel: $('panel'), panelDrag: $('panelDrag'), closeBtn: $('closeBtn'),
      tally: $('tally'), dial: $('dial'), dialProg: $('dialProg'), dialHandle: $('dialHandle'),
      dialTime: $('dialTime'), dialPhase: $('dialPhase'),
      dots: $('dots'),
      bStartFocus: $('bStartFocus'), bStartBreak: $('bStartBreak'),
      bPause: $('bPause'), bResume: $('bResume'), bRestart: $('bRestart'), bSkip: $('bSkip'), bStop: $('bStop'),
      sFocus: $('s-focus'), sShort: $('s-short'), sLong: $('s-long'), sLongEvery: $('s-longEvery'),
      sChain: $('s-chain'), sSound: $('s-sound'),
      bTestSound: $('bTestSound'), bResetCycle: $('bResetCycle'), bPim: $('bPim'),
      bStats: $('bStats'), statsCard: $('statsCard'), statsChart: $('statsChart'), statsTotal: $('statsTotal'),
      pill: $('pill'), pillProg: $('pillProg'), pillTime: $('pillTime'),
      pp: $('pp'), pg: $('pg'), ph: $('ph')
    };

    ui.closeBtn.addEventListener('click', () => { panelOpen = false; render(); });
    ui.bStartFocus.addEventListener('click', () => send('start', { phase: 'focus' }));
    ui.bStartBreak.addEventListener('click', () => send('start', { phase: 'short' }));
    ui.bPause.addEventListener('click', () => send('pause'));
    ui.bResume.addEventListener('click', () => send('resume'));
    ui.bRestart.addEventListener('click', () => send('restart'));
    ui.bSkip.addEventListener('click', () => send('skip'));
    ui.bStop.addEventListener('click', () => send('stop'));
    ui.bResetCycle.addEventListener('click', () => send('resetCycle'));
    bindDialDrag();
    ui.bPim.addEventListener('click', () => {
      // solo tiene efecto en la app de escritorio (el anfitrión lanza el paseo)
      try { window.webkit.messageHandlers.host.postMessage(JSON.stringify({ type: 'pim' })); } catch (e) {}
    });
    ui.bTestSound.addEventListener('click', () => {
      const a = new Audio(browser.runtime.getURL('alarm.wav'));
      a.volume = 1.0;
      a.play().catch(() => {});
    });
    for (const el of [ui.sFocus, ui.sShort, ui.sLong, ui.sLongEvery, ui.sChain, ui.sSound]) {
      el.addEventListener('change', pushSettings);
    }

    ui.pp.addEventListener('click', (e) => { e.stopPropagation(); send(state && state.running ? 'pause' : 'resume'); });
    ui.pg.addEventListener('click', (e) => { e.stopPropagation(); panelOpen = true; render(); });
    ui.ph.addEventListener('click', (e) => {
      e.stopPropagation();
      pillCompact = !pillCompact;
      browser.storage.local.set({ pillCompact });
      render();
    });
    ui.bStats.addEventListener('click', () => { statsOpen = !statsOpen; renderStats(); positionHost(); });

    makeDraggable(ui.pill, 'pomoPos', () => { panelOpen = true; render(); });
    makeDraggable(ui.panelDrag, 'panelPos', null);

    (document.body || document.documentElement).appendChild(host);
    console.info(`[pomodoro-estudio] v${VERSION}`);
  }

  // Arrastre con listeners en window en fase de captura (la página no puede
  // interceptarlo). Un clic sin movimiento dispara onTap (abrir el panel).
  function makeDraggable(handle, saveKey, onTap) {
    let drag = null;
    // Pinta el último destino pedido en un rAF: varios pointermove por
    // fotograma se funden en un solo repintado (la superficie transparente a
    // pantalla completa es cara de recomponer bajo XWayland).
    const flush = () => {
      if (!drag) return;
      drag.raf = 0;
      const { x, y } = drag.pending;
      // transform (no left/top) para no disparar reflow: solo composición,
      // vía GPU. Se compone con el scale del zoom (origen arriba-izquierda):
      // un offset visual D equivale a translate(D / s).
      const tx = (x - drag.anchorLeft) / drag.s;
      const ty = (y - drag.anchorTop) / drag.s;
      host.style.transform = `${drag.base} translate(${tx}px, ${ty}px)`.trim();
    };
    const onMove = (e) => {
      if (!drag) return;
      e.preventDefault();
      e.stopPropagation();
      if (!drag.moved && Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) < 4) return;
      drag.moved = true;
      // Destino (esquina sup-izda) acotado a la pantalla con dimensiones
      // cacheadas al empezar: ni getBoundingClientRect ni reflow por evento.
      const x = Math.min(Math.max(6, e.clientX - drag.dx), window.innerWidth - drag.w - 6);
      const y = Math.min(Math.max(6, e.clientY - drag.dy), window.innerHeight - drag.h - 6);
      drag.pending = { x, y };
      if (!drag.raf) drag.raf = requestAnimationFrame(flush);
    };
    const onUp = (e) => {
      window.removeEventListener('pointermove', onMove, true);
      window.removeEventListener('pointerup', onUp, true);
      window.removeEventListener('pointercancel', onUp, true);
      if (drag && drag.raf) cancelAnimationFrame(drag.raf);
      if (drag && drag.moved) {
        e.preventDefault();
        e.stopPropagation();
        const r = host.getBoundingClientRect();  // refleja el translate: pos visual real
        // Aterrizar en left/top y soltar el translate: el DOM queda igual que
        // se ve y positionHost vuelve a mandar.
        host.style.left = r.left + 'px';
        host.style.top = r.top + 'px';
        host.style.transform = drag.base;
        // px = borde izquierdo con el reloj desplegado; pr = borde derecho
        // (el ancla real de la píldora al plegar el reloj).
        const pos = { px: r.left, py: r.top };
        if (saveKey === 'pomoPos') {
          if (pillCompact) pos.px -= PILL_DELTA;
          pos.pr = r.right;
          pillPos = pos;
        } else {
          panelPos = pos;
        }
        browser.storage.local.set({ [saveKey]: pos });
      } else if (drag && !drag.moved && onTap) {
        onTap();
      }
      drag = null;
    };
    handle.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || e.target.closest('button, input, .ctrls')) return;
      e.preventDefault();
      e.stopPropagation();
      const r = host.getBoundingClientRect();
      const base = host.style.transform || '';
      host.style.left = r.left + 'px';
      host.style.top = r.top + 'px';
      host.style.right = 'auto';
      host.style.bottom = 'auto';
      host.style.transformOrigin = 'top left';
      drag = {
        dx: e.clientX - r.left, dy: e.clientY - r.top,
        x0: e.clientX, y0: e.clientY,
        // Ancla y dimensiones visuales cacheadas al empezar el arrastre.
        anchorLeft: r.left, anchorTop: r.top,
        w: r.width || 160, h: r.height || 46,
        s: 1, base,
        pending: { x: r.left, y: r.top }, raf: 0,
        moved: false
      };
      window.addEventListener('pointermove', onMove, true);
      window.addEventListener('pointerup', onUp, true);
      window.addEventListener('pointercancel', onUp, true);
    });
  }

  function positionHost() {
    host.style.transform = '';
    const pos = panelOpen ? panelPos : pillPos;
    if (pos && typeof pos.px === 'number') {
      const r = host.getBoundingClientRect();
      const w = r.width || 160, h = r.height || 46;
      const y = Math.min(Math.max(6, pos.py), window.innerHeight - h - 6);
      host.style.top = y + 'px';
      host.style.bottom = 'auto';
      if (!panelOpen && typeof pos.pr === 'number') {
        // Píldora anclada por su borde derecho: al plegar el reloj la anchura
        // encoge de izquierda a derecha y el lado derecho no se mueve.
        host.style.transformOrigin = 'top right';
        const edge = Math.min(Math.max(w + 6, pos.pr), window.innerWidth - 6);
        host.style.right = (window.innerWidth - edge) + 'px';
        host.style.left = 'auto';
      } else {
        host.style.transformOrigin = 'top left';
        const x = Math.min(Math.max(6, pos.px), window.innerWidth - w - 6);
        host.style.left = x + 'px';
        host.style.right = 'auto';
        // Posiciones guardadas por versiones antiguas: fijar el borde derecho.
        if (!panelOpen && r.width) {
          pos.pr = x + w;
          browser.storage.local.set({ pomoPos: pos });
        }
      }
    } else if (panelOpen) {
      host.style.transformOrigin = 'top right';
      host.style.left = 'auto';
      host.style.bottom = 'auto';
      host.style.top = '16px';
      host.style.right = '16px';
    } else {
      host.style.transformOrigin = 'bottom right';
      host.style.left = 'auto';
      host.style.top = 'auto';
      host.style.right = '18px';
      host.style.bottom = '18px';
    }
  }

  async function send(cmd, extra = {}) {
    try {
      state = await browser.runtime.sendMessage({ cmd, ...extra });
      render();
    } catch (e) {}
  }

  // ── Ajuste del tiempo restante arrastrando el dial ──────────────────────
  // Útil cuando se va a acabar la batería: acortas el pomodoro en curso para
  // que llegue a cero y cuente de verdad, en vez de perder lo que llevabas.
  let dialDrag = false;
  let dialPendingMs = null;
  let dialSendTimer = null;

  function dialFromEvent(e) {
    const r = ui.dial.getBoundingClientRect();
    const dx = e.clientX - (r.left + r.width / 2);
    const dy = e.clientY - (r.top + r.height / 2);
    let a = Math.atan2(dx, -dy); // 0 arriba, crece en sentido horario
    if (a < 0) a += 2 * Math.PI;
    return { frac: a / (2 * Math.PI), rad: Math.hypot(dx, dy) / (r.width / 2) };
  }

  function queueSetRemaining(ms) {
    dialPendingMs = ms;
    if (dialSendTimer) return;
    dialSendTimer = setTimeout(() => {
      dialSendTimer = null;
      const m = dialPendingMs; dialPendingMs = null;
      if (m != null) send('setRemaining', { ms: m });
    }, 110);
  }

  function applyDial(e) {
    if (!state || state.phase === 'idle') return;
    const { frac } = dialFromEvent(e);
    const total = (state.settings[state.phase] || 0) * MIN || 1;
    let ms = Math.round(frac * total / 30000) * 30000; // a saltos de 30 s
    ms = Math.max(0, Math.min(total, ms));
    // Pintado optimista para que el arco y el tirador sigan al dedo al instante.
    if (state.running) state.endsAt = Date.now() + ms; else state.remainingMs = ms;
    ui.dialTime.textContent = fmt(ms);
    paint();
    queueSetRemaining(ms);
  }

  function moveDial(e) { if (dialDrag) applyDial(e); }

  function endDial() {
    if (!dialDrag) return;
    dialDrag = false;
    ui.dial.classList.remove('grabbing');
    window.removeEventListener('pointermove', moveDial);
    window.removeEventListener('pointerup', endDial);
    if (dialSendTimer) { clearTimeout(dialSendTimer); dialSendTimer = null; }
    if (dialPendingMs != null) { const m = dialPendingMs; dialPendingMs = null; send('setRemaining', { ms: m }); }
  }

  function bindDialDrag() {
    ui.dial.addEventListener('pointerdown', (e) => {
      if (!state || state.phase === 'idle') return;
      const { rad } = dialFromEvent(e);
      if (rad < 0.34) return; // zona muerta central: no estorbar la lectura del tiempo
      e.preventDefault();
      e.stopPropagation();
      dialDrag = true;
      ui.dial.classList.add('grabbing');
      try { ui.dial.setPointerCapture(e.pointerId); } catch (_) {}
      applyDial(e);
      window.addEventListener('pointermove', moveDial);
      window.addEventListener('pointerup', endDial);
    });
  }

  function pushSettings() {
    if (!state) return;
    const s = state.settings;
    const ci = (el, lo, hi, fb) => {
      const n = Math.round(Number(el.value));
      return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : fb;
    };
    send('settings', {
      settings: {
        focus: ci(ui.sFocus, 1, 180, s.focus),
        short: ci(ui.sShort, 1, 60, s.short),
        long: ci(ui.sLong, 1, 90, s.long),
        longEvery: ci(ui.sLongEvery, 2, 12, s.longEvery),
        chain: ui.sChain.checked,
        sound: ui.sSound.checked
      }
    });
  }

  function fmt(ms) {
    ms = Math.max(0, ms);
    const m = Math.floor(ms / MIN), s = Math.floor(ms / 1000) % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function remaining() {
    return state.running ? Math.max(0, state.endsAt - Date.now()) : (state.remainingMs || 0);
  }

  function paint() {
    if (!state) return;
    const idle = state.phase === 'idle';
    const total = (state.settings[idle ? 'focus' : state.phase] || 0) * MIN || 1;
    const rem = idle ? total : remaining();
    const off = 1 - Math.min(1, rem / total);
    if (panelOpen) {
      ui.dialTime.textContent = fmt(rem);
      ui.dialProg.style.strokeDashoffset = String(C_DIAL * off);
      // Tirador al final del arco (mismo marco sin rotar que el dial, centro 85,85).
      const th = (1 - off) * 2 * Math.PI; // ángulo horario desde arriba
      const RH = 85 * (R_DIAL / 110); // radio del arco en px del dial (170 px)
      ui.dialHandle.style.left = (85 + RH * Math.sin(th)) + 'px';
      ui.dialHandle.style.top = (85 - RH * Math.cos(th)) + 'px';
    } else {
      ui.pillTime.textContent = fmt(rem);
      ui.pillProg.style.strokeDashoffset = String(C_PILL * off);
    }
  }

  // Gráfica de barras de los últimos 7 días (datos de state.history)
  function renderStats() {
    ui.statsCard.classList.toggle('open', statsOpen);
    ui.bStats.textContent = statsOpen ? 'Ocultar estadísticas' : 'Estadísticas de la semana';
    if (!statsOpen) return;
    const hist = (state && state.history) || {};
    const now = new Date();
    const days = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(now.getDate() - i);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      days.push({ dow: 'DLMXJVS'[d.getDay()], data: hist[key] || { count: 0, focusMin: 0 }, isToday: i === 0 });
    }
    const max = Math.max(1, ...days.map((x) => x.data.count));
    ui.statsChart.textContent = '';
    for (const day of days) {
      const col = document.createElement('div');
      col.className = 'col' + (day.isToday ? ' today' : '');
      const n = document.createElement('span');
      n.className = 'n';
      n.textContent = day.data.count || '';
      const bar = document.createElement('div');
      bar.className = 'bar';
      bar.style.height = (day.data.count ? Math.round(6 + 50 * day.data.count / max) : 3) + 'px';
      if (!day.data.count) bar.style.opacity = '0.45';
      const lbl = document.createElement('span');
      lbl.className = 'd';
      lbl.textContent = day.dow;
      col.append(n, bar, lbl);
      ui.statsChart.appendChild(col);
    }
    const tot = days.reduce((a, x) => a + x.data.count, 0);
    const min = days.reduce((a, x) => a + (x.data.focusMin || 0), 0);
    const h = Math.floor(min / 60), m = min % 60;
    ui.statsTotal.textContent = tot
      ? `${tot} 🍅 esta semana · ${h ? `${h} h ${m} min` : `${m} min`} de enfoque`
      : 'Aún no hay pomodoros esta semana';
  }

  function render() {
    const active = state && state.phase !== 'idle';
    if (!host) {
      if (!active && !panelOpen) return;
      build();
    }
    if (!active && !panelOpen) {
      host.style.display = 'none';
      stopTick();
      return;
    }
    host.style.display = '';
    const phase = state ? state.phase : 'idle';
    const mode = phase === 'idle' ? 'idle' : (state.running ? 'running' : 'paused');
    const c = COLORS[phase] || '#10b981';
    host.style.setProperty('--accent', c);

    ui.panel.classList.toggle('open', panelOpen);
    ui.pill.classList.toggle('open', !panelOpen && active);

    if (panelOpen) {
      ui.panel.dataset.mode = mode;
      ui.dialPhase.textContent = phase === 'idle'
        ? 'Listo para estudiar'
        : LABELS[phase] + (state.running ? '' : ' · en pausa');
      ui.tally.textContent = `🍅 ${state && state.today ? state.today.count : 0} hoy`;
      if (state) {
        const n = state.settings.longEvery;
        let filled = state.cycle % n;
        if (filled === 0 && state.cycle > 0 && phase === 'long') filled = n;
        ui.dots.textContent = '';
        for (let i = 0; i < n; i++) {
          const d = document.createElement('span');
          d.className = 'dot' + (i < filled ? ' on' : '');
          ui.dots.appendChild(d);
        }
        const root = ui.panel.getRootNode();
        const focused = root.activeElement;
        const fields = [['sFocus', 'focus'], ['sShort', 'short'], ['sLong', 'long'], ['sLongEvery', 'longEvery']];
        for (const [el, k] of fields) {
          if (focused !== ui[el]) ui[el].value = state.settings[k];
        }
        ui.sChain.checked = state.settings.chain;
        ui.sSound.checked = state.settings.sound;
      }
      renderStats();
    } else {
      ui.pill.classList.toggle('paused', mode === 'paused');
      ui.pill.classList.toggle('running', mode === 'running');
      ui.pill.classList.toggle('compact', pillCompact);
      const wantPlay = mode !== 'running';
      if (showsPlay !== wantPlay) {
        showsPlay = wantPlay;
        ui.pp.innerHTML = wantPlay ? ICONS.play : ICONS.pause;
      }
      if (showsChevL !== !pillCompact) {
        showsChevL = !pillCompact;
        ui.ph.innerHTML = pillCompact ? ICONS.chevR : ICONS.chevL;
      }
    }
    paint();
    positionHost();
    if (state && state.running && !document.hidden) startTick(); else stopTick();
  }

  // 1000ms (no 500): el reloj muestra mm:ss y solo cambia una vez por segundo.
  // Con 500ms la mitad de los repintados eran idénticos; a 1s WebKit tiene hueco
  // para dormir entre tics en vez de recompositar sin pausa.
  function startTick() { if (!timer) timer = setInterval(paint, 1000); }
  function stopTick() { if (timer) { clearInterval(timer); timer = null; } }

  browser.runtime.onMessage.addListener((msg) => {
    if (!msg) return;
    if (msg.cmd === 'togglePanel') {
      panelOpen = !panelOpen;
      if (panelOpen && !state) send('get'); else render();
    }
  });

  browser.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    if (changes.pomo) { state = changes.pomo.newValue; render(); }
    if (changes.pomoPos && changes.pomoPos.newValue) { pillPos = changes.pomoPos.newValue; if (host) positionHost(); }
    if (changes.panelPos && changes.panelPos.newValue) { panelPos = changes.panelPos.newValue; if (host) positionHost(); }
    if (changes.pillCompact) {
      pillCompact = !!changes.pillCompact.newValue;
      if (host) render();
    }
  });

  document.addEventListener('visibilitychange', () => { if (state || panelOpen) render(); });
  window.addEventListener('resize', () => { if (host) positionHost(); });

  // Con el panel abierto, un clic en cualquier parte de la página fuera del
  // panel lo pliega de vuelta a la píldora (sin tener que pulsar la ×).
  window.addEventListener('pointerdown', (e) => {
    if (!panelOpen || !host) return;
    if (e.composedPath().includes(host)) return;
    panelOpen = false;
    render();
  }, true);

  browser.storage.local.get(['pomo', 'pomoPos', 'panelPos', 'pillCompact']).then(({ pomo, pomoPos, panelPos: pp, pillCompact: pc }) => {
    state = pomo || null;
    if (pomoPos && typeof pomoPos.px === 'number') pillPos = pomoPos;
    if (pp && typeof pp.px === 'number') panelPos = pp;
    pillCompact = !!pc;
    render();
  });
})();
