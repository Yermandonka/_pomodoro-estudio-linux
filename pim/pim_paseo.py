#!/usr/bin/env python3
"""Pim Pimling cruza caminando la pantalla y se va.

En camino: animaciones del cartel de ÁNIMO GERMÁN (sacarlo del
bolsillo, trompeta con confeti, guardarlo) con fotogramas dibujados en
las carpetas cartel_* — se activarán cuando haya PNGs ahí.

Ventana transparente, siempre encima, forzada a X11/XWayland igual que el
pomodoro. Solo la silueta de Pim captura clics (input shape desde el canal alfa);
el resto deja pasar todo. Si lo pinchas, explota en confeti.
"""
import math
import os
import random
import sys

# Imprescindible antes de importar Gtk: en GNOME Wayland solo las
# ventanas X11 admiten keep-above e input shape (igual que el pomodoro).
os.environ["GDK_BACKEND"] = "x11"

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf
import cairo
from pathlib import Path

SPRITE = 128         # alto lógico de Pim en px
JUMP = 80            # holgura vertical extra de la franja (y escala de
                     # los fotogramas: el lienzo se mapea a SPRITE+JUMP)
STRIP_H = SPRITE + JUMP + 40
SPEED = 80           # px lógicos por segundo
FPS = 24             # el arte es de 12fps; 24 interpola el movimiento con fluidez
                     # gastando ~20% menos que 30 (todas las duraciones y la
                     # velocidad se expresan en función de FPS → tiempo real igual)
BOOM_SECS = 2.4      # duración de la explosión de confeti
GROUND = STRIP_H + 2  # las suelas pisan el borde inferior exacto

PINK = (0.96, 0.76, 0.93)
MAROON = (0.42, 0.10, 0.15)
BLUE = (0.40, 0.40, 0.92)
YELLOW = (0.93, 0.86, 0.30)
WHITE = (1, 1, 1)
BLACK = (0.06, 0.06, 0.07)

CONFETTI_COLORS = [
    PINK, BLUE, YELLOW, (0.98, 0.98, 0.98),
    (0.95, 0.45, 0.55), (0.45, 0.85, 0.95), (0.60, 0.92, 0.50),
    (0.98, 0.65, 0.25), (0.75, 0.55, 0.98),
]


def _scribble(seed, pts=150):
    """Garabato caótico dentro del disco unidad (pupilas de Pim)."""
    rng = random.Random(seed)
    a = rng.uniform(0, 2 * math.pi)
    r = 0.2
    path = []
    for _ in range(pts):
        a += rng.uniform(0.35, 0.9)
        r = min(1.0, max(0.12, r + rng.uniform(-0.3, 0.32)))
        path.append((math.cos(a) * r, math.sin(a) * r))
    return path


SCRIBBLE_L = _scribble(7)
SCRIBBLE_R = _scribble(23)

# Ciclo de andar dibujado a mano: PNGs numerados en ./caminando/
# (fondo transparente, Pim mirando a la derecha, pies en el borde
# inferior del lienzo), en bucle mientras cruza la pantalla; si la
# carpeta está vacía se usa el Pim vectorial procedural.
BASE_DIR = Path(__file__).resolve().parent
FRAME_FPS = 12


def _load_frames(nombre):
    d = BASE_DIR / nombre
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.png")):
        try:
            out.append(GdkPixbuf.Pixbuf.new_from_file(str(p)))
        except Exception:
            pass
    return out


WALK_FRAMES = _load_frames("caminando")
CARTEL_SACAR = _load_frames("cartel_sacar")
CARTEL_LOOP = _load_frames("cartel_caminando")
CARTEL_TROMPETA = _load_frames("cartel_trompeta")
CARTEL_TROMPETA_LOOP = _load_frames("cartel_trompeta_caminando")
CARTEL_GUARDAR = _load_frames("cartel_guardar")
LOOP_SECS = 4.5      # andar con cartel entre transiciones (si hay bucle)


