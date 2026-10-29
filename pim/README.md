# Pim paseo

Pim Pimling (Smiling Friends) cruza caminando la pantalla **al
principio de cada tercio de un pomodoro de trabajo y al completarse**
(nunca en los descansos): con un focus de 60 min, en los minutos 0, 20,
40 y al terminar. El paseo final solo sale si el pomodoro acaba de
forma natural, no si se salta o pausa.

El andar usa el ciclo dibujado de `caminando/` (12 PNG a 12 fps). En
cada paseo, al 20-30% del camino Pim hace el número del cartel de
**ÁNIMO GERMÁN**:

- `cartel_sacar/` — se saca el cartel del bolsillo (una vez)
- `cartel_caminando/` — camina con el cartel en alto (bucle de 4,5 s)
- `cartel_trompeta/` — trompeta con confeti sin soltar el cartel (una vez)
- `cartel_trompeta_caminando/` — camina tocando la trompeta con el
  cartel en alto (bucle de 4,5 s)
- `cartel_guardar/` — se lo guarda todo (una vez)

Los fotogramas están normalizados: recorte por píxeles sólidos
(alfa > 128), pies en el borde inferior, cuerpo (pies→cráneo)
reescalado a la mediana de su animación con lienzo = cuerpo/0,544
(así Pim mide lo mismo en pantalla en todos los juegos; el
renderizador escala cada lienzo a 208 px y ancla su borde inferior al
suelo), ojo derecho exactamente en el centro horizontal del lienzo
(ancla estable aunque el cartel ensanche el dibujo) y piel igualada
al rosa de `caminando` (HSV 223/107/251). Si alguna carpeta se vacía,
el código la salta; sin `caminando/` se usa el Pim vectorial de
respaldo dibujado con Cairo.

## Piezas

- `pim_paseo.py` — un paseo: ventana transparente, siempre encima
  (misma técnica X11/XWayland que `_pomodoro-estudio-linux`). Solo la
  **silueta exacta** de Pim captura clics: la región de entrada se genera
  cada fotograma desde el canal alfa del propio dibujo (~1,3 ms), y sobre
  él el cursor cambia a mano. **Si pinchas a Pim, explota en confeti.**
  Sprite de 128 px dibujado con Cairo (contornos temblorosos a mano,
  andar saltarín con rodillas y cabeceo estilo Smiling Friends),
  velocidad 80 px/s, siempre de izquierda a derecha, se cierra solo al salir de
  pantalla (cortafuegos a 120 s). Prueba de la explosión sin clic:
  `PIM_EXPLOTA_EN=5 python3 pim_paseo.py`.
- `pim_vigia.py` — demonio que lee
  `~/.local/share/pomodoro-estudio/storage.json` cada 5 s y lanza el paseo
  al empezar cada tercio del focus (arranque, 1/3 y 2/3) y otro al
  completarse (solo si el focus se vio vivo hasta su fin natural, con
  20 s de margen). Solo actúa si el proceso del pomodoro está abierto.
  Si el vigía arranca a mitad de sesión, los tercios ya pasados no se
  disparan retroactivamente. No toca nada del pomodoro.
- `~/.config/systemd/user/pim-vigia.service` — mantiene el vigía activo
  en cada sesión gráfica (`systemctl --user status pim-vigia`).

## Probar a mano

```sh
python3 pim_paseo.py            # un paseo suelto
journalctl --user -u pim-vigia  # log del vigía
```

Variables de prueba del vigía: `PIM_STORE`, `PIM_POLL`, `PIM_CMD`,
`PIM_SIN_PGREP` (ver cabecera de `pim_vigia.py`).
