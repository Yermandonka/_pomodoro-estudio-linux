'use strict';

// ── Estado ────────────────────────────────────────────────────────────────
const MIN = 60000;

const DEFAULTS = {
  phase: 'idle',        // idle | focus | short | long
  running: false,
  endsAt: 0,            // timestamp de fin (cuando corre)
  remainingMs: 0,       // restante (cuando está en pausa)
  cycle: 0,             // pomodoros de la sesión (marca cuándo toca descanso largo)
  today: { date: '', count: 0 }, // contador diario, se reinicia a medianoche
  history: {},          // por día: { 'AAAA-MM-DD': { count, focusMin } }, últimos 7 días
  settings: {
    focus: 25,          // minutos de enfoque
    short: 5,           // descanso corto
    long: 15,           // descanso largo
    longEvery: 4,       // descanso largo cada N pomodoros
    chain: true,        // encadenar fases automáticamente
    sound: true         // alarma al terminar el enfoque o cualquier descanso
  }
};

let state = { ...DEFAULTS, settings: { ...DEFAULTS.settings } };

async function init() {
  const { pomo } = await browser.storage.local.get('pomo');
  if (pomo) {
    state = { ...state, ...pomo, settings: { ...state.settings, ...(pomo.settings || {}) } };
  }
  rollToday();
  // Al reabrir (p. ej. tras apagar el portátil): cualquier ciclo que estuviera
  // en curso se da por terminado por completo. No se reanuda ni se auto-completa
  // (nada de pomodoros fantasma en el contador), se arranca siempre en reposo.
  // El recuento diario y el historial de pomodoros reales se conservan.
  if (state.running || state.phase !== 'idle') {
    state.phase = 'idle';
    state.running = false;
    state.endsAt = 0;
    state.remainingMs = 0;
    state.cycle = 0;
  }
  save();
}

function save() { browser.storage.local.set({ pomo: state }); }
function durationMs(phase) { return (state.settings[phase] || 0) * MIN; }

function dateStr(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function todayStr() { return dateStr(new Date()); }

function rollToday() { // reinicia el contador diario si ha cambiado el día
  const d = todayStr();
  if (!state.today || state.today.date !== d) state.today = { date: d, count: 0 };
  pruneHistory();
}

function pruneHistory() { // conserva solo los últimos 7 días (hoy incluido)
  if (!state.history) { state.history = {}; return; }
  const limit = new Date();
  limit.setDate(limit.getDate() - 6);
  const cutoff = dateStr(limit); // AAAA-MM-DD se compara bien como texto
  for (const key of Object.keys(state.history)) {
    if (key < cutoff) delete state.history[key];
  }
}

// ── Máquina de fases ──────────────────────────────────────────────────────
function startPhase(phase) {
  state.phase = phase;
  state.running = true;
  state.endsAt = Date.now() + durationMs(phase);
  state.remainingMs = 0;
}

function armPhase(phase) { // fase preparada pero en pausa (chain desactivado)
  state.phase = phase;
  state.running = false;
  state.endsAt = 0;
  state.remainingMs = durationMs(phase);
}

function nextAfter(finished) {
  if (finished !== 'focus') return 'focus';
  return state.cycle > 0 && state.cycle % state.settings.longEvery === 0 ? 'long' : 'short';
}

function finishPhase() { // fin natural de la fase en curso
  const finished = state.phase;
  if (finished === 'focus') {
    state.cycle += 1;
    rollToday();
    state.today.count += 1;
    const key = todayStr();
    const day = state.history[key] || { count: 0, focusMin: 0 };
    day.count += 1;
    day.focusMin += state.settings.focus;
    state.history[key] = day;
  }
  if (state.settings.sound) playAlarm();
  const next = nextAfter(finished);
  notify(finished, next);
  if (state.settings.chain) startPhase(next);
  else armPhase(next);
  save();
}

// ── Alarma y notificaciones ───────────────────────────────────────────────
// `Audio` está sustituido por el shim: play() delega en el anfitrión Python
// (GStreamer nativo) y siempre resuelve.
const alarm = new Audio(browser.runtime.getURL('alarm.wav'));
alarm.volume = 1.0;

async function playAlarm() {
  try {
    alarm.currentTime = 0;
    await alarm.play();
  } catch (e) {}
}

function notify(finished, next) {
  const mins = state.settings[next];
  const title = finished === 'focus'
    ? `Pomodoro ${state.cycle} completado 🍅`
    : 'Descanso terminado';
  const message = finished === 'focus'
    ? (next === 'long' ? `Te has ganado un descanso largo: ${mins} min.` : `Descanso corto: ${mins} min.`)
    : `Vuelta al enfoque: ${mins} min.`;
  browser.notifications.create({
    type: 'basic',
    iconUrl: browser.runtime.getURL('icon.svg'),
    title,
    message
  }).catch(() => {});
}

// Reloj de fondo: cierra la fase en cuanto se agota el tiempo (incluye el
// caso de dejar el restante a cero arrastrando el dial).
setInterval(() => {
  if (state.running && Date.now() >= state.endsAt) finishPhase();
}, 1000);

// ── Comandos desde el widget ──────────────────────────────────────────────
browser.runtime.onMessage.addListener((msg) => {
  switch (msg && msg.cmd) {
    case 'start':
      startPhase(msg.phase === 'short' || msg.phase === 'long' ? msg.phase : 'focus');
      break;
    case 'pause':
      if (state.running) {
        state.remainingMs = Math.max(0, state.endsAt - Date.now());
        state.running = false;
        state.endsAt = 0;
      }
      break;
    case 'resume':
      if (!state.running && state.phase !== 'idle') {
        state.endsAt = Date.now() + (state.remainingMs || durationMs(state.phase));
        state.remainingMs = 0;
        state.running = true;
      }
      break;
    case 'skip': // saltar no cuenta como pomodoro completado y no suena
      if (state.phase !== 'idle') startPhase(nextAfter(state.phase));
      break;
    case 'stop':
      state.phase = 'idle';
      state.running = false;
      state.endsAt = 0;
      state.remainingMs = 0;
      break;
    case 'setRemaining': // ajustar a mano el tiempo que queda (arrastrando el dial)
      if (state.phase !== 'idle') {
        const total = durationMs(state.phase);
        const ms = Math.max(0, Math.min(total, Math.round(Number(msg.ms) || 0)));
        if (state.running) state.endsAt = Date.now() + ms;
        else state.remainingMs = ms;
      }
      break;
    case 'restart': // vuelve a poner la fase actual a su duración completa
      if (state.phase !== 'idle') {
        if (state.running) startPhase(state.phase);
        else armPhase(state.phase); // en pausa: se recarga el tiempo sin arrancar
      }
      break;
    case 'resetCycle':
      state.cycle = 0;
      break;
    case 'settings':
      state.settings = { ...state.settings, ...msg.settings };
      if (!state.running && state.phase !== 'idle' && !state.remainingMs) {
        state.remainingMs = durationMs(state.phase);
      }
      break;
    case 'testSound':
      playAlarm();
      return Promise.resolve(state);
    case 'get':
    default:
      rollToday();
      return Promise.resolve(state);
  }
  save();
  return Promise.resolve(state);
});

init();