def _draw_frame(cr, pb, cx, ground, direction):
    """Pinta un fotograma anclado al suelo, centrado en cx, mirando
    según direction (los PNG miran a la derecha)."""
    k = (SPRITE + JUMP) / pb.get_height()
    cr.save()
    cr.translate(cx, ground)
    if direction == -1:
        cr.scale(-1, 1)
    cr.translate(-pb.get_width() * k / 2, -pb.get_height() * k)
    cr.scale(k, k)
    Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
    cr.paint()
    cr.restore()


def _jitter(seed, n=40):
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(n)]


J_HEAD = _jitter(3)
J_EYE1 = _jitter(11, 28)
J_EYE2 = _jitter(17, 28)


def _blob(cr, rx, ry, jit, amp):
    """Elipse de trazo tembloroso, como dibujada a mano."""
    n = len(jit)
    for i in range(n + 1):
        t = i / n * 2 * math.pi
        r = 1 + amp * jit[i % n]
        x, y = math.cos(t) * rx * r, math.sin(t) * ry * r
        if i == 0:
            cr.move_to(x, y)
        else:
            cr.line_to(x, y)
    cr.close_path()



class PimWalk(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_keep_above(True)
        self.stick()

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geo = monitor.get_geometry()
        self.screen_w = geo.width
        self.move(geo.x, geo.y + geo.height - STRIP_H)
        self.set_default_size(self.screen_w, STRIP_H)
        self.resize(self.screen_w, STRIP_H)

        self.direction = 1  # siempre de izquierda a derecha
        margin = SPRITE
        if self.direction == 1:
            self.x = -margin
            self.end_x = self.screen_w + margin
        else:
            self.x = self.screen_w + margin
            self.end_x = -margin
        self.phase = 0.0

        self.traveled = 0.0
        self.boom_t = None    # None = vivo; 0..1 = explosión de confeti

        # Número del cartel de ÁNIMO GERMÁN: sacar → (bucle) → trompeta
        # → (bucle) → guardar. Solo etapas con fotogramas; el bucle de
        # andar con cartel es opcional (carpeta cartel_caminando).
        self.etapas = []

        def etapa(frames, en_bucle=False):
            if frames:
                dur = (LOOP_SECS * FPS if en_bucle
                       else len(frames) * FPS / FRAME_FPS)
                self.etapas.append((frames, en_bucle, dur))

        etapa(CARTEL_SACAR)
        etapa(CARTEL_LOOP, True)
        etapa(CARTEL_TROMPETA)
        etapa(CARTEL_TROMPETA_LOOP, True)
        etapa(CARTEL_GUARDAR)
        self.show_at = abs(self.end_x - self.x) * random.uniform(0.20, 0.30)
        self.etapa_i = None   # índice de la etapa en curso
        self.etapa_tick = 0
        self.confetti = []

        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self.on_draw)
        self.add(self.area)

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("button-press-event", self.on_click)
        self.connect("realize", self.on_realize)
        self.connect("map-event", self.on_map)

    # ── input shape: solo Pim es clicable ────────────────────────────────

    def pixbuf_actual(self):
        """Fotograma dibujado que toca ahora, o None (Pim procedural)."""
        if self.etapa_i is not None:
            frames, bucle, _ = self.etapas[self.etapa_i]
            idx = int(self.etapa_tick * FRAME_FPS / FPS)
            idx = idx % len(frames) if bucle else min(idx, len(frames) - 1)
            return frames[idx]
        if WALK_FRAMES:
            idx = int(self.phase / 0.32 * FRAME_FPS / FPS)
            return WALK_FRAMES[idx % len(WALK_FRAMES)]
        return None

    def draw_escena(self, cr, cx):
        pb = self.pixbuf_actual()
        if pb is not None:
            _draw_frame(cr, pb, cx, GROUND, self.direction)
        else:
            self.draw_pim(cr, cx, GROUND, self.phase, self.direction)

    def apply_shape(self):
        if self.boom_t is not None:
            self.input_shape_combine_region(cairo.Region())
            return
        s = SPRITE / 128.0
        w = int(150 * s)
        for p in (WALK_FRAMES + CARTEL_SACAR + CARTEL_LOOP
                  + CARTEL_TROMPETA + CARTEL_TROMPETA_LOOP + CARTEL_GUARDAR):
            k = (SPRITE + JUMP) / p.get_height()
            w = max(w, int(p.get_width() * k) + 4)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, STRIP_H)
        c = cairo.Context(surf)
        self.draw_escena(c, w / 2)
        surf.flush()
        region = Gdk.cairo_region_create_from_surface(surf)
        region.translate(int(self.x) - w // 2, 0)
        self.input_shape_combine_region(region)

    def on_realize(self, *_):
        self.apply_shape()
        # Cursor de mano: solo se ve dentro del input shape, o sea, sobre Pim
        win = self.get_window()
        if win:
            cur = (Gdk.Cursor.new_from_name(win.get_display(), "pointer")
                   or Gdk.Cursor.new_for_display(win.get_display(),
                                                 Gdk.CursorType.HAND2))
            win.set_cursor(cur)

    def on_map(self, *_):
        # reafirmar tras mapear: mutter ignora lo pedido antes de crearla
        self.stick()
        self.set_keep_above(True)
        gdk_win = self.get_window()
        if gdk_win:
            gdk_win.stick()
        self.apply_shape()
        return False

    # ── explosión de confeti ─────────────────────────────────────────────

    def on_click(self, _w, _ev):
        if self.boom_t is not None:
            return True
        self.boom_t = 0.0
        s = SPRITE / 128.0
        cx = self.x
        cy = GROUND - 64 * s   # centro del cuerpo
        rng = random.Random()
        self.confetti = []
        for _ in range(140):
            ang = rng.uniform(0, 2 * math.pi)
            v = rng.uniform(60, 420)
            self.confetti.append({
                "x": cx + rng.uniform(-14, 14) * s,
                "y": cy + rng.uniform(-40, 40) * s,
                "vx": math.cos(ang) * v,
                "vy": math.sin(ang) * v - 160,
                "rot": rng.uniform(0, 2 * math.pi),
                "vrot": rng.uniform(-9, 9),
                "color": rng.choice(CONFETTI_COLORS),
                "w": rng.uniform(4, 9) * s,
                "h": rng.uniform(2.5, 5) * s,
            })
        self.apply_shape()
        return True

    # ── bucle de animación ───────────────────────────────────────────────

    def tick(self):
        if self.boom_t is not None:
            self.boom_t += 1.0 / (BOOM_SECS * FPS)
            dt = 1.0 / FPS
            for p in self.confetti:
                p["vy"] += 620 * dt          # gravedad
                p["vx"] *= 0.985             # roce
                p["x"] += p["vx"] * dt
                p["y"] += p["vy"] * dt
                p["rot"] += p["vrot"] * dt
            if self.boom_t >= 1.0:
                Gtk.main_quit()
                return False
            self.area.queue_draw()
            return True

        step = SPEED / FPS
        self.x += step * self.direction
        self.traveled += step
        self.phase += 0.32

        if self.etapas:
            if self.etapa_i is None:
                if self.traveled >= self.show_at:
                    self.etapa_i, self.etapa_tick = 0, 0
            else:
                self.etapa_tick += 1
                if self.etapa_tick >= self.etapas[self.etapa_i][2]:
                    self.etapa_i += 1
                    self.etapa_tick = 0
                    if self.etapa_i >= len(self.etapas):
                        self.etapa_i = None
                        self.etapas = []   # el número solo se hace una vez

        done = (self.direction == 1 and self.x > self.end_x) or (
            self.direction == -1 and self.x < self.end_x
        )
        if done:
            Gtk.main_quit()
            return False
        self.apply_shape()
        self.area.queue_draw()
        return True

    def on_draw(self, _widget, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        if self.boom_t is not None:
            self.draw_confetti(cr)
        else:
            self.draw_escena(cr, self.x)
        return False

    def draw_confetti(self, cr):
        t = self.boom_t
        # anillo del "pum" inicial
        if t < 0.22:
            k = t / 0.22
            cr.set_source_rgba(1, 1, 1, 0.7 * (1 - k))
            cr.set_line_width(6 * (1 - k) + 1)
            cy = GROUND - 64 * SPRITE / 128.0
            cr.arc(self.x, cy, 20 + 120 * k, 0, 2 * math.pi)
            cr.stroke()
        alpha = 1.0 if t < 0.72 else max(0.0, 1.0 - (t - 0.72) / 0.28)
        for p in self.confetti:
            cr.save()
            cr.translate(p["x"], p["y"])
            cr.rotate(p["rot"])
            # brillo de giro: el ancho aparente oscila
            w = p["w"] * (0.35 + 0.65 * abs(math.sin(p["rot"] * 1.7)))
            c = p["color"]
            cr.set_source_rgba(c[0], c[1], c[2], alpha)
            cr.rectangle(-w / 2, -p["h"] / 2, w, p["h"])
            cr.fill()
            cr.restore()

    # ── dibujo de Pim ────────────────────────────────────────────────────

    @staticmethod
    def draw_pim(cr, cx, ground, phase, direction):
        """Pim vectorial de respaldo (sin fotogramas dibujados)."""
        s = SPRITE / 128.0

        def leg_angles(off):
            ph_l = phase + off
            return (0.65 * math.sin(ph_l),
                    1.05 * max(0.0, math.sin(ph_l - 1.2)))

        # el cuerpo cabalga sobre la pierna apoyada: el pie más bajo
        # pisa siempre el borde y el rebote sale de las rodillas
        bots = []
        for off in (0.0, math.pi):
            t, k = leg_angles(off)
            bots.append(-34 + 12 * math.cos(t)
                        + 12 * math.cos(t + k) + 7)
        bob = (-1 - max(bots)) * s

        cr.save()
        cr.translate(cx, ground + bob)
        if direction == -1:
            cr.scale(-1, 1)
        cr.rotate(-0.05)  # pecho fuera, andar chulo de la serie

        LINE = 1.7 * s

        def outline(width=None):
            cr.set_source_rgb(*BLACK)
            cr.set_line_width(width or LINE)
            cr.stroke()

        def fill_outline(color, width=None):
            cr.set_source_rgb(*color)
            cr.fill_preserve()
            outline(width)

        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)

        # ── piernas: muslo + espinilla con rodilla, pasitos saltarines ──
        for leg_ph_off, side in ((0.0, 1), (math.pi, -1)):
            thigh, knee = leg_angles(leg_ph_off)
            cr.save()
            cr.translate(4 * s * side, -34 * s)
            cr.rotate(thigh)
            # pernera ancha del pantalón sobre el muslo
            cr.move_to(-9 * s, -3 * s)
            cr.curve_to(-10 * s, 4 * s, -9.5 * s, 10 * s, -8 * s, 15 * s)
            cr.line_to(8 * s, 15 * s)
            cr.curve_to(9.5 * s, 10 * s, 10 * s, 4 * s, 9 * s, -3 * s)
            cr.close_path()
            fill_outline(BLUE)
            cr.set_source_rgb(*BLACK)
            cr.set_line_width(LINE * 0.5)
            cr.move_to(-5 * s, 7 * s)
            cr.line_to(0, 8 * s)
            cr.stroke()
            # rodilla → espinilla
            cr.translate(0, 12 * s)
            cr.rotate(knee)
            cr.set_source_rgb(*PINK)
            cr.set_line_width(7.5 * s)
            cr.move_to(0, 1 * s)
            cr.line_to(0, 11 * s)
            cr.stroke()
            # pie: contra-giro para apoyarlo casi plano
            cr.translate(0, 12 * s)
            cr.rotate(-(thigh + knee) * 0.8)
            cr.save()
            cr.translate(2.5 * s, 1.5 * s)
            cr.scale(1.7, 1.0)
            cr.arc(0, 0, 5.5 * s, 0, 2 * math.pi)
            cr.restore()
            fill_outline(BLACK)
            cr.restore()

        # ── cadera del pantalón ──
        cr.move_to(-25 * s, -40 * s)
        cr.curve_to(-26.5 * s, -33 * s, -26 * s, -27 * s, -25 * s, -22 * s)
        cr.line_to(-2 * s, -22 * s)
        cr.line_to(0, -28 * s)
        cr.line_to(2 * s, -22 * s)
        cr.line_to(25 * s, -22 * s)
        cr.curve_to(26 * s, -27 * s, 26.5 * s, -33 * s, 25 * s, -40 * s)
        cr.close_path()
        fill_outline(BLUE)
        # bragueta y arrugas
        cr.set_source_rgb(*BLACK)
        cr.set_line_width(LINE * 0.5)
        cr.move_to(0, -28 * s)
        cr.line_to(1 * s, -35 * s)
        cr.stroke()
        cr.move_to(-18 * s, -28 * s)
        cr.line_to(-12 * s, -27 * s)
        cr.stroke()
        cr.move_to(12 * s, -27 * s)
        cr.line_to(18 * s, -28 * s)
        cr.stroke()

        # ── camisa blanca (más ancha abajo) ──
        cr.move_to(-19 * s, -70 * s)
        cr.curve_to(-24 * s, -62 * s, -26 * s, -50 * s, -25.5 * s, -38 * s)
        cr.line_to(25.5 * s, -38 * s)
        cr.curve_to(26 * s, -50 * s, 24 * s, -62 * s, 19 * s, -70 * s)
        cr.curve_to(10 * s, -76 * s, -10 * s, -76 * s, -19 * s, -70 * s)
        cr.close_path()
        fill_outline(WHITE)
        # tapeta, botones y arrugas
        cr.set_source_rgb(*BLACK)
        cr.set_line_width(LINE * 0.5)
        cr.move_to(2 * s, -72 * s)
        cr.line_to(3 * s, -42 * s)
        cr.stroke()
        for by in (-64, -56, -48):
            cr.arc(-1.5 * s, by * s, 1.4 * s, 0, 2 * math.pi)
            cr.fill()
        cr.move_to(-22 * s, -44 * s)
        cr.line_to(-15 * s, -45 * s)
        cr.stroke()
        cr.move_to(15 * s, -45 * s)
        cr.line_to(22 * s, -44 * s)
        cr.stroke()

        # ── cinturón con hebilla amarilla ──
        cr.rectangle(-25.5 * s, -42 * s, 51 * s, 7 * s)
        fill_outline(BLACK)
        cr.save()
        cr.translate(0, -38.5 * s)
        r = 2.5 * s
        hw, hh = 6 * s, 5.5 * s
        cr.move_to(-hw + r, -hh)
        cr.arc(hw - r, -hh + r, r, -math.pi / 2, 0)
        cr.arc(hw - r, hh - r, r, 0, math.pi / 2)
        cr.arc(-hw + r, hh - r, r, math.pi / 2, math.pi)
        cr.arc(-hw + r, -hh + r, r, math.pi, 1.5 * math.pi)
        cr.close_path()
        fill_outline(YELLOW)
        cr.set_source_rgb(*BLACK)
        cr.set_line_width(LINE * 0.5)
        cr.move_to(0, -2 * s)
        cr.line_to(0, 2 * s)
        cr.stroke()
        cr.restore()

        # ── brazos: manga abombada + brazo con codo + mano de 4 deditos ──
        for side in (1, -1):
            arm_ph = phase + (math.pi if side == 1 else 0.0)
            up_ang = 0.35 + 0.7 * math.sin(arm_ph)
            lo_ang = 0.5 + 0.3 * math.sin(arm_ph + 0.6)
            cr.save()
            cr.translate(20 * s * side, -64 * s)
            # manga blanca abombada que sobresale del hombro
            cr.save()
            cr.scale(1.15, 1.0)
            cr.arc(0, 0, 7 * s, 0, 2 * math.pi)
            cr.restore()
            fill_outline(WHITE, LINE * 0.8)
            cr.rotate(-up_ang * side)
            # brazo superior rosa
            cr.set_source_rgb(*PINK)
            cr.set_line_width(7.5 * s)
            cr.move_to(0, 3 * s)
            cr.line_to(0, 12 * s)
            cr.stroke()
            # codo → antebrazo
            cr.translate(0, 12 * s)
            cr.rotate(-lo_ang * side)
            cr.set_source_rgb(*PINK)
            cr.set_line_width(7 * s)
            cr.move_to(0, 0)
            cr.line_to(0, 9 * s)
            cr.stroke()
            # mano abierta: silueta negra + relleno rosa (contorno fácil)
            cr.translate(0, 11 * s)
            for color, palm, fw in ((BLACK, 5.3, 3.9), (PINK, 4.2, 2.6)):
                cr.set_source_rgb(*color)
                cr.arc(0, 0, palm * s, 0, 2 * math.pi)
                cr.fill()
                cr.set_line_width(fw * s)
                for fa in (-0.7, -0.25, 0.25, 0.7):
                    cr.save()
                    cr.rotate(fa)
                    cr.move_to(0, 2 * s)
                    cr.line_to(0, 8.5 * s)
                    cr.stroke()
                    cr.restore()
            cr.restore()

        # ── cabeza y cara enteras: cabecean con retardo al andar ──
        cr.save()
        cr.translate(2 * s, -92 * s)
        cr.rotate(-0.05 + 0.06 * math.sin(phase + 0.6))
        cr.translate(0, 1.4 * s * math.sin(2 * phase + 0.9))

        # cabezota con contorno tembloroso
        cr.save()
        cr.scale(1.16, 1.0)
        _blob(cr, 29 * s, 29 * s, J_HEAD, 0.02)
        cr.restore()
        fill_outline(PINK, LINE * 1.1)
        # papada/mentón que baja sobre la camisa
        cr.save()
        cr.translate(11 * s, 24 * s)
        cr.scale(1.2, 1.0)
        cr.arc(0, 0, 12 * s, 0, 2 * math.pi)
        cr.restore()
        cr.set_source_rgb(*PINK)
        cr.fill()
        cr.save()
        cr.translate(11 * s, 24 * s)
        cr.scale(1.2, 1.0)
        cr.arc(0, 0, 12 * s, -0.1 * math.pi, 0.9 * math.pi)
        cr.restore()
        outline(LINE * 1.1)
        # antenita de pelo
        cr.set_source_rgb(*BLACK)
        cr.set_line_width(LINE * 0.5)
        cr.move_to(-4 * s, -28 * s)
        cr.curve_to(-2 * s, -34 * s, -7 * s, -38 * s, -3 * s, -43 * s)
        cr.stroke()

        # ojazos: dos círculos blancos enormes casi tocándose
        eyes = ((-9 * s, -6 * s, 14.5 * s, J_EYE1, SCRIBBLE_L),
                (18 * s, -7 * s, 15 * s, J_EYE2, SCRIBBLE_R))
        for ex, ey, er, jit, _ in eyes:
            cr.save()
            cr.translate(ex, ey)
            _blob(cr, er, er, jit, 0.03)
            cr.restore()
            fill_outline(WHITE, LINE * 1.1)
        # pupilas: garabato denso
        cr.set_source_rgb(*BLACK)
        cr.set_line_width(1.15 * s)
        for ex, ey, er, _, scr in eyes:
            cr.save()
            cr.translate(ex, ey)
            pr = er * 0.72
            cr.move_to(scr[0][0] * pr, scr[0][1] * pr)
            for px, py in scr[1:]:
                cr.line_to(px * pr, py * pr)
            cr.stroke()
            cr.restore()

        # bocaza abierta con dientón
        cr.save()
        cr.translate(13 * s, 22 * s)
        cr.rotate(-0.32)
        cr.scale(1.15, 1.0)
        cr.arc(0, 0, 11.5 * s, 0, 2 * math.pi)
        cr.set_source_rgb(*MAROON)
        cr.fill_preserve()
        cr.set_source_rgb(*BLACK)
        cr.set_line_width(LINE)
        cr.stroke()
        # dientón colgando del labio superior
        cr.rectangle(-1 * s, -11.5 * s, 8 * s, 8.5 * s)
        cr.set_source_rgb(*WHITE)
        cr.fill_preserve()
        cr.set_source_rgb(*BLACK)
        cr.set_line_width(LINE * 0.5)
        cr.stroke()
        cr.restore()

        cr.restore()   # cabeza
        cr.restore()   # figura


def main():
    win = PimWalk()
    win.show_all()
    GLib.timeout_add(int(1000 / FPS), win.tick)
    # Prueba: explosión automática a los N segundos
    prueba = os.environ.get("PIM_EXPLOTA_EN")
    if prueba:
        GLib.timeout_add(int(float(prueba) * 1000),
                         lambda: (win.on_click(None, None), False)[1])
    # Cortafuegos: pase lo que pase, morir a los 120 s
    GLib.timeout_add_seconds(120, Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    sys.exit(main())
