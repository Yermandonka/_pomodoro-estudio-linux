# Pomodoro de estudio — versión de escritorio (Linux)

El pomodoro que nació como extensión de Zen, convertido en aplicación de
escritorio **con la misma interfaz exacta**: aquí corren los `content.js` y
`background.js` originales de la extensión, dentro de una ventana WebKitGTK
transparente que queda siempre encima de cualquier aplicación. Desde la
unificación (2026-09-23) **este es el único proyecto**: la extensión se
desinstaló de los navegadores y su código vive aquí.
Misma píldora (grip, anillo, pulso, modo compacto plegando el reloj), mismo
panel de cristal pastel (esfera, puntos del ciclo, ajustes, estadísticas de
la semana), misma alarma y mismas notificaciones.

## Cómo funciona

| Archivo | Papel |
|---|---|
| `pomodoro.py` | Anfitrión: ventana X11 transparente del tamaño del área de trabajo, siempre encima y en todos los escritorios. Persiste el almacén, lanza notificaciones (libnotify) y recorta la *input shape*. |
| `shim.js` | Emula lo justo del API `browser.*` de Firefox que usa el pomodoro de escritorio (storage, runtime y `tabs.sendMessage` para abrir/plegar el panel; notificaciones). También informa al anfitrión del rectángulo del widget y **enruta la alarma** (sustituye `window.Audio`). |
| `app.html` | Página transparente que carga `shim.js` + `background.js` + `content.js`. |
| `content.js`, `background.js`, `alarm.wav`, `icon.svg` | La interfaz y la lógica (heredadas de la extensión, ahora la ÚNICA copia: se editan aquí directamente). |

Trucos clave:

- **Siempre encima en GNOME Wayland**: imposible para apps Wayland nativas;
  mutter sí respeta `_NET_WM_STATE_ABOVE`/`STICKY` en ventanas X11, así que
  se fuerza `GDK_BACKEND=x11` (XWayland) antes de importar Gtk.
- **Inmune al Ctrl+W accidental**: Ctrl+W es «cerrar ventana» en GNOME y,
  al cerrar pestañas en ráfaga, el foco puede acabar en el pomodoro
  (siempre encima). Con el panel plegado la orden de cierre se ignora;
  salir de verdad: panel abierto + Ctrl+W, menú contextual «Salir», o
  Terminar (el widget oculto cierra la app solo).
- **Clics que atraviesan**: la ventana cubre el área de trabajo, pero su
  *input shape* X11 se recorta SIEMPRE al rectángulo del widget. Fuera de
  la píldora/panel, clics y teclado van a las apps de debajo: la ventana no
  puede bloquear el escritorio ni secuestrar el foco. El "clic fuera pliega
  el panel" de la extensión se traduce a escritorio como "al perder el foco
  se pliega".
- **El anfitrión sondea el rectángulo** cada 300 ms con
  `evaluate_javascript` (`window.__frame`), no con temporizadores de la
  página (se demostraron poco fiables para esto). Ojo con el **escalado
  fraccional**: los px CSS de WebKit no son px de ventana (aquí 1745 CSS
  sobre 1920 lógicos, dpr 2.2) — se convierte con `ancho_ventana /
  innerWidth` antes de aplicar la región.
- **Autocierre**: cuando el widget queda totalmente oculto (sin sesión
  activa y panel plegado — p. ej. tras «Terminar» y un clic fuera, o la ×),
  la app se cierra sola. Con sesión activa nunca se cierra: queda la
  píldora.
- **Vista de actividades / Alt+Tab**: la ventana NO aparece ahí
  (`skip_taskbar`), lo que también quita el punto de "en ejecución" del
  dock (en GNOME son la misma lista). El panel se abre con clic en la
  píldora, relanzando la app (icono anclado al dock) o con el menú
  contextual — nunca al recibir foco, porque GNOME enfoca esta ventana al
  cambiar de escritorio y el panel se abriría solo.
- **Shadow root cerrado**: `shim.js` intercepta `attachShadow` antes de que
  corra `content.js` para poder leer si el panel está abierto.
- El tamaño de la ventana es el del área de trabajo (no el monitor entero:
  mutter la trataría como pantalla completa y taparía la barra).

## Uso

- Menú de aplicaciones → **Pomodoro de estudio**, o `python3 pomodoro.py`.
- Al arrancar sin sesión activa se abre el panel (equivale al clic en el
  icono de la barra del navegador). **Relanzar la app abre/pliega el
  panel** (instancia única).
- **Clic derecho** sobre la píldora o el panel: menú con «Abrir / plegar
  panel» y «Salir».
- Estado en `~/.local/share/pomodoro-estudio/storage.json` (mismas claves
  que el `storage.local` de la extensión: `pomo`, `pomoPos`, `panelPos`,
  `pillCompact`). Sobrevive a reinicios; si el tiempo venció con la app
  cerrada, avanza de fase al arrancar.

### Autoarranque al iniciar sesión (opcional)

```sh
cp pomodoro-estudio.desktop ~/.config/autostart/
```

## Editar la interfaz

`alarm.wav` se reproduce directamente desde disco (el script que lo
generaba y los restos de empaquetado de la extensión de navegador se
borraron el 2026-09-24 al dar la app por terminada).

`content.js` (widget) y `background.js` (temporizador) se editan aquí
mismo y basta reiniciar la app. Siguen escritos contra el API `browser.*`
de Firefox (emulado por `shim.js`): si algún cambio usa APIs nuevas, habrá
que añadirlas al shim.

## Seguridad y recursos

La página corre con el mínimo privilegio posible:

- **Sin red**: proxy a un agujero negro (`127.0.0.1:1`) + política de
  navegación que solo permite `app.html` y recursos de esta carpeta; se
  bloquean ventanas nuevas. Nada puede cargarse ni exfiltrarse.
- **Sandbox bubblewrap** del proceso web de WebKit (namespaces + seccomp):
  si el motor cayera por un exploit, el proceso comprometido no ve el
  sistema de ficheros real ni puede usar la mayoría de llamadas al kernel.
- Sin `allow_universal_access_from_file_urls` (la página no puede leer
  otros ficheros del disco), sin WebGL, media-stream, localStorage ni
  developer extras; toda petición de permisos (cámara, micro, geolocalización)
  se deniega.
- **Contexto efímero**: WebKit no escribe nada en disco. El único fichero
  es `storage.json` (0600, directorio 0700), acotado por diseño: el
  historial se poda a 7 días (~500 bytes constantes).
- **RAM acotada**: `MemoryPressureSettings` con techo de 350 MB — si el
  proceso web lo supera, WebKit lo mata y el anfitrión lo recrea con el
  estado guardado. Caché en modo `DOCUMENT_VIEWER` (mínima) y objeto de
  notificación único reutilizado.
- El anfitrión valida todo mensaje de la página (tipos, tamaños con tope,
  cuerpo de notificaciones escapado) y acota los rectángulos de la región
  de clics al tamaño de la ventana.

## Limitaciones conocidas

- No se muestra sobre aplicaciones a pantalla completa (mutter pone el
  contenido a pantalla completa por encima de las ventanas ABOVE).
- Solo monitor principal.
- Consumo: ~0 % CPU en reposo, ~300 MB de RAM (WebKit).
- Es independiente de la extensión de Zen: cada una guarda su propio
  contador. Lo normal es usar solo una de las dos.
