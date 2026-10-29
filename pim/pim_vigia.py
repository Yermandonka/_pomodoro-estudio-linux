#!/usr/bin/env python3
"""Vigía de Pim: pasea al empezar cada tercio y al completarse el pomodoro.

Con un focus de 60 min, Pim sale en los minutos 0, 20 y 40, y una vez
más al terminar (solo si el pomodoro acaba de forma natural: nada de
paseo final si se salta o se pausa a mitad).

No modifica el pomodoro: lee el storage.json que la app ya escribe en
~/.local/share/pomodoro-estudio/ y solo actúa mientras el proceso del
pomodoro esté abierto. Los descansos no cuentan.

Variables de entorno para pruebas:
  PIM_STORE       ruta alternativa al storage.json
  PIM_POLL        segundos entre lecturas (por defecto 5)
  PIM_CMD         comando a lanzar en vez del paseo real
  PIM_SIN_PGREP   si está definida, no exige que el pomodoro esté abierto
"""
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

STORE = Path(os.environ.get(
    "PIM_STORE",
    Path.home() / ".local/share/pomodoro-estudio/storage.json",
))
POLL = float(os.environ.get("PIM_POLL", "5"))
ARRANQUE_MS = 30_000    # tercios ya pasados al arrancar: no dispararlos
GRACE_MS = 20_000       # margen para el paseo final tras acabar la fase

PIM = Path(__file__).resolve().parent / "pim_paseo.py"
CMD = (shlex.split(os.environ["PIM_CMD"])
       if os.environ.get("PIM_CMD")
       else [sys.executable, str(PIM)])

# Al COMPLETARSE el pomodoro se HIBERNA el equipo (apagado total, S4),
# tras un margen corto para que dé tiempo a ver el paseo final de Pim.
SUSPEND_DELAY = float(os.environ.get("PIM_SUSPEND_DELAY", "5"))  # s antes de hibernar


def pomodoro_abierto():
    if os.environ.get("PIM_SIN_PGREP"):
        return True
    return subprocess.run(
        ["pgrep", "-f", "_pomodoro-estudio-linux/pomodoro.py"],
        stdout=subprocess.DEVNULL,
    ).returncode == 0


def lanzar():
    subprocess.Popen(CMD, start_new_session=True)


def al_completar():
    """Hiberna el equipo tras SUSPEND_DELAY, en un proceso desacoplado
    para no frenar el bucle del vigía. PIM_SIN_BLOQUEO lo desactiva
    (útil en pruebas)."""
    if os.environ.get("PIM_SIN_BLOQUEO"):
        return
    subprocess.Popen(
        ["bash", "-c", f"sleep {SUSPEND_DELAY}; loginctl lock-session; sleep 1; systemctl suspend"],
        start_new_session=True,
    )


def main():
    fired = set()      # (endsAt, indice_de_paseo)
    vistos = set()     # sesiones ya inicializadas
    ultima = None      # [endsAt, ultima_vez_vista_viva] del último focus

    while True:
        time.sleep(POLL)
        if not pomodoro_abierto():
            continue
        try:
            pomo = json.loads(STORE.read_text()).get("pomo") or {}
        except (OSError, ValueError):
            continue

        now = time.time() * 1000
        phase = pomo.get("phase")
        ends = pomo.get("endsAt")

        if phase == "focus" and pomo.get("running") and ends:
            focus_ms = (pomo.get("settings") or {}).get("focus", 25) * 60_000
            start = ends - focus_ms
            # principio de cada tercio: arranque, 1/3 y 2/3 del focus
            tercios = [start, start + focus_ms / 3, start + 2 * focus_ms / 3]
            if ends not in vistos:
                vistos.add(ends)
                # arranque a mitad de sesión: los tercios ya muy pasados
                # se dan por hechos, sin paseo retroactivo
                for i, t in enumerate(tercios):
                    if now > t + ARRANQUE_MS:
                        fired.add((ends, i))
            for i, t in enumerate(tercios):
                if now >= t and (ends, i) not in fired:
                    fired.add((ends, i))
                    lanzar()
            if ultima and ultima[0] == ends:
                ultima[1] = now
            else:
                ultima = [ends, now]

        # Paseo final al COMPLETARSE el pomodoro: cuando llega ese
        # momento la fase ya ha saltado al descanso, así que se mira
        # fuera del bloque focus. Solo cuenta si el focus se vio vivo
        # hasta justo antes de su fin natural (nada de paseo si se
        # saltó o pausó a mitad) y dentro del margen de gracia.
        if ultima:
            u_ends, visto = ultima
            if now >= u_ends and (u_ends, 3) not in fired:
                fired.add((u_ends, 3))
                if (phase != "focus"
                        and visto >= u_ends - GRACE_MS
                        and now <= u_ends + GRACE_MS):
                    lanzar()
                    al_completar()

        # poda para que los sets no crezcan sin límite
        if len(fired) > 500:
            corte = now - 86_400_000
            fired = {k for k in fired if k[0] > corte}
            vistos = {e for e in vistos if e > corte}


if __name__ == "__main__":
    main()
