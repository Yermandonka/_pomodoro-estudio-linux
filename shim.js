'use strict';
// Shim del API browser.* de Firefox para que background.js y content.js de la
// extensión corran SIN CAMBIOS dentro de una página WebKitGTK. Se carga antes
// que ellos. El anfitrión Python recibe mensajes por
// window.webkit.messageHandlers.host (siempre JSON en texto).
(() => {
  const post = (obj) => {
    try { window.webkit.messageHandlers.host.postMessage(JSON.stringify(obj)); } catch (e) {}
  };
  const clone = (v) => v === undefined ? v : JSON.parse(JSON.stringify(v));

  // ── Captura del shadow root cerrado del widget ─────────────────────────
  // content.js usa attachShadow({mode:'closed'}); se intercepta ANTES de que
  // corra para poder leer el estado real (panel abierto o píldora) desde aquí.
  let widgetRoot = null;
  const origAttach = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function (init) {
    const root = origAttach.call(this, init);
    if (this.id === 'pomodoro-estudio-host') widgetRoot = root;
    return root;
  };

  // ── storage.local ──────────────────────────────────────────────────────
  // Respaldado por un objeto en memoria (inicial inyectado por el anfitrión)
  // que se persiste a disco vía Python en cada set().
  const store = clone(window.__initialStorage || {}) || {};
  const changedListeners = [];

  // ── runtime.onMessage ──────────────────────────────────────────────────
  // En la extensión hay dos contextos: background (recibe runtime.sendMessage)
  // y content (recibe tabs.sendMessage). Aquí comparten página, así que se
  // reparte por orden de registro: el PRIMER listener es el del background
  // (background.js se carga antes), el resto son del content.
  const msgListeners = [];

  window.browser = {
    runtime: {
      getURL: (p) => new URL(p, location.href).href,
      sendMessage: (msg) => {
        const fn = msgListeners[0];
        if (!fn) return Promise.reject(new Error('sin background'));
        try { return Promise.resolve(fn(msg, {})); }
        catch (e) { return Promise.reject(e); }
      },
      onMessage: { addListener: (fn) => msgListeners.push(fn) }
    },
    storage: {
      local: {
        get: (keys) => {
          const list = keys == null ? Object.keys(store)
            : Array.isArray(keys) ? keys : [keys];
          const out = {};
          for (const k of list) if (k in store) out[k] = clone(store[k]);
          return Promise.resolve(out);
        },
        set: (obj) => {
          const changes = {};
          for (const [k, v] of Object.entries(obj)) {
            changes[k] = { oldValue: clone(store[k]), newValue: clone(v) };
            store[k] = clone(v);
          }
          post({ type: 'storage', data: store });
          // Firefox también avisa al contexto que hizo el set; igual aquí.
          queueMicrotask(() => {
            for (const fn of changedListeners) {
              try { fn(changes, 'local'); } catch (e) {}
            }
          });
          return Promise.resolve();
        }
      },
      onChanged: { addListener: (fn) => changedListeners.push(fn) }
    },
    notifications: {
      create: (opts) => {
        post({ type: 'notify', title: (opts && opts.title) || '', message: (opts && opts.message) || '' });
        return Promise.resolve('');
      }
    },
    // El anfitrión abre/pliega el panel enviando 'togglePanel' al content.
    tabs: {
      sendMessage: (_id, msg) => {
        for (const fn of msgListeners.slice(1)) {
          try {
            const r = fn(msg, {});
            if (r !== undefined) return Promise.resolve(r);
          } catch (e) {}
        }
        return Promise.reject(new Error('sin receptor'));
      }
    }
  };

  // ── Audio nativo ────────────────────────────────────────────────────────
  // La decodificación del WAV dentro de WebKit (GStreamer bajo XWayland)
  // sonaba distorsionada. Se sustituye `new Audio()` por un shim que delega
  // la reproducción en el anfitrión Python (GStreamer nativo, limpio). Como
  // play() resuelve siempre, background.js nunca cae al carillón sintético.
  window.Audio = class {
    constructor(src) { this.src = src || ''; this.volume = 1; this.currentTime = 0; }
    play() { post({ type: 'sound' }); return Promise.resolve(); }
    pause() { post({ type: 'stopSound' }); }
    addEventListener() {}
    removeEventListener() {}
  };

  // El anfitrión los invoca al relanzar la app, desde el menú contextual y
  // con los cambios de foco (abrir al enfocar desde la vista de actividades,
  // plegar al perder el foco).
  const panelIsOpen = () => {
    const p = widgetRoot && widgetRoot.getElementById('panel');
    return !!(p && p.classList.contains('open'));
  };
  window.__togglePanel = () => {
    window.browser.tabs.sendMessage(0, { cmd: 'togglePanel' }).catch(() => {});
  };
  window.__openPanel = () => { if (!panelIsOpen()) window.__togglePanel(); };
  window.__closePanel = () => { if (panelIsOpen()) window.__togglePanel(); };

  // ── Informe del rectángulo del widget ──────────────────────────────────
  // El anfitrión recorta la "input shape" X11 de la ventana al widget: los
  // clics fuera atraviesan a las apps de debajo. Con el panel abierto se
  // deja toda la ventana receptiva para que el clic fuera lo pliegue (igual
  // que en la extensión).
  const frameNow = () => {
    const host = document.getElementById('pomodoro-estudio-host');
    let frame = { type: 'frame', visible: false, panel: false, x: 0, y: 0, w: 0, h: 0 };
    if (host && host.style.display !== 'none') {
      // Capa compuesta propia: arrastrar el widget mueve la capa en la GPU
      // en vez de repintar los degradados y sombras en cada frame.
      if (host.style.willChange !== 'transform') host.style.willChange = 'transform';
      const r = host.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        frame = {
          type: 'frame', visible: true, panel: panelIsOpen(),
          x: Math.floor(r.left), y: Math.floor(r.top),
          w: Math.ceil(r.width), h: Math.ceil(r.height)
        };
      }
    }
    return frame;
  };
  // Única vía de informes: el anfitrión sondea con evaluate_javascript (no
  // depende de los temporizadores de la página ni de postMessage).
  // `beats` delata si WebKit congela los setInterval del documento.
  let beats = 0;
  setInterval(() => { beats += 1; }, 500);
  window.__frame = () => {
    const f = frameNow();
    f.beats = beats;
    // El anfitrión convierte px CSS → px X11 con el tamaño real del viewport
    // (con escalado fraccional no coinciden).
    f.iw = window.innerWidth;
    f.ih = window.innerHeight;
    f.dpr = window.devicePixelRatio;
    return JSON.stringify(f);
  };

  // Al arrancar: si no hay sesión activa el widget está oculto; se abre el
  // panel para que se vea algo (equivale al clic en el icono de la barra).
  window.addEventListener('load', () => {
    setTimeout(() => {
      const host = document.getElementById('pomodoro-estudio-host');
      if (!host || host.style.display === 'none') window.__togglePanel();
    }, 500);
  });
})();
