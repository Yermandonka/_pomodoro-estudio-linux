#!/usr/bin/env python3
"""Pomodoro de estudio — versión NATIVA (GTK3 + Cairo, sin WebKit).

Reescritura para consumo mínimo de CPU y RAM: una ventana PEQUEÑA (del tamaño
del widget, no de la pantalla), dibujada a mano con Cairo. Al no cubrir todo el
escritorio, el compositor solo recompone un recuadro diminuto → Xwayland en
reposo ~0 % y RAM ~40 MB (frente a ~200 MB de WebKit).

Se conserva TODO lo que dependía de la versión anterior:
  · Mismo fichero de estado  ~/.local/share/pomodoro-estudio/storage.json
    con el mismo esquema `pomo` (phase, running, endsAt, settings.focus…).
  · Mismo nombre de proceso  _pomodoro-estudio-linux/pomodoro.py
    → pim/pim_vigia.py lo sigue detectando con pgrep y Pim pasea igual.
  · Siempre encima en GNOME Wayland vía XWayland (GDK_BACKEND=x11),
    sticky, fuera de Alt+Tab y del dock de actividades.
  · Alarma (GStreamer), notificaciones (libnotify), botón 🎺 de Pim,
    instancia única (relanzar abre/pliega el panel), menú contextual.
"""
import os
os.environ.setdefault('GDK_BACKEND', 'x11')  # imprescindible ANTES de importar Gtk

import json
import math
import subprocess
import sys
import time
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('PangoCairo', '1.0')
gi.require_version('Notify', '0.7')
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo, Notify  # noqa: E402
import cairo  # noqa: E402

GLib.set_prgname('pomodoro-estudio')

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(GLib.get_user_data_dir()) / 'pomodoro-estudio'
STORE_FILE = DATA_DIR / 'storage.json'
ICON_FILE = APP_DIR / 'icon.svg'
ALARM_FILE = APP_DIR / 'alarm.wav'
PIM_FILE = APP_DIR / 'pim' / 'pim_paseo.py'

MIN = 60000  # ms por minuto

_DBG_FILE = Path('/tmp/claude-1000/-home-yermandonka-Projects/900be78c-ec61-457c-93af-21d5cdbe01e6/scratchpad/drag.log')
def _dbg(msg):
    try:
        with open(_DBG_FILE, 'a') as f:
            f.write(msg + '\n')
    except Exception:
        pass

# Paleta (misma que la versión web)
COLORS = {'focus': (1.0, 0.310, 0.545), 'short': (0.063, 0.725, 0.506),
          'long': (0.275, 0.588, 1.0)}
LABELS = {'focus': 'Enfoque', 'short': 'Descanso corto', 'long': 'Descanso largo'}
ACCENT_IDLE = COLORS['short']
# Segundo color de cada fase para el degradado "líquido" de la píldora
SECOND = {'focus': (0.60, 0.16, 0.78), 'short': (0.02, 0.62, 0.70),
          'long': (0.47, 0.30, 0.95)}
SECOND_IDLE = SECOND['short']


def mix(c1, c2, t):
    return (c1[0] * (1 - t) + c2[0] * t, c1[1] * (1 - t) + c2[1] * t,
            c1[2] * (1 - t) + c2[2] * t)


def darken(c, t):
    return (c[0] * (1 - t), c[1] * (1 - t), c[2] * (1 - t))


def desat(c, t):
    """Rebaja el 'fluorescente' mezclando hacia su propia luminancia."""
    lum = 0.30 * c[0] + 0.59 * c[1] + 0.11 * c[2]
    return mix(c, (lum, lum, lum), t)

DEFAULT_SETTINGS = {'focus': 25, 'short': 5, 'long': 15, 'longEvery': 4,
                    'chain': True, 'sound': True}
SETTING_RANGE = {'focus': (1, 180), 'short': (1, 60), 'long': (1, 90),
                 'longEvery': (2, 12)}


def now_ms():
    return int(time.time() * 1000)


def date_str(t=None):
    lt = time.localtime(t)
    return '%04d-%02d-%02d' % (lt.tm_year, lt.tm_mon, lt.tm_mday)


# ─────────────────────────── Modelo / temporizador ──────────────────────────
# Puerto directo de background.js. El estado vive en self.pomo y se persiste en
# storage.json con el MISMO formato que leía pim_vigia.py.
class Model:
    def __init__(self, on_finish):
        self.on_finish = on_finish          # callback(finished, nxt) para alarma+aviso
        self._save_id = 0
        self.pomo = {
            'phase': 'idle', 'running': False, 'endsAt': 0, 'remainingMs': 0,
            'cycle': 0, 'today': {'date': '', 'count': 0}, 'history': {},
            'dialUsed': False,
            'settings': dict(DEFAULT_SETTINGS),
        }
        self.pos_pill = None   # {'x','y'} esquina sup-izq de la ventana-píldora
        self.pos_panel = None
        self.compact = False
        self._load()

    # ── persistencia ─────────────────────────────────────────────────────
    def _load(self):
        try:
            raw = json.loads(STORE_FILE.read_text())
        except (OSError, ValueError):
            raw = {}
        pomo = raw.get('pomo')
        if isinstance(pomo, dict):
            self.pomo.update(pomo)
            self.pomo['settings'] = {**DEFAULT_SETTINGS, **(pomo.get('settings') or {})}
        self.pos_pill = raw.get('pomoPos') if isinstance(raw.get('pomoPos'), dict) else None
        self.pos_panel = raw.get('panelPos') if isinstance(raw.get('panelPos'), dict) else None
        self.compact = bool(raw.get('pillCompact'))
        self._roll_today()
        # Al reabrir: cualquier ciclo en curso se da por terminado (sin
        # pomodoros fantasma). El recuento diario y el historial se conservan.
        p = self.pomo
        if p['running'] or p['phase'] != 'idle':
            p['phase'] = 'idle'
            p['running'] = False
            p['endsAt'] = 0
            p['remainingMs'] = 0
            p['cycle'] = 0
        self.save(now=True)

    def save(self, now=False):
        if now:
            if self._save_id:
                GLib.source_remove(self._save_id)
                self._save_id = 0
            self._flush()
            return
        if self._save_id:
            return
        self._save_id = GLib.timeout_add(600, self._flush)

    def _flush(self):
        self._save_id = 0
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            os.chmod(DATA_DIR, 0o700)
            data = {'pomo': self.pomo}
            if self.pos_pill:
                data['pomoPos'] = self.pos_pill
            if self.pos_panel:
                data['panelPos'] = self.pos_panel
            data['pillCompact'] = self.compact
            tmp = STORE_FILE.with_suffix('.tmp')
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as fh:
                fh.write(json.dumps(data))
            tmp.replace(STORE_FILE)
        except OSError:
            pass
        return False

    # ── calendario ───────────────────────────────────────────────────────
    def _roll_today(self):
        d = date_str()
        t = self.pomo.get('today')
        if not isinstance(t, dict) or t.get('date') != d:
            self.pomo['today'] = {'date': d, 'count': 0}
        self._prune_history()

    def _prune_history(self):
        hist = self.pomo.get('history')
        if not isinstance(hist, dict):
            self.pomo['history'] = {}
            return
        cutoff = date_str(time.time() - 6 * 86400)
        for k in list(hist.keys()):
            if k < cutoff:
                del hist[k]

    # ── consultas ────────────────────────────────────────────────────────
    def duration_ms(self, phase):
        return self.pomo['settings'].get(phase, 0) * MIN

    def remaining_ms(self):
        p = self.pomo
        if p['running']:
            return max(0, p['endsAt'] - now_ms())
        return p.get('remainingMs', 0) or 0

    def active(self):
        return self.pomo['phase'] != 'idle'

    # ── máquina de fases (idéntica a background.js) ───────────────────────
    def _start_phase(self, phase):
        p = self.pomo
        p['phase'] = phase
        p['running'] = True
        p['endsAt'] = now_ms() + self.duration_ms(phase)
        p['remainingMs'] = 0
        p['dialUsed'] = False   # nueva fase: se recupera el adelanto de 15 min

    def _arm_phase(self, phase):
        p = self.pomo
        p['phase'] = phase
        p['running'] = False
        p['endsAt'] = 0
        p['remainingMs'] = self.duration_ms(phase)
        p['dialUsed'] = False

    def _next_after(self, finished):
        if finished != 'focus':
            return 'focus'
        p = self.pomo
        every = p['settings']['longEvery']
        return 'long' if (p['cycle'] > 0 and p['cycle'] % every == 0) else 'short'

    def finish_phase(self):
        p = self.pomo
        finished = p['phase']
        if finished == 'focus':
            p['cycle'] += 1
            self._roll_today()
            p['today']['count'] += 1
            key = date_str()
            day = p['history'].get(key) or {'count': 0, 'focusMin': 0}
            day['count'] += 1
            day['focusMin'] += p['settings']['focus']
            p['history'][key] = day
        nxt = self._next_after(finished)
        if p['settings'].get('sound'):
            self.on_finish(finished, nxt, sound=True)
        else:
            self.on_finish(finished, nxt, sound=False)
        if p['settings'].get('chain'):
            self._start_phase(nxt)
        else:
            self._arm_phase(nxt)
        self.save(now=True)

    # Comandos (equivalen a los mensajes del widget)
    def start(self, phase='focus'):
        self._start_phase(phase if phase in ('focus', 'short', 'long') else 'focus')
        self.save()

    def pause(self):
        p = self.pomo
        if p['running']:
            p['remainingMs'] = max(0, p['endsAt'] - now_ms())
            p['running'] = False
            p['endsAt'] = 0
            self.save()

    def resume(self):
        p = self.pomo
        if not p['running'] and p['phase'] != 'idle':
            p['endsAt'] = now_ms() + (p.get('remainingMs') or self.duration_ms(p['phase']))
            p['remainingMs'] = 0
            p['running'] = True
            self.save()

    def skip(self):
        p = self.pomo
        if p['phase'] != 'idle':
            self._start_phase(self._next_after(p['phase']))
            self.save()

    def stop(self):
        p = self.pomo
        p['phase'] = 'idle'
        p['running'] = False
        p['endsAt'] = 0
        p['remainingMs'] = 0
        self.save()

    def advance_15(self):
        """Adelanta el reloj 15 min, una sola vez por fase (mover el dial).
        Devuelve True si se aplicó."""
        p = self.pomo
        if p['phase'] == 'idle' or p.get('dialUsed'):
            return False
        nuevo = max(0, self.remaining_ms() - 15 * MIN)
        if p['running']:
            p['endsAt'] = now_ms() + nuevo
        else:
            p['remainingMs'] = nuevo
        p['dialUsed'] = True
        self.save()
        return True

    def restart(self):
        p = self.pomo
        if p['phase'] == 'idle':
            return
        if p['running']:
            self._start_phase(p['phase'])
        else:
            self._arm_phase(p['phase'])
        self.save()

    def reset_cycle(self):
        self.pomo['cycle'] = 0
        self.save()

    def set_setting(self, key, value):
        p = self.pomo
        if key in SETTING_RANGE:
            lo, hi = SETTING_RANGE[key]
            value = max(lo, min(hi, int(value)))
        p['settings'][key] = value
        if not p['running'] and p['phase'] != 'idle' and not p.get('remainingMs'):
            p['remainingMs'] = self.duration_ms(p['phase'])
        self.save()

    def tick(self):
        """Devuelve True si acaba de terminar la fase."""
        p = self.pomo
        if p['running'] and now_ms() >= p['endsAt']:
            self.finish_phase()
            return True
        return False


