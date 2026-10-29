#!/usr/bin/env python3
"""Pomodoro de estudio — escritorio (WebKitGTK).

Ejecuta la interfaz REAL de la extensión de Zen (content.js + background.js,
sin modificar) dentro de una ventana transparente que cubre el área de
trabajo y queda siempre encima de cualquier aplicación. Un shim (shim.js)
emula el API browser.*: el almacén va a un JSON en disco y las
notificaciones a libnotify.

La "input shape" X11 de la ventana se recorta SIEMPRE al rectángulo del
widget: los clics y el teclado fuera de la píldora/panel jamás tocan esta
ventana (nada de bloqueos invisibles). El "clic fuera pliega el panel" de
la extensión se traduce a escritorio como "al perder el foco se pliega".

En GNOME Wayland solo las ventanas X11 pueden fijarse "siempre encima" y
usar input shapes, por eso se fuerza XWayland (GDK_BACKEND=x11).
"""

import os
os.environ['GDK_BACKEND'] = 'x11'  # imprescindible antes de importar Gtk

import json
import subprocess
import sys
from pathlib import Path

import cairo
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
gi.require_version('Notify', '0.7')
gi.require_version('Gst', '1.0')
from gi.repository import Gtk, Gdk, GLib, WebKit2, Notify, Gst  # noqa: E402

# WM_CLASS = nombre del .desktop: la vista de actividades muestra su icono
GLib.set_prgname('pomodoro-estudio')

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(GLib.get_user_data_dir()) / 'pomodoro-estudio'
STORE_FILE = DATA_DIR / 'storage.json'
ICON_FILE = APP_DIR / 'icon.svg'


class PomodoroApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='dev.yermandonka.pomodoro.old')
        self.win = None
        self.webview = None
        self._store = None
        self._save_id = 0
        self._last_frame = None
        self._panel_open = False
        self._menu_open = False
        self._beats = None
        self.ucm = None
        self._notification = None
        self._player = None  # GStreamer nativo para la alarma
        self._pim_proc = None  # paseo de Pim lanzado desde el panel

    # ── ciclo de vida ─────────────────────────────────────────────────
    def do_activate(self):
        if self.win:
            # Relanzar la app equivale al clic en el icono de la barra:
            # abre/pliega el panel.
            self.run_js('window.__togglePanel && window.__togglePanel()')
            return
        self.build()

    def do_shutdown(self):
        self.flush_store()
        Gtk.Application.do_shutdown(self)

    def build(self):
        try:
            initial = json.loads(STORE_FILE.read_text())
        except (OSError, ValueError):
            initial = {}

        win = Gtk.ApplicationWindow(application=self)
        win.set_title('Pomodoro de estudio')
        win.set_decorated(False)
        # Fuera de la vista de actividades (Super) y de Alt+Tab — pero el
        # icono del dock sigue vivo: al pulsarlo la app recibe el foco (o se
        # relanza) y eso abre el panel.
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_focus_on_map(False)  # no robar el foco al arrancar sesión
        win.connect('focus-out-event', self.on_focus_out)
        win.connect('delete-event', self.on_delete_event)
        win.set_keep_above(True)     # respetado por mutter al ir vía XWayland
        win.stick()                  # visible en todos los escritorios
        screen = win.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            win.set_visual(visual)
        win.set_app_paintable(True)
        try:
            win.set_icon_from_file(str(ICON_FILE))
        except GLib.Error:
            pass

        # Cubre el área de trabajo del monitor principal (sin la barra de
        # GNOME; además, si igualara el monitor mutter la trataría como
        # ventana a pantalla completa).
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        wa = monitor.get_workarea()
        win.move(wa.x, wa.y)
        win.set_default_size(wa.width, wa.height)

        # ── Endurecimiento y techo de memoria ─────────────────────────
        try:
            # Si el proceso web pasa de este límite, WebKit lo mata y aquí
            # se recrea con el estado guardado: la RAM no crece sin freno.
            mps = WebKit2.MemoryPressureSettings.new()
            mps.set_memory_limit(350)  # MB
            # Contexto efímero: WebKit no escribe NADA en disco (ni HSTS,
            # ni caché, ni almacenes)
            ctx = WebKit2.WebContext(
                memory_pressure_settings=mps,
                website_data_manager=WebKit2.WebsiteDataManager(is_ephemeral=True))
        except (AttributeError, TypeError):
            ctx = WebKit2.WebContext.get_default()
        try:
            # Sin cachés de página/recursos en memoria
            ctx.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)
        except AttributeError:
            pass
        try:
            # Sandbox bubblewrap del proceso web: seccomp + namespaces
            # (reduce la superficie de ataque del kernel si WebKit cayera).
            ctx.set_sandbox_enabled(True)
        except Exception:
            pass  # en WebKitGTK modernos ya viene activado de serie
        if hasattr(ctx, 'add_path_to_sandbox'):
            try:
                ctx.add_path_to_sandbox(str(APP_DIR), True)  # solo lectura
            except Exception:
                pass
        ucm = WebKit2.UserContentManager()
        ucm.add_script(WebKit2.UserScript.new(
            'window.__initialStorage = %s;' % json.dumps(initial),
            WebKit2.UserContentInjectedFrames.TOP_FRAME,
            WebKit2.UserScriptInjectionTime.START, None, None))
        ucm.register_script_message_handler('host')
        ucm.connect('script-message-received::host', self.on_script_message)

        settings = WebKit2.Settings()
        # Solo file→file dentro del mismo origen; NADA de acceso universal
        # (permitiría a la página leer cualquier fichero del disco).
        settings.set_allow_file_access_from_file_urls(True)
        settings.set_media_playback_requires_user_gesture(False)
        settings.set_enable_write_console_messages_to_stdout(
            bool(os.environ.get('POMODORO_DEBUG')))
        # Aceleración por GPU: sin ella los degradados/sombras del panel se
        # dibujan por CPU a escala 2.2× y el arrastre va a tirones
        settings.set_hardware_acceleration_policy(
            WebKit2.HardwareAccelerationPolicy.ALWAYS)
        # Todo lo que el widget no usa, apagado
        for setter in ('set_enable_webgl', 'set_enable_media_stream',
                       'set_enable_html5_local_storage', 'set_enable_html5_database',
                       'set_enable_developer_extras'):
            if hasattr(settings, setter):
                try:
                    getattr(settings, setter)(False)
                except TypeError:
                    pass

        # Sin esto la alarma calla: la política de autoplay por defecto es
        # "solo sin sonido" e ignora media_playback_requires_user_gesture.
        try:
            policies = WebKit2.WebsitePolicies(
                autoplay=WebKit2.AutoplayPolicy.ALLOW)
            webview = WebKit2.WebView(web_context=ctx, user_content_manager=ucm,
                                      website_policies=policies)
        except (AttributeError, TypeError):
            webview = WebKit2.WebView(web_context=ctx, user_content_manager=ucm)
        webview.set_settings(settings)
        webview.set_background_color(Gdk.RGBA(0, 0, 0, 0))
        webview.connect('context-menu', self.on_context_menu)
        webview.connect('web-process-terminated', self.on_web_process_died)
        webview.connect('decide-policy', self.on_decide_policy)
        webview.connect('permission-request', self.on_permission_request)
        # Agujero negro de red: aunque algo intentara salir, no puede.
        dm = webview.get_website_data_manager()
        if hasattr(dm, 'set_network_proxy_settings'):
            try:
                dm.set_network_proxy_settings(
                    WebKit2.NetworkProxyMode.CUSTOM,
                    WebKit2.NetworkProxySettings.new('http://127.0.0.1:1', None))
            except (AttributeError, TypeError):
                pass
        webview.load_uri((APP_DIR / 'app.html').as_uri())
        self.ucm = ucm

        win.add(webview)
        win.show_all()
        self.win = win
        self.webview = webview
        # Hasta el primer informe del widget, la ventana no captura NINGÚN
        # clic (región vacía): invisible e inofensiva.
        GLib.idle_add(lambda: (win.input_shape_combine_region(cairo.Region()), False)[1])
        # Sondeo activo del rectángulo: no depende de que WebKit mantenga
        # vivos los temporizadores de la página.
        GLib.timeout_add(300, self.poll_frame)

    def run_js(self, code):
        if not self.webview:
            return
        try:
            self.webview.evaluate_javascript(code, -1, None, None, None, None, None)
        except (AttributeError, TypeError):
            self.webview.run_javascript(code, None, None, None)

    def poll_frame(self):
        if not self.webview:
            return True
        code = 'window.__frame ? window.__frame() : ""'
        try:
            self.webview.evaluate_javascript(code, -1, None, None, None,
                                             self.on_frame_poll, None)
        except (AttributeError, TypeError):
            self.webview.run_javascript(code, None, self.on_frame_poll_old, None)
        return True

    def on_frame_poll(self, webview, result, _data):
        try:
            value = webview.evaluate_javascript_finish(result)
            self.handle_frame_json(value.to_string())
        except GLib.Error:
            pass

    def on_frame_poll_old(self, webview, result, _data):
        try:
            js = webview.run_javascript_finish(result)
            self.handle_frame_json(js.get_js_value().to_string())
        except GLib.Error:
            pass

    def handle_frame_json(self, text):
        if not text or text in ('null', 'undefined'):
            return
        try:
            frame = json.loads(text)
        except ValueError:
            return
        self._beats = frame.get('beats')
        self._polls = getattr(self, '_polls', 0) + 1
        if os.environ.get('POMODORO_DEBUG') and self._polls % 20 == 0:
            print('beats:', self._beats, flush=True)
        self.apply_frame(frame)

    def on_web_process_died(self, webview, reason):
        # Si el proceso web muere, se recarga con el almacén ACTUAL (el
        # user script inicial quedó anticuado).
        print('WebKit web process terminado:', reason, flush=True)
        if self._store is not None and self.ucm:
            self.ucm.remove_all_scripts()
            self.ucm.add_script(WebKit2.UserScript.new(
                'window.__initialStorage = %s;' % json.dumps(self._store),
                WebKit2.UserContentInjectedFrames.TOP_FRAME,
                WebKit2.UserScriptInjectionTime.START, None, None))
        webview.reload()

    # ── política: la página jamás sale de app.html ni pide permisos ───
    def on_decide_policy(self, _webview, decision, dtype):
        app_uri = (APP_DIR / 'app.html').as_uri()
        if dtype == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
            decision.ignore()
            return True
        if dtype == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri()
            if uri != app_uri:
                decision.ignore()
                return True
        elif dtype == WebKit2.PolicyDecisionType.RESPONSE:
            uri = decision.get_response().get_uri()
            if not uri.startswith(APP_DIR.as_uri() + '/'):
                decision.ignore()
                return True
        return False

    def on_permission_request(self, _webview, request):
        request.deny()  # cámara, micro, geolocalización, notificaciones web…
        return True

    # ── mensajes desde la página (no fiarse: validar y acotar todo) ───
    def on_script_message(self, _ucm, result):
        try:
            text = result.get_js_value().to_string()
            if not text or len(text) > 512 * 1024:
                return
            data = json.loads(text)
            if not isinstance(data, dict):
                return
        except (ValueError, GLib.Error):
            return
        kind = data.get('type')
        if kind == 'storage':
            store = data.get('data')
            if not isinstance(store, dict):
                return
            self._store = store
            if self._save_id:
                GLib.source_remove(self._save_id)
            self._save_id = GLib.timeout_add(600, self.flush_store)
        elif kind == 'pim':
            # botón 🎺 del panel: un paseo de Pim (uno a la vez)
            if self._pim_proc is None or self._pim_proc.poll() is not None:
                try:
                    self._pim_proc = subprocess.Popen(
                        [sys.executable, str(APP_DIR / 'pim' / 'pim_paseo.py')],
                        cwd=str(APP_DIR / 'pim'))
                except OSError:
                    self._pim_proc = None
        elif kind == 'sound':
            self.play_alarm()
        elif kind == 'stopSound':
            self.stop_alarm()
        elif kind == 'notify':
            title = str(data.get('title', ''))[:200]
            # El cuerpo se interpreta como marcado en GNOME: escapar
            message = GLib.markup_escape_text(str(data.get('message', ''))[:500])
            try:
                # Un único objeto reutilizado: nada se acumula
                if self._notification is None:
                    self._notification = Notify.Notification.new(title, message, str(ICON_FILE))
                else:
                    self._notification.update(title, message, str(ICON_FILE))
                self._notification.show()
            except GLib.Error:
                pass

    # ── Alarma nativa (GStreamer) ─────────────────────────────────────
    def play_alarm(self):
        if self._player is None:
            self._player = Gst.ElementFactory.make('playbin', None)
            if self._player is None:
                return
            self._player.set_property('uri', (APP_DIR / 'alarm.wav').as_uri())
            bus = self._player.get_bus()
            bus.add_signal_watch()
            bus.connect('message', self._on_alarm_msg)
        self._player.set_state(Gst.State.NULL)   # rebobina si ya sonaba
        self._player.set_state(Gst.State.PLAYING)

    def stop_alarm(self):
        if self._player is not None:
            self._player.set_state(Gst.State.NULL)

    def _on_alarm_msg(self, _bus, msg):
        if msg.type in (Gst.MessageType.EOS, Gst.MessageType.ERROR):
            self._player.set_state(Gst.State.NULL)

    def flush_store(self):
        self._save_id = 0
        if self._store is not None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            os.chmod(DATA_DIR, 0o700)
            tmp = STORE_FILE.with_suffix('.tmp')
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as fh:
                fh.write(json.dumps(self._store))
            tmp.replace(STORE_FILE)
        return False

    def apply_frame(self, f):
        if not self.win:
            return
        # px CSS → px X11: con escalado fraccional el viewport de WebKit no
        # mide lo mismo que la ventana (p. ej. 1746 CSS sobre 3840 X11).
        alloc = self.win.get_allocation()
        try:
            iw, ih = float(f.get('iw') or 0), float(f.get('ih') or 0)
            sx = (alloc.width / iw) if iw > 0 else 1.0
            sy = (alloc.height / ih) if ih > 0 else 1.0
            x, y = int(f.get('x', 0) * sx), int(f.get('y', 0) * sy)
            w, h = int(f.get('w', 0) * sx) + 1, int(f.get('h', 0) * sy) + 1
        except (TypeError, ValueError):
            return
        # Acotar al tamaño de la ventana: la página no decide más que eso
        x = max(0, min(x, alloc.width))
        y = max(0, min(y, alloc.height))
        w = max(0, min(w, alloc.width - x))
        h = max(0, min(h, alloc.height - y))
        key = (bool(f.get('visible')), bool(f.get('panel')), x, y, w, h)
        if key == self._last_frame:
            return
        was_visible = bool(self._last_frame and self._last_frame[0])
        self._last_frame = key
        self._panel_open = bool(f.get('visible') and f.get('panel'))
        if f.get('visible'):
            m = 3  # margen para el borde del widget
            region = cairo.Region(cairo.RectangleInt(x - m, y - m, w + 2 * m, h + 2 * m))
        else:
            region = cairo.Region()  # oculto: nada de clics
        if os.environ.get('POMODORO_DEBUG'):
            print('frame:', f, '→ x11:', (x, y, w, h), 'escala:', round(sx, 3), flush=True)
        self.win.input_shape_combine_region(region)
        # Widget totalmente oculto = sin sesión activa y sin panel: la app
        # se cierra sola (Terminar + clic fuera o ×, petición del usuario).
        if was_visible and not f.get('visible'):
            GLib.idle_add(self.quit)

    # ── cierre ────────────────────────────────────────────────────────
    def on_delete_event(self, *_):
        # Ctrl+W es «cerrar ventana» en GNOME: al cerrar pestañas en
        # ráfaga el foco puede acabar aquí (siempre encima) y el atajo se
        # llevaría el pomodoro. Con el panel plegado se ignora el cierre;
        # salir de verdad: panel abierto + Ctrl+W, menú «Salir» o Terminar.
        return not self._panel_open

    # ── foco ──────────────────────────────────────────────────────────
    # OJO: nada de abrir el panel al RECIBIR foco — GNOME puede enfocar esta
    # ventana (sticky + encima) al cambiar de escritorio y el panel se
    # abriría solo. El panel se abre por clic en la píldora, relanzamiento
    # (instancia única) o menú contextual.
    def on_focus_out(self, *_):
        # Equivalente de escritorio al "clic fuera pliega el panel".
        if self._panel_open and not self._menu_open:
            self.run_js('window.__closePanel && window.__closePanel()')
        return False

    # ── menú contextual (clic derecho sobre el widget) ────────────────
    def on_context_menu(self, _webview, _menu, _event, _hit):
        self._menu_open = True  # que el menú no dispare el pliegue por foco
        menu = Gtk.Menu()
        menu.connect('deactivate', self.on_menu_closed)
        toggle = Gtk.MenuItem(label='Abrir / plegar panel')
        toggle.connect('activate', lambda *_: self.run_js('window.__togglePanel()'))
        quit_item = Gtk.MenuItem(label='Salir')
        quit_item.connect('activate', lambda *_: self.quit())
        for item in (toggle, quit_item):
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(None)
        return True  # sin menú de WebKit

    def on_menu_closed(self, *_):
        def clear():
            self._menu_open = False
            return False
        GLib.timeout_add(300, clear)


def main():
    Gst.init(None)
    Notify.init('Pomodoro de estudio')
    PomodoroApp().run(None)


if __name__ == '__main__':
    main()
