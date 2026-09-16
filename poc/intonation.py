#!/usr/bin/env python3
"""Misura l'escursione dell'intonazione, cioe' quanto la voce "canta" mentre parla.

XTTS clona dal riferimento anche la prosodia, non solo il timbro: se la registrazione di
riferimento e' letta in modo piatto, tutta la lettura del fumetto suonera' piatta. Questo
difetto non si vede in nessuna delle altre misure (SNR, presenza, riverbero), che sono
tutte spettrali.

Stima F0 per autocorrelazione su finestre da 40 ms e riporta:
  F0 mediana      l'altezza media della voce
  escursione      deviazione standard in semitoni sui frame sonori
  range 10-90%    ampiezza tra decimo e novantesimo percentile, in semitoni

Riferimenti indicativi per il parlato: sotto ~2 semitoni di escursione suona monotono,
2-3 e' una lettura neutra, 3-5 e' parlato espressivo, oltre 5 e' recitato.

Uso:
    poc/.venv/bin/python poc/intonation.py file.wav [altri.wav ...]
"""

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

F0_MIN, F0_MAX = 70.0, 350.0
FRAME_MS, HOP_MS = 40.0, 10.0


def f0_track(x, sr):
    """F0 per frame via autocorrelazione; None dove il frame non e' sonoro."""
    frame, hop = int(sr * FRAME_MS / 1000), int(sr * HOP_MS / 1000)
    lag_min, lag_max = int(sr / F0_MAX), int(sr / F0_MIN)

    peak = np.percentile(np.abs(x), 99) + 1e-12
    out = []
    for start in range(0, len(x) - frame, hop):
        seg = x[start:start + frame]
        rms = np.sqrt(np.mean(seg ** 2))
        if rms < peak * 0.05:          # troppo debole: silenzio o respiro
            continue
        seg = seg - seg.mean()
        ac = np.correlate(seg, seg, mode="full")[len(seg) - 1:]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        window = ac[lag_min:lag_max]
        if window.size == 0:
            continue
        lag = int(np.argmax(window)) + lag_min
        # Un picco di autocorrelazione basso significa suono non periodico
        # (consonante fricativa, rumore): non e' una nota, va scartato.
        if ac[lag] < 0.35:
            continue
        out.append(sr / lag)
    return np.array(out)


def describe(path):
    x, sr = sf.read(path)
    x = x if x.ndim == 1 else x.mean(1)
    f0 = f0_track(x.astype(np.float64), sr)
    if f0.size < 20:
        return None
    semitones = 12 * np.log2(f0 / np.median(f0))
    return (float(np.median(f0)), float(np.std(semitones)),
            float(np.percentile(semitones, 90) - np.percentile(semitones, 10)), f0.size)


def main():
    files = [f for f in sys.argv[1:] if "pause" not in f and "raw_concat" not in f]
    if not files:
        sys.exit(__doc__)

    print(f"{'file':<34} {'F0 mediana':>11} {'escursione':>11} {'range 10-90%':>13}")
    for f in files:
        d = describe(f)
        if d is None:
            print(f"{Path(f).name:<34} {'(troppo corto)':>11}")
            continue
        med, std, rng, n = d
        giudizio = ("monotono" if std < 2.0 else
                    "neutro" if std < 3.0 else
                    "espressivo" if std < 5.0 else "recitato")
        print(f"{Path(f).name:<34} {med:8.0f} Hz {std:8.2f} st {rng:10.2f} st   {giudizio}")


if __name__ == "__main__":
    main()