# ───────────────────────────── Utilidades de dibujo ─────────────────────────
def fmt(ms):
    ms = max(0, int(ms))
    return '%02d:%02d' % (ms // MIN, (ms // 1000) % 60)


FONT_FAMILY = 'Ubuntu'  # la del sistema que usaba el original (redondeada)


def rounded_rect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def soft_shadow(cr, x, y, w, h, r, spread=14, alpha=0.16, dy=5,
                color=(0.09, 0.13, 0.25)):
    """Sombra difusa apilando recuadros concéntricos (simula el blur)."""
    cr.save()
    for k in range(spread, 0, -1):
        t = k / spread
        rounded_rect(cr, x - k, y - k + dy, w + 2 * k, h + 2 * k, r + k)
        cr.set_source_rgba(color[0], color[1], color[2], alpha * (1 - t) ** 1.6)
        cr.fill()
    cr.restore()


def ease_out_cubic(p):
    return 1 - (1 - p) ** 3


def ease_out_back(p):
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2


def text_layout(cr, s, size, weight=Pango.Weight.NORMAL, spacing=0.0):
    layout = PangoCairo.create_layout(cr)
    fd = Pango.FontDescription()
    fd.set_family(FONT_FAMILY)
    fd.set_size(int(size * Pango.SCALE))
    fd.set_weight(weight)
    layout.set_font_description(fd)
    if spacing:
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_letter_spacing_new(int(spacing * Pango.SCALE)))
        layout.set_attributes(attrs)
    layout.set_text(s, -1)
    return layout


def draw_text(cr, s, x, y, size, color, bold=False, cx=None, cw=None,
              weight=None, spacing=0.0):
    """Dibuja texto; si cx/cw dados, centra horizontalmente en [cx, cx+cw]."""
    if weight is None:
        weight = Pango.Weight.BOLD if bold else Pango.Weight.NORMAL
    layout = text_layout(cr, s, size, weight, spacing)
    tw, th = layout.get_pixel_size()
    if cx is not None:
        x = cx + (cw - tw) / 2
    cr.save()
    cr.set_source_rgba(*color)
    cr.move_to(x, y - th / 2)  # `y` es SIEMPRE el centro vertical del texto
    PangoCairo.show_layout(cr, layout)
    cr.new_path()  # limpia el punto actual: si no, el siguiente arc/figura traza
                   # una línea desde aquí (causaba una "raya" diagonal del texto al aro)
    cr.restore()
    return tw, th


# ──────────────────────────────── Aplicación ────────────────────────────────
class PomodoroApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='dev.yermandonka.pomodoro')
        self.win = None
        self.area = None
        self.model = None
        self.panel_open = False
        self.stats_open = False
        self._tick_id = 0
        self._player = None
        self._notification = None
        self._pim_proc = None
        self._menu_open = False
        self._drag = None          # arrastre de la ventana
        self.hit = {}              # nombre -> (x,y,w,h) rellenado al dibujar
        self._work = (0, 0, 1920, 1080)
        self._winpos = None        # posición que llevamos nosotros (mutter ignora move)
        self._anim = None          # animación de entrada (abrir/cerrar)
        self._anim_id = 0
        self._clock_reveal = None  # 0..1 apertura del reloj (None = estático)
        self._canim = None         # animación de expansión horizontal
        self._canim_id = 0
        self._hover = False        # ratón encima (restaura opacidad en descanso)
        self._fade = 1.0           # alpha actual de la píldora (animada)
        self._fade_id = 0

    # ── ciclo de vida ────────────────────────────────────────────────────
    def do_activate(self):
        if self.win:
            self.toggle_panel()     # relanzar = abrir/plegar panel
            return
        self.model = Model(self.on_phase_finished)
        self.panel_open = not self.model.active()  # sin sesión → abre el panel
        self.build_window()
        self.refresh(resize=True)
        self.start_anim()

    def do_shutdown(self):
        if self.model:
            self.model.save(now=True)
        Gtk.Application.do_shutdown(self)

    def build_window(self):
        win = Gtk.ApplicationWindow(application=self)
        win.set_title('Pomodoro de estudio')
        win.set_decorated(False)
        win.set_resizable(False)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_focus_on_map(False)
        win.set_keep_above(True)
        win.stick()
        # UTILITY: fuera de la vista de Actividades (Super) y de Alt+Tab.
        # skip_taskbar solo quita del dock; esto la saca del selector de ventanas.
        win.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        screen = win.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            win.set_visual(visual)
        win.set_app_paintable(True)
        try:
            win.set_icon_from_file(str(ICON_FILE))
        except GLib.Error:
            pass
        win.connect('focus-out-event', self.on_focus_out)
        win.connect('delete-event', self.on_delete_event)
        win.connect('map-event', self.on_map)

        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        wa = monitor.get_workarea()
        self._work = (wa.x, wa.y, wa.width, wa.height)

        area = Gtk.DrawingArea()
        area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                        Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK |
                        Gdk.EventMask.SCROLL_MASK |
                        Gdk.EventMask.LEAVE_NOTIFY_MASK)
        area.connect('draw', self.on_draw)
        area.connect('button-press-event', self.on_press)
        area.connect('button-release-event', self.on_release)
        area.connect('motion-notify-event', self.on_motion)
        area.connect('leave-notify-event', self.on_leave)
        area.connect('scroll-event', self.on_scroll)
        win.add(area)
        self.win = win
        self.area = area

    # ── notificaciones / alarma / Pim ────────────────────────────────────
    def on_phase_finished(self, finished, nxt, sound):
        if sound:
            self.play_alarm()
        self.notify(finished, nxt)

    def play_alarm(self):
        # Reproductor por subproceso (fiable y sin bloquear la UI). Se prueba
        # en orden hasta dar con uno disponible en el sistema.
        if self._player is not None and self._player.poll() is None:
            self._player.terminate()  # rebobina si ya sonaba
        cmds = (['pw-play', str(ALARM_FILE)],
                ['paplay', str(ALARM_FILE)],
                ['aplay', '-q', str(ALARM_FILE)],
                ['canberra-gtk-play', '-f', str(ALARM_FILE)])
        for cmd in cmds:
            try:
                self._player = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except (OSError, FileNotFoundError):
                continue

    def notify(self, finished, nxt):
        mins = self.model.pomo['settings'][nxt]
        cycle = self.model.pomo['cycle']
        if finished == 'focus':
            title = 'Pomodoro %d completado 🍅' % cycle
            if nxt == 'long':
                message = 'Te has ganado un descanso largo: %d min.' % mins
            else:
                message = 'Descanso corto: %d min.' % mins
        else:
            title = 'Descanso terminado'
            message = 'Vuelta al enfoque: %d min.' % mins
        try:
            message = GLib.markup_escape_text(message)
            if self._notification is None:
                self._notification = Notify.Notification.new(title, message, str(ICON_FILE))
            else:
                self._notification.update(title, message, str(ICON_FILE))
            # Asocia el aviso al mismo .desktop que está anclado en el dock.
            # GNOME puede así reutilizar su nombre e icono en la pantalla bloqueada.
            self._notification.set_hint(
                'desktop-entry', GLib.Variant('s', 'pomodoro-estudio'))
            self._notification.show()
        except GLib.Error:
            pass

    def launch_pim(self):
        if self._pim_proc is None or self._pim_proc.poll() is not None:
            try:
                self._pim_proc = subprocess.Popen(
                    [sys.executable, str(PIM_FILE)], cwd=str(PIM_FILE.parent))
            except OSError:
                self._pim_proc = None

    # ── tick de un segundo (solo mientras corre y es visible) ─────────────
    def start_tick(self):
        if not self._tick_id:
            self._tick_id = GLib.timeout_add_seconds(1, self._on_tick)

    def stop_tick(self):
        if self._tick_id:
            GLib.source_remove(self._tick_id)
            self._tick_id = 0

    def _on_tick(self):
        finished = self.model.tick()
        if finished:
            self.refresh(resize=True)
            return bool(self._tick_id)
        if self.area:
            self.area.queue_draw()
        return True

    # ── refresco de estado → tamaño, visibilidad, redibujado ──────────────
    def refresh(self, resize=False):
        m = self.model
        active = m.active()
        if not active and not self.panel_open:
            # Widget totalmente oculto: la app se cierra sola (como la web).
            self.quit()
            return
        if resize:
            self._apply_size()
        if m.pomo['running'] and self.panel_open is not None:
            self.start_tick()
        if not m.pomo['running']:
            self.stop_tick()
        if self.win and not self.win.get_visible():
            self.win.show_all()
        if self.area:
            self.area.queue_draw()

    def _content_size(self):
        if self.panel_open:
            return self._panel_size()
        return self._pill_size()

    def _compute_pos(self, w, h):
        wx, wy, ww, wh = self._work
        pos = self.model.pos_panel if self.panel_open else self.model.pos_pill
        if pos and isinstance(pos.get('x'), (int, float)):
            x, y = int(pos['x']), int(pos['y'])
        elif self.panel_open:
            x, y = wx + ww - w - 16, wy + 16
        else:
            x, y = wx + ww - w - 18, wy + wh - h - 18
        x = max(wx + 6, min(x, wx + ww - w - 6))
        y = max(wy + 6, min(y, wy + wh - h - 6))
        return x, y

    def _apply_size(self):
        gw, gh = self._content_size()
        m = self.MARGIN
        w, h = gw + 2 * m, gh + 2 * m
        self.area.set_size_request(w, h)
        if not self.win:
            self._winpos = self._compute_pos(w, h)
            return
        tx, ty = self._compute_pos(w, h)
        _dbg('_apply_size -> tx,ty=(%d,%d) winpos=%s' % (tx, ty, self._winpos))
        if self.win.get_visible() and self._winpos == (tx, ty):
            # misma posición (p. ej. abrir stats: crece hacia abajo) → solo
            # redimensionar, SIN hide/show → sin parpadeo.
            self.win.resize(w, h)
        else:
            # cambia la posición: mutter ignora move() en ventana mapeada, así que
            # hay que ocultar → mover → mostrar (re-mapear) para que la respete.
            self._opened_at = GLib.get_monotonic_time()
            if self.win.get_visible():
                self.win.hide()
            self.win.resize(w, h)
            self._winpos = (tx, ty)
            self.win.move(tx, ty)
            self.win.show_all()
            self.win.set_keep_above(True)
            self.win.stick()

    def _place(self, w, h):
        x, y = self._compute_pos(w, h)
        self._winpos = (x, y)
        if self.win:
            self.win.move(x, y)

    def toggle_panel(self):
        self.panel_open = not self.panel_open
        if not self.panel_open:
            self.stats_open = False
        # marca el momento de apertura: el hide/show del re-mapeo dispara un
        # focus-out inmediato que, sin esta guarda, cerraría el panel al instante.
        self._opened_at = GLib.get_monotonic_time()
        self.refresh(resize=True)
        self.start_anim()

    # ─────────────────────────── Tamaños ────────────────────────────────
    PILL_H = 48
    MARGIN = 20   # hueco alrededor del cristal: sombra completa + rebote anim

    CLOCK_SLOT = 58     # ancho del hueco del reloj mm:ss
    PILL_BASE = 150     # pad(12)+grip(14)+anillo(38)+pp(30)+pg(30)+ph(18)+pad(8)

    def _reveal(self):
        """Fracción de apertura del reloj (0 compacto, 1 desplegado)."""
        if self._clock_reveal is not None:
            return self._clock_reveal
        return 0.0 if self.model.compact else 1.0

    def _pill_fade_target(self):
        """Alpha objetivo de la píldora: en descanso (y sin ratón encima) se
        vuelve casi transparente para no estar mirándola todo el rato."""
        m = self.model
        if self.panel_open or self._hover:
            return 1.0
        if m.active() and m.pomo['phase'] in ('short', 'long') and m.pomo['running']:
            return 0.22
        return 1.0

    def _sync_fade(self):
        """Arranca una animación suave de _fade hacia su objetivo si difiere."""
        target = self._pill_fade_target()
        if abs(self._fade - target) < 0.01:
            self._fade = target
            return
        if self._fade_id:
            return
        start = self._fade

        def tick():
            t0 = getattr(self, '_fade_t0', None)
            now = GLib.get_monotonic_time()
            if t0 is None:
                self._fade_t0 = now
                p = 0.0
            else:
                p = min(1.0, (now - t0) / 350000.0)
            tgt = self._pill_fade_target()   # puede cambiar a mitad de camino
            self._fade = start + (tgt - start) * ease_out_cubic(p)
            if self.area:
                self.area.queue_draw()
            if p >= 1.0:
                self._fade = tgt
                self._fade_id = 0
                self._fade_t0 = None
                return False
            return True

        self._fade_t0 = None
        self._fade_id = GLib.timeout_add(16, tick)

    def _pill_size(self):
        # La VENTANA es siempre del ancho máximo (expandido). La píldora visible
        # se dibuja alineada a la derecha dentro de ella, de modo que al expandir
        # el borde izquierdo crece hacia la IZQUIERDA sin mover la ventana.
        return self.PILL_BASE + self.CLOCK_SLOT, self.PILL_H

    PANEL_W = 300
    DIAL_R = 82

    def _panel_size(self):
        w = self.PANEL_W
        h = 16 + 46              # header
        h += 30                  # tally (píldora)
        h += 2 * self.DIAL_R + 20  # dial
        h += 30                  # dots
        h += 60                  # controles (46 + gap)
        h += 234                 # ajustes (4 numboxes + checks 2 líneas + botones)
        if self.stats_open:
            h += 118
        h += 14
        return w, h

    # ─────────────────────────── Dibujo ─────────────────────────────────
    def accent(self):
        p = self.model.pomo
        return desat(COLORS.get(p['phase'], ACCENT_IDLE), 0.20)  # menos fluorescente

    def start_anim(self):
        import gi  # noqa
        self._anim = {'t0': GLib.get_monotonic_time(), 'dur': 240000.0, 'p': 0.0}
        if not self._anim_id:
            self._anim_id = GLib.timeout_add(16, self._anim_tick)

    def _anim_tick(self):
        a = self._anim
        if not a:
            self._anim_id = 0
            return False
        el = GLib.get_monotonic_time() - a['t0']
        a['p'] = min(1.0, el / a['dur'])
        if self.area:
            self.area.queue_draw()
        if a['p'] >= 1.0:
            self._anim = None
            self._anim_id = 0
            return False
        return True

    def start_compact_anim(self):
        """Expande/pliega la píldora en horizontal (revela el reloj poco a poco).
        Redimensiona la ventana cada fotograma anclada a la izquierda (crece a la
        derecha) — sin hide/show, para que sea fluido."""
        target = 0.0 if self.model.compact else 1.0
        start = self._reveal()
        self._clock_reveal = start
        self._canim = {'t0': GLib.get_monotonic_time(), 'dur': 260000.0,
                       'a': start, 'b': target}
        if not self._canim_id:
            self._canim_id = GLib.timeout_add(16, self._canim_tick)

    def _canim_tick(self):
        a = self._canim
        if not a:
            self._canim_id = 0
            return False
        p = min(1.0, (GLib.get_monotonic_time() - a['t0']) / a['dur'])
        # ventana de ancho fijo: solo cambia el dibujo (alineado a la derecha),
        # así la expansión es fluida y hacia la izquierda, sin resize ni move.
        self._clock_reveal = a['a'] + (a['b'] - a['a']) * ease_out_cubic(p)
        if self.area:
            self.area.queue_draw()
        if p >= 1.0:
            self._canim = None
            self._canim_id = 0
            self._clock_reveal = None   # vuelve a estático (según compact)
            return False
        return True

    def on_draw(self, _area, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        self.hit = {}   # las regiones se guardan en coords del cristal (origen 0,0)
        m = self.MARGIN
        gw, gh = self._content_size()
        draw = self._draw_panel if self.panel_open else self._draw_pill
        self._sync_fade()
        fade = 1.0 if self.panel_open else self._fade
        a = self._anim
        if a:
            p = a['p']
            scale = 0.86 + 0.14 * ease_out_back(p)       # pop con leve rebote
            rise = 12 * (1 - ease_out_cubic(p))           # sube un poco al entrar
            cr.push_group()
            cr.save()
            cr.translate(m + gw / 2, m + gh / 2 + rise)
            cr.scale(scale, scale)
            cr.translate(-gw / 2, -gh / 2)
            draw(cr)
            cr.restore()
            pat = cr.pop_group()
            cr.set_source(pat)
            cr.paint_with_alpha(fade * ease_out_cubic(min(1.0, p * 1.25)))
        elif fade < 0.999:
            cr.push_group()
            cr.save()
            cr.translate(m, m)
            draw(cr)
            cr.restore()
            cr.set_source(cr.pop_group())
            cr.paint_with_alpha(fade)
        else:
            cr.save()
            cr.translate(m, m)
            draw(cr)
            cr.restore()
        # recorta la zona clicable al cristal: la franja transparente (margen y
        # el hueco de la píldora compacta) deja pasar los clics a la app de abajo.
        # Durante las animaciones NO se recalcula (es una llamada al servidor X
        # por fotograma → tirones); se fija al terminar.
        if self.win and self.win.get_realized() and not self._canim and not self._anim:
            if self.panel_open:
                rx, ry, rw, rh = m, m, gw, gh
            else:
                pw = self.PILL_BASE + self.CLOCK_SLOT * self._reveal()
                rx, ry, rw, rh = m + (gw - pw), m, pw, gh
            reg = cairo.Region(cairo.RectangleInt(int(rx) - 2, int(ry) - 2,
                                                  int(rw) + 4, int(rh) + 4))
            self.win.input_shape_combine_region(reg)
        return False

    def _bg_fill(self, cr, x, y, w, h):
        """Fondo EXACTO del original (.bg): base lila-rosada + 3 radiales
        (rosa arriba-izda, azul abajo-dcha, ámbar arriba-dcha). Fijo, NO por
        fase: el color de fase solo tiñe aro, texto y botones."""
        # base: vertical (sin diagonal que deje "raya")
        lg = cairo.LinearGradient(x, y, x, y + h)
        lg.add_color_stop_rgb(0, 0xfd / 255, 0xf2 / 255, 0xf6 / 255)
        lg.add_color_stop_rgb(1, 0xee / 255, 0xf3 / 255, 0xff / 255)
        cr.set_source(lg)
        cr.paint()
        base = max(w, h)
        # radiales grandes y solapados (falloff suave de 3 paradas) para que no
        # quede ninguna franja clara en diagonal entre ellos
        for fx, fy, rad, col, a in (
                (0.0, 0.0, 1.15, (255, 120, 185), 0.40),      # rosa arriba-izda
                (1.0, 1.0, 1.25, (120, 170, 255), 0.42),      # azul abajo-dcha
                (1.0, 0.0, 1.05, (255, 205, 135), 0.34)):     # ámbar arriba-dcha
            cxp, cyp = x + fx * w, y + fy * h
            R = base * rad
            rg = cairo.RadialGradient(cxp, cyp, 0, cxp, cyp, R)
            cr0 = (col[0] / 255, col[1] / 255, col[2] / 255)
            rg.add_color_stop_rgba(0, cr0[0], cr0[1], cr0[2], a)
            rg.add_color_stop_rgba(0.55, cr0[0], cr0[1], cr0[2], a * 0.42)
            rg.add_color_stop_rgba(1, cr0[0], cr0[1], cr0[2], 0)
            cr.set_source(rg)
            cr.paint()

    def _glass(self, cr, x, y, w, h, r=16):
        # sin sombra alrededor del panel (el halo gris quedaba mal)
        cr.save()
        rounded_rect(cr, x, y, w, h, r)
        cr.clip()
        self._bg_fill(cr, x, y, w, h)
        cr.restore()
        # borde fino
        rounded_rect(cr, x + 0.5, y + 0.5, w - 1, h - 1, r)
        cr.set_source_rgba(1, 1, 1, 0.7)
        cr.set_line_width(1)
        cr.stroke()

    def second(self):
        return desat(SECOND.get(self.model.pomo['phase'], SECOND_IDLE), 0.28)

    def _liquid_glass(self, cr, x, y, w, h, r):
        """Píldora con el MISMO fondo multicolor del original (.bg), más clara."""
        soft_shadow(cr, x, y, w, h, r, spread=16, alpha=0.09, dy=6)
        cr.save()
        rounded_rect(cr, x, y, w, h, r)
        cr.clip()
        self._bg_fill(cr, x, y, w, h)
        # velo blanco ligero: apenas suaviza, deja los colores más vivos.
        cr.set_source_rgba(1, 1, 1, 0.10)
        cr.paint()
        # gloss superior
        gg = cairo.LinearGradient(x, y, x, y + h * 0.6)
        gg.add_color_stop_rgba(0, 1, 1, 1, 0.45)
        gg.add_color_stop_rgba(1, 1, 1, 1, 0)
        rounded_rect(cr, x + 2, y + 1.5, w - 4, h * 0.5, r)
        cr.set_source(gg)
        cr.fill()
        cr.restore()
        rounded_rect(cr, x + 0.5, y + 0.5, w - 1, h - 1, r)
        cr.set_source_rgba(1, 1, 1, 0.65)
        cr.set_line_width(1)
        cr.stroke()

    def _ring(self, cr, cx, cy, radius, lw, rem, total, color, glow=False):
        frac = max(0.0, min(1.0, rem / total if total else 0))
        cr.set_line_cap(cairo.LineCap.ROUND)
        # pista
        cr.set_line_width(lw)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.set_source_rgba(0, 0, 0, 0.07)
        cr.stroke()
        if frac > 0:
            a0 = -math.pi / 2
            a1 = a0 + 2 * math.pi * frac
            if glow:
                cr.set_line_width(lw + 6)
                cr.arc(cx, cy, radius, a0, a1)
                cr.set_source_rgba(color[0], color[1], color[2], 0.18)
                cr.stroke()
            cr.set_line_width(lw)
            cr.arc(cx, cy, radius, a0, a1)
            cr.set_source_rgba(*color)
            cr.stroke()
        return frac

    def _draw_pill(self, cr):
        m = self.model
        wmax, h = self._pill_size()
        reveal = self._reveal()
        pill_w = self.PILL_BASE + self.CLOCK_SLOT * reveal
        x0 = wmax - pill_w   # alineado a la derecha: crece hacia la izquierda
        self._liquid_glass(cr, x0, 0, pill_w, h, h / 2)
        color = self.accent()   # mismo rosa que el aro del panel
        paused = m.active() and not m.pomo['running']
        x = x0 + 12
        # grip (3x2 puntos)
        cr.set_source_rgba(0, 0, 0, 0.30)
        for i in range(3):
            for j in range(2):
                cr.arc(x + j * 5, h / 2 - 6 + i * 6, 1.6, 0, 2 * math.pi)
                cr.fill()
        x += 14
        # anillo: color a PLENA saturación (más intenso/vivo, no lavado ni oscuro)
        total = m.duration_ms('focus' if not m.active() else m.pomo['phase']) or 1
        rem = total if not m.active() else m.remaining_ms()
        vivid = COLORS.get(m.pomo['phase'], ACCENT_IDLE)
        rc = (0.6, 0.6, 0.6) if paused else vivid
        cr.save()
        self._ring(cr, x + 15, h / 2, 12.5, 3.2, rem, total, rc)
        cr.restore()
        cr.set_source_rgba(*((0.6, 0.6, 0.6) if paused else vivid))
        cr.arc(x + 15, h / 2, 3.2, 0, 2 * math.pi)
        cr.fill()
        x += 30 + 8
        # reloj: hueco animado que se abre a la derecha revelando los dígitos
        reveal = self._reveal()
        slot = self.CLOCK_SLOT * reveal
        if reveal > 0.02:
            tcol = vivid if not paused else (0, 0, 0, 0.45)
            cr.save()
            cr.rectangle(x - 2, 0, slot + 2, h)
            cr.clip()
            draw_text(cr, fmt(rem), x, h / 2, 15, (tcol[0], tcol[1], tcol[2], reveal), bold=True)
            cr.restore()
        x += slot
        # botones (el chevron apunta a la izquierda cuando está desplegado)
        compact_now = reveal < 0.5
        x = self._icon_btn(cr, 'pp', x, h, 'pause' if m.pomo['running'] else 'play')
        x = self._icon_btn(cr, 'pg', x, h, 'gear')
        x = self._icon_btn(cr, 'ph', x, h, 'chevR' if compact_now else 'chevL', small=True)

    def _icon_btn(self, cr, name, x, h, icon, small=False, alpha=1.0):
        d = 23 if not small else 17
        cy = h / 2
        bx = x
        if not small:
            # círculo blanco definido con una sombrita (como el original)
            cr.arc(bx + d / 2, cy + 1, d / 2, 0, 2 * math.pi)
            cr.set_source_rgba(0.1, 0.12, 0.2, 0.10 * alpha)
            cr.fill()
            cr.arc(bx + d / 2, cy, d / 2, 0, 2 * math.pi)
            cr.set_source_rgba(1, 1, 1, 0.9 * alpha)
            cr.fill()
        self.hit[name] = (bx - 2, cy - d / 2 - 2, d + 4, d + 4)
        self._glyph(cr, icon, bx + d / 2, cy, 11 if not small else 9, alpha=alpha)
        return x + d + (8 if not small else 2)

    def _glyph(self, cr, icon, cx, cy, s, alpha=1.0):
        cr.save()
        cr.set_source_rgba(0, 0, 0, 0.62 * alpha)
        cr.set_line_width(2)
        cr.set_line_cap(cairo.LineCap.ROUND)
        cr.set_line_join(cairo.LineJoin.ROUND)
        if icon == 'pause':
            cr.rectangle(cx - s * 0.42, cy - s * 0.6, s * 0.32, s * 1.2)
            cr.rectangle(cx + s * 0.1, cy - s * 0.6, s * 0.32, s * 1.2)
            cr.fill()
        elif icon == 'play':
            cr.move_to(cx - s * 0.4, cy - s * 0.6)
            cr.line_to(cx + s * 0.55, cy)
            cr.line_to(cx - s * 0.4, cy + s * 0.6)
            cr.close_path()
            cr.fill()
        elif icon == 'gear':
            # engranaje limpio: dientes trapezoidales + agujero central
            teeth = 7
            r_tip, r_base = s * 0.74, s * 0.54
            aw = (2 * math.pi / teeth) * 0.20
            cr.new_sub_path()
            first = True
            for i in range(teeth):
                a = 2 * math.pi * i / teeth - math.pi / 2
                for rad, ang in ((r_base, a - aw * 1.9), (r_tip, a - aw),
                                 (r_tip, a + aw), (r_base, a + aw * 1.9)):
                    px, py = cx + rad * math.cos(ang), cy + rad * math.sin(ang)
                    if first:
                        cr.move_to(px, py)
                        first = False
                    else:
                        cr.line_to(px, py)
            cr.close_path()
            cr.set_line_width(1.5)
            cr.stroke()
            cr.arc(cx, cy, s * 0.26, 0, 2 * math.pi)
            cr.stroke()
        elif icon == 'chevL':
            cr.move_to(cx + s * 0.25, cy - s * 0.5)
            cr.line_to(cx - s * 0.25, cy)
            cr.line_to(cx + s * 0.25, cy + s * 0.5)
            cr.stroke()
        elif icon == 'chevR':
            cr.move_to(cx - s * 0.25, cy - s * 0.5)
            cr.line_to(cx + s * 0.25, cy)
            cr.line_to(cx - s * 0.25, cy + s * 0.5)
            cr.stroke()
        elif icon == 'close':
            cr.move_to(cx - s * 0.5, cy - s * 0.5)
            cr.line_to(cx + s * 0.5, cy + s * 0.5)
            cr.move_to(cx + s * 0.5, cy - s * 0.5)
            cr.line_to(cx - s * 0.5, cy + s * 0.5)
            cr.stroke()
        elif icon == 'restart':
            R = s * 0.5
            a0 = math.radians(-50)
            a1 = math.radians(230)
            cr.arc(cx, cy, R, a0, a1)
            cr.stroke()
            # punta de flecha en el extremo del arco (tangente)
            ex, ey = cx + R * math.cos(a1), cy + R * math.sin(a1)
            tang = a1 - math.pi / 2  # sentido horario
            hl = s * 0.36
            for da in (math.radians(32), math.radians(-32)):
                cr.move_to(ex, ey)
                cr.line_to(ex - hl * math.cos(tang + da), ey - hl * math.sin(tang + da))
            cr.stroke()
        cr.restore()

    # ── panel ────────────────────────────────────────────────────────────
    def _draw_panel(self, cr):
        m = self.model
        p = m.pomo
        w, h = self._panel_size()
        self._glass(cr, 0, 0, w, h, 24)
        color = self.accent()
        pad = 20
        y = 18
        # header (zona de arrastre)
        self.hit['panelDrag'] = (0, 0, w - 46, 56)
        draw_text(cr, 'ESTUDIO', pad, y - 2, 8.5, (color[0] * 0.75, color[1] * 0.6, color[2] * 0.7, 1.0),
                  weight=Pango.Weight.SEMIBOLD, spacing=2.8)
        draw_text(cr, 'Pomodoro', pad, y + 18, 18, (0.12, 0.14, 0.2, 0.92), bold=True)
        # botón cerrar
        cr.arc(w - 30, y + 11, 13, 0, 2 * math.pi)
        cr.set_source_rgba(1, 1, 1, 0.6)
        cr.fill()
        self.hit['closeBtn'] = (w - 46, y - 5, 32, 32)
        self._glyph(cr, 'close', w - 30, y + 11, 9)
        y += 48

        # tally en una píldora de cristal (como el original)
        cnt = (p.get('today') or {}).get('count', 0)
        tally = '🍅 %d hoy' % cnt
        tw = text_layout(cr, tally, 12, Pango.Weight.SEMIBOLD).get_pixel_size()[0]
        pw2 = tw + 26
        px2 = (w - pw2) / 2
        rounded_rect(cr, px2, y - 3, pw2, 23, 11.5)
        cr.set_source_rgba(1, 1, 1, 0.55)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.7)
        cr.set_line_width(0.6)
        cr.stroke()
        draw_text(cr, tally, 0, y + 8, 12, (0, 0, 0, 0.55),
                  weight=Pango.Weight.SEMIBOLD, cx=px2, cw=pw2)
        y += 30

        # dial
        cx = w / 2
        dial_r = self.DIAL_R
        cyc = y + dial_r + 6
        idle = p['phase'] == 'idle'
        paused = (not idle) and not p['running']
        total = m.duration_ms('focus' if idle else p['phase']) or 1
        rem = total if idle else m.remaining_ms()
        ring_col = (0, 0, 0, 0.18) if paused else color
        frac = self._ring(cr, cx, cyc, dial_r, 9, rem, total, ring_col)
        # tirador solo cuando hay fase activa (en reposo no hay tirador)
        if not idle:
            th = 2 * math.pi * frac
            hx, hy = cx + dial_r * math.sin(th), cyc - dial_r * math.cos(th)
            cr.arc(hx, hy, 7.5, 0, 2 * math.pi)
            cr.set_source_rgba(1, 1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgba(*(ring_col if len(ring_col) == 3 else color))
            cr.set_line_width(3)
            cr.stroke()
        # centro: tiempo + fase en MAYÚSCULAS espaciada (color de fase)
        tcol = (0, 0, 0, 0.35) if paused else (0.1, 0.11, 0.16, 0.92)
        draw_text(cr, fmt(rem), 0, cyc - 7, 34, tcol, bold=True, cx=0, cw=w)
        plbl = ('LISTO PARA ESTUDIAR' if idle
                else (LABELS[p['phase']] + ('' if p['running'] else ' · EN PAUSA')).upper())
        pcol = (0, 0, 0, 0.35) if paused else color
        draw_text(cr, plbl, 0, cyc + 22, 8.5, pcol,
                  weight=Pango.Weight.BOLD, spacing=0.8, cx=0, cw=w)
        self.hit['dial'] = (cx - dial_r - 8, cyc - dial_r - 8,
                            2 * (dial_r + 8), 2 * (dial_r + 8), cx, cyc)
        y = cyc + dial_r + 10

        # dots del ciclo
        every = p['settings']['longEvery']
        filled = p['cycle'] % every
        if filled == 0 and p['cycle'] > 0 and p['phase'] == 'long':
            filled = every
        dot_w = every * 15
        dx = cx - dot_w / 2 + 4
        for i in range(every):
            cr.arc(dx + i * 15, y, 4.2, 0, 2 * math.pi)
            if i < filled:
                cr.set_source_rgba(*color)
            else:
                cr.set_source_rgba(0, 0, 0, 0.12)
            cr.fill()
        y += 30

        # controles según modo
        y = self._draw_controls(cr, pad, y, w - 2 * pad)

        # ajustes
        y += 14
        self._draw_settings(cr, pad, y, w - 2 * pad)

    def _button(self, cr, name, x, y, w, h, label, kind='ghost', icon=None):
        color = self.accent()
        rad = 13
        if kind == 'primary':
            soft_shadow(cr, x, y, w, h, rad, spread=8, alpha=0.30, dy=3,
                        color=color)
            g = cairo.LinearGradient(0, y, 0, y + h)
            g.add_color_stop_rgba(0, min(1, color[0] + 0.10),
                                  min(1, color[1] + 0.10), min(1, color[2] + 0.10), 1)
            g.add_color_stop_rgba(1, color[0], color[1], color[2], 1)
            rounded_rect(cr, x, y, w, h, rad)
            cr.set_source(g)
            cr.fill()
            tcol = (1, 1, 1, 1)
        elif kind == 'danger':
            rounded_rect(cr, x, y, w, h, rad)
            cr.set_source_rgba(0.93, 0.33, 0.37, 0.13)
            cr.fill()
            tcol = (0.82, 0.22, 0.27, 1)
        else:
            rounded_rect(cr, x, y, w, h, rad)
            cr.set_source_rgba(1, 1, 1, 0.68)
            cr.fill_preserve()
            cr.set_source_rgba(0, 0, 0, 0.07)
            cr.set_line_width(1)
            cr.stroke()
            tcol = (0, 0, 0, 0.66)
        self.hit[name] = (x, y, w, h)
        if icon:
            self._glyph(cr, icon, x + w / 2, y + h / 2, 11)
        else:
            # auto-ajuste: reduce la fuente hasta que el texto quepa con margen
            bold = (kind == 'primary')
            weight = Pango.Weight.BOLD if bold else Pango.Weight.NORMAL
            avail = w - 14
            fs = 11.5
            while fs > 7.5:
                tw = text_layout(cr, label, fs, weight).get_pixel_size()[0]
                if tw <= avail:
                    break
                fs -= 0.5
            draw_text(cr, label, 0, y + h / 2, fs, tcol, weight=weight, cx=x, cw=w)
        return x + w

    def _draw_controls(self, cr, x, y, w):
        m = self.model
        p = m.pomo
        h = 46
        g = 8
        if p['phase'] == 'idle':
            half = (w - g) / 2
            self._button(cr, 'bStartFocus', x, y, half, h, 'Empezar enfoque', 'primary')
            self._button(cr, 'bStartBreak', x + half + g, y, half, h, 'Descanso', 'ghost')
        else:
            # [Pausar/Reanudar] [↻] [Saltar] [Terminar]
            restart_w, skip_w, stop_w = 40, 62, 84
            prim_w = w - (restart_w + skip_w + stop_w) - 3 * g
            bx = x
            if p['running']:
                bx = self._button(cr, 'bPause', bx, y, prim_w, h, 'Pausar', 'primary') + g
            else:
                bx = self._button(cr, 'bResume', bx, y, prim_w, h, 'Reanudar', 'primary') + g
            bx = self._button(cr, 'bRestart', bx, y, restart_w, h, '', 'ghost', icon='restart') + g
            bx = self._button(cr, 'bSkip', bx, y, skip_w, h, 'Saltar', 'ghost') + g
            self._button(cr, 'bStop', bx, y, stop_w, h, 'Terminar', 'danger')
        return y + h

    def _draw_settings(self, cr, x, y, w):
        m = self.model
        s = m.pomo['settings']
        # tarjeta blanca translúcida (como el original, NO tintada por fase)
        card_h = 228 + (118 if self.stats_open else 0)
        rounded_rect(cr, x - 8, y, w + 16, card_h, 18)
        cr.set_source_rgba(1, 1, 1, 0.5)
        cr.fill()
        draw_text(cr, 'AJUSTES', x, y + 14, 8.5, (0, 0, 0, 0.38),
                  weight=Pango.Weight.SEMIBOLD, spacing=2.4)
        yy = y + 28
        # 4 cajas numéricas en una fila (como el original): Enfoque/Corto/Largo/Cada
        labels = [('Enfoque', 'focus'), ('Corto', 'short'),
                  ('Largo', 'long'), ('Cada 🍅', 'longEvery')]
        gap = 7
        col_w = (w - 3 * gap) / 4
        for i, (lbl, key) in enumerate(labels):
            sx = x + i * (col_w + gap)
            draw_text(cr, lbl, 0, yy + 6, 9.5, (0, 0, 0, 0.5),
                      weight=Pango.Weight.SEMIBOLD, cx=sx, cw=col_w)
            self._numbox(cr, key, sx, yy + 16, col_w, s[key])
        yy += 58
        # checkboxes con texto completo (ajuste a 2 líneas si no cabe)
        avail = w - 2
        yy += self._check(cr, 's-chain', x, yy, 'Encadenar fases automáticamente',
                          s['chain'], avail) + 8
        yy += self._check(cr, 's-sound', x, yy, 'Alarma al terminar el enfoque y los descansos',
                          s['sound'], avail) + 10
        # fila de botones mini (texto completo)
        bw = (w - 16) / 3
        self._button(cr, 'bTestSound', x, yy, bw, 30, 'Probar alarma', 'ghost')
        self._button(cr, 'bResetCycle', x + bw + 8, yy, bw, 30, 'Reiniciar ciclo', 'ghost')
        self._button(cr, 'bPim', x + 2 * (bw + 8), yy, bw, 30, '🎺', 'ghost')
        yy += 38
        # estadísticas
        lbl = 'Ocultar estadísticas' if self.stats_open else 'Estadísticas de la semana'
        self._button(cr, 'bStats', x, yy, w, 30, lbl, 'ghost')
        yy += 40
        if self.stats_open:
            self._draw_stats(cr, x, yy, w)

    def _numbox(self, cr, key, x, y, w, value):
        h = 30
        rounded_rect(cr, x, y, w, h, 9)
        cr.set_source_rgba(1, 1, 1, 0.62)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.8)
        cr.set_line_width(0.7)
        cr.stroke()
        # valor centrado (dejando hueco al spinner de la derecha)
        draw_text(cr, str(value), 0, y + h / 2, 13.5, (0, 0, 0, 0.82), bold=True,
                  cx=x, cw=w - 13)
        # spinner ▴▾
        sx = x + w - 11
        cr.set_source_rgba(0, 0, 0, 0.45)
        cr.move_to(sx - 3.5, y + 11); cr.line_to(sx + 3.5, y + 11)
        cr.line_to(sx, y + 7); cr.close_path(); cr.fill()
        cr.move_to(sx - 3.5, y + 19); cr.line_to(sx + 3.5, y + 19)
        cr.line_to(sx, y + 23); cr.close_path(); cr.fill()
        self.hit['inc:' + key] = (x + w - 16, y, 16, h / 2)
        self.hit['dec:' + key] = (x + w - 16, y + h / 2, 16, h / 2)
        self.hit['num:' + key] = (x, y, w, h)   # para la rueda del ratón

    def _check(self, cr, name, x, y, label, on, avail):
        box = 18
        # texto con ajuste de línea (word-wrap) a 2 líneas si hace falta
        layout = PangoCairo.create_layout(cr)
        fd = Pango.FontDescription()
        fd.set_family(FONT_FAMILY)
        fd.set_size(int(11 * Pango.SCALE))
        layout.set_font_description(fd)
        layout.set_width(int((avail - box - 10) * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD)
        layout.set_text(label, -1)
        tw, th = layout.get_pixel_size()
        # casilla (alineada con la primera línea)
        rounded_rect(cr, x, y, box, box, 6)
        if on:
            cr.set_source_rgba(*self.accent())
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 1)
            cr.set_line_width(2.2)
            cr.set_line_cap(cairo.LineCap.ROUND)
            cr.set_line_join(cairo.LineJoin.ROUND)
            cr.move_to(x + 4, y + 9)
            cr.line_to(x + 7.6, y + 12.8)
            cr.line_to(x + 14, y + 5)
            cr.stroke()
        else:
            cr.set_source_rgba(1, 1, 1, 0.75)
            cr.fill_preserve()
            cr.set_source_rgba(0, 0, 0, 0.14)
            cr.set_line_width(1)
            cr.stroke()
        cr.save()
        cr.set_source_rgba(0, 0, 0, 0.62)
        cr.move_to(x + box + 10, y + (box - min(th, 18)) / 2 if th <= 18 else y)
        PangoCairo.show_layout(cr, layout)
        cr.new_path()
        cr.restore()
        hh = max(box, th)
        self.hit[name] = (x, y - 3, avail, hh + 6)
        return hh

    def _draw_stats(self, cr, x, y, w):
        m = self.model
        hist = m.pomo.get('history') or {}
        days = []
        for i in range(6, -1, -1):
            t = time.time() - i * 86400
            key = date_str(t)
            # tm_wday: 0=lunes..6=domingo → índice tipo getDay() (0=domingo)
            dow = 'DLMXJVS'[(time.localtime(t).tm_wday + 1) % 7]
            d = hist.get(key) or {'count': 0, 'focusMin': 0}
            days.append((dow, d, i == 0))
        mx = max([1] + [d[1]['count'] for d in days])
        bw = w / 7
        base_y = y + 72
        for i, (dow, d, today) in enumerate(days):
            bx = x + i * bw + bw / 2
            bh = (6 + 50 * d['count'] / mx) if d['count'] else 3
            rounded_rect(cr, bx - 7, base_y - bh, 14, bh, 4)
            if d['count']:
                cr.set_source_rgba(*self.accent())
            else:
                cr.set_source_rgba(0, 0, 0, 0.12)
            cr.fill()
            if d['count']:
                draw_text(cr, str(d['count']), 0, base_y - bh - 8, 9, (0, 0, 0, 0.6), cx=bx - 10, cw=20)
            draw_text(cr, dow, 0, base_y + 10, 9,
                      self.accent() if today else (0, 0, 0, 0.4), bold=today, cx=bx - 10, cw=20)
        tot = sum(d[1]['count'] for d in days)
        mins = sum(d[1].get('focusMin', 0) for d in days)
        hh, mm = mins // 60, mins % 60
        if tot:
            txt = '%d 🍅 esta semana · %s de enfoque' % (
                tot, ('%d h %d min' % (hh, mm)) if hh else ('%d min' % mm))
        else:
            txt = 'Aún no hay pomodoros esta semana'
        draw_text(cr, txt, 0, base_y + 28, 9.5, (0, 0, 0, 0.5), cx=x, cw=w)

    # ─────────────────────────── Entrada ────────────────────────────────
    def _at(self, name, px, py):
        r = self.hit.get(name)
        if not r:
            return False
        x, y, w, h = r[0], r[1], r[2], r[3]
        return x <= px <= x + w and y <= py <= y + h

    def on_press(self, _area, e):
        if e.button == 3:
            self.popup_menu(e)
            return True
        if e.button != 1:
            return False
        px, py = e.x - self.MARGIN, e.y - self.MARGIN   # coords del cristal
        # dial: un toque adelanta 15 min, una sola vez por pomodoro
        if self.panel_open and self.model.active() and self._at('dial', px, py):
            r = self.hit['dial']
            cx, cy = r[4], r[5]
            rad = math.hypot(px - cx, py - cy) / self.DIAL_R
            if rad >= 0.34:
                if self.model.advance_15():
                    self.refresh()
                return True
        # botones (press: recordamos para activar al soltar si no hubo arrastre)
        for name in self.hit:
            if name in ('panelDrag', 'dial'):
                continue
            if self._at(name, px, py):
                self._pending_btn = name
                return True
        self._pending_btn = None
        # arrastre de la ventana (pill completa o header del panel)
        drag_zone = 'panelDrag' if self.panel_open else None
        if self.panel_open and not self._at('panelDrag', px, py):
            return False
        wx, wy = getattr(self, '_winpos', None) or self.win.get_position()
        self._drag = {'x0': e.x_root, 'y0': e.y_root, 'wx': wx, 'wy': wy, 'moved': False}
        _dbg('press drag start wx,wy=%s getpos=%s' % ((wx, wy), self.win.get_position()))
        return True

    def on_leave(self, _area, _e):
        if self._hover:
            self._hover = False
            self._sync_fade()
        return False

    def on_motion(self, _area, e):
        if not self._hover:
            self._hover = True
            self._sync_fade()
        if self._drag:
            dx = e.x_root - self._drag['x0']
            dy = e.y_root - self._drag['y0']
            if not self._drag['moved'] and math.hypot(dx, dy) < 4:
                return True
            self._drag['moved'] = True
            nx, ny = int(self._drag['wx'] + dx), int(self._drag['wy'] + dy)
            self._drag['cur'] = (nx, ny)
            self.win.move(nx, ny)
            _dbg('motion move -> (%d,%d) getpos=%s' % (nx, ny, self.win.get_position()))
            return True
        return False

    def on_release(self, _area, e):
        if self._drag:
            moved = self._drag['moved']
            cur = self._drag.get('cur')
            self._drag = None
            _dbg('release moved=%s cur=%s getpos=%s' % (moved, cur, self.win.get_position()))
            if moved and cur:
                pos = {'x': int(cur[0]), 'y': int(cur[1])}
                if self.panel_open:
                    self.model.pos_panel = pos
                else:
                    self.model.pos_pill = pos
                self.model.save()
                return True
            # clic en la píldora sin arrastrar → abre el panel
            if not self.panel_open:
                self.toggle_panel()
                return True
        btn = getattr(self, '_pending_btn', None)
        if btn and self._at(btn, e.x - self.MARGIN, e.y - self.MARGIN):
            self._activate(btn)
        self._pending_btn = None
        return True

    def on_scroll(self, _area, e):
        if not self.panel_open:
            return False
        px, py = e.x - self.MARGIN, e.y - self.MARGIN
        up = (e.direction == Gdk.ScrollDirection.UP) or getattr(e, 'delta_y', 0) < 0
        down = (e.direction == Gdk.ScrollDirection.DOWN) or getattr(e, 'delta_y', 0) > 0
        if not (up or down):
            return False
        for key in ('focus', 'short', 'long', 'longEvery'):
            if self._at('num:' + key, px, py):
                cur = self.model.pomo['settings'][key]
                self.model.set_setting(key, cur + (1 if up else -1))
                self.refresh()
                return True
        return False

    def _activate(self, name):
        m = self.model
        if name == 'pp':
            m.resume() if not m.pomo['running'] else m.pause()
            self.refresh()
        elif name == 'pg':
            self.toggle_panel()
        elif name == 'ph':
            m.compact = not m.compact
            m.save()
            self.start_compact_anim()   # expansión horizontal animada
        elif name == 'closeBtn':
            self.toggle_panel()
        elif name == 'bStartFocus':
            m.start('focus'); self.refresh(resize=True)
        elif name == 'bStartBreak':
            m.start('short'); self.refresh(resize=True)
        elif name == 'bPause':
            m.pause(); self.refresh()
        elif name == 'bResume':
            m.resume(); self.refresh()
        elif name == 'bRestart':
            m.restart(); self.refresh()
        elif name == 'bSkip':
            m.skip(); self.refresh(resize=True)
        elif name == 'bStop':
            m.stop(); self.refresh(resize=True)
        elif name == 'bResetCycle':
            m.reset_cycle(); self.refresh()
        elif name == 'bTestSound':
            self.play_alarm()
        elif name == 'bPim':
            self.launch_pim()
        elif name == 'bStats':
            self.stats_open = not self.stats_open
            self.refresh(resize=True)
        elif name.startswith('inc:') or name.startswith('dec:'):
            key = name[4:]
            step = 1
            cur = m.pomo['settings'][key]
            m.set_setting(key, cur + (step if name.startswith('inc:') else -step))
            self.refresh()
        elif name == 's-chain':
            m.set_setting('chain', not m.pomo['settings']['chain']); self.refresh()
        elif name == 's-sound':
            m.set_setting('sound', not m.pomo['settings']['sound']); self.refresh()

    # ── foco / cierre / menú ─────────────────────────────────────────────
    def on_map(self, *_):
        # Cada vez que la ventana se (re)mapea, re-afirmar los hints: mutter los
        # pierde al re-mapear (hide/show del reposicionado). Incluye skip_taskbar
        # / skip_pager para que NO salga en la vista de Actividades ni en Alt+Tab.
        if self.win:
            self.win.set_keep_above(True)
            self.win.stick()
            self.win.set_skip_taskbar_hint(True)
            self.win.set_skip_pager_hint(True)
            gw = self.win.get_window()
            if gw:
                gw.set_keep_above(True)
        return False

    def on_focus_out(self, *_):
        # Ignora el focus-out inmediato tras abrir (lo dispara el hide/show del
        # re-mapeo) y mientras se anima o se arrastra: si no, el panel se
        # cerraría justo al abrirlo con un clic en la píldora.
        age = GLib.get_monotonic_time() - getattr(self, '_opened_at', 0)
        if age < 700000 or self._anim or self._drag or self._menu_open:
            return False
        if self.panel_open:
            self.toggle_panel()
        return False

    def on_delete_event(self, *_):
        # Ctrl+W accidental: con el panel plegado se ignora.
        return not self.panel_open

    def popup_menu(self, event):
        self._menu_open = True
        menu = Gtk.Menu()
        menu.connect('deactivate', self._menu_closed)
        t = Gtk.MenuItem(label='Abrir / plegar panel')
        t.connect('activate', lambda *_: self.toggle_panel())
        q = Gtk.MenuItem(label='Salir')
        q.connect('activate', lambda *_: self.quit())
        for it in (t, q):
            menu.append(it)
        menu.show_all()
        menu.popup_at_pointer(event)

    def _menu_closed(self, *_):
        GLib.timeout_add(300, lambda: (setattr(self, '_menu_open', False), False)[1])


def main():
    Notify.init('Pomodoro de estudio')
    PomodoroApp().run(None)


if __name__ == '__main__':
    main()
