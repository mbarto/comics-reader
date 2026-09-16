#!/usr/bin/env python3
"""Misure oggettive sulle clip, per tarare la regia senza andare a orecchio alla cieca.

Riporta per ogni file tre numeri:
  SNR        rapporto tra parlato (90mo percentile) e finestra piu' silenziosa.
             Sotto i ~30 dB il fruscio si sente.
  2-4kHz     energia nella banda delle consonanti, rispetto al totale.
             E' l'indice di intelligibilita': piu' e' alto, piu' la voce e' nitida.
  decad.     millisecondi perche' il livello cali di 20 dB dopo la fine di una parola.
             E' l'indice di riverbero: piu' e' lungo, piu' si sente la stanza.

Uso:
    poc/.venv/bin/python poc/measure.py poc/clips/processed/*.wav
"""

import sys
from pathlib import Path

import numpy as np
import soundfile as sf


def _load(path):
    x, sr = sf.read(path)
    return (x if x.ndim == 1 else x.mean(1)), sr


def snr_db(x, sr):
    w = int(sr * 0.15)
    n = len(x) // w
    if n < 6:
        return None
    r = np.array([np.sqrt(np.mean(x[i*w:(i+1)*w] ** 2)) + 1e-12 for i in range(n)])
    db = 20 * np.log10(r)
    return float(np.percentile(db, 90) - db.min())


def presence_db(x, sr):
    """Energia 2-4 kHz sul totale, misurata solo sui tratti di parlato."""
    w = int(sr * 0.05)
    n = len(x) // w
    if n < 4:
        return None
    r = np.array([np.sqrt(np.mean(x[i*w:(i+1)*w] ** 2)) + 1e-12 for i in range(n)])
    keep = r > np.percentile(r, 55)
    seg = np.concatenate([x[i*w:(i+1)*w] for i in range(n) if keep[i]])
    S = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    fr = np.fft.rfftfreq(len(seg), 1 / sr)
    return float(10 * np.log10(S[(fr >= 2000) & (fr < 4000)].sum() / (S.sum() + 1e-12) + 1e-12))


def decay_ms(x, sr, drop_db=20):
    """Tempo mediano perche' il livello cali di drop_db dopo un picco di parlato."""
    w = int(sr * 0.010)
    n = len(x) // w
    if n < 40:
        return None, 0
    e = np.array([np.sqrt(np.mean(x[i*w:(i+1)*w] ** 2)) + 1e-12 for i in range(n)])
    db = 20 * np.log10(e)
    peak = np.percentile(db, 95)
    times, i = [], 2
    while i < n - 30:
        if db[i] > peak - 8 and db[i+1] < db[i]:
            start, j = db[i], i + 1
            while j < n - 1 and db[j] > start - drop_db and db[j] <= db[j-1] + 2:
                j += 1
            if db[j] <= start - drop_db:
                times.append((j - i) * 10)
                i = j + 5
                continue
        i += 1
    return (float(np.median(times)) if times else None), len(times)


def main():
    files = [f for f in sys.argv[1:] if "pause" not in f and "raw_concat" not in f]
    if not files:
        sys.exit(__doc__)

    print(f"{'file':<26} {'SNR':>7} {'2-4kHz':>8} {'decad.':>8}")
    rows = []
    for f in files:
        x, sr = _load(f)
        s, p = snr_db(x, sr), presence_db(x, sr)
        d, cnt = decay_ms(x, sr)
        rows.append((s, p, d))
        fmt = lambda v, u: f"{v:.1f}{u}" if v is not None else "n/d"
        print(f"{Path(f).name:<26} {fmt(s,''):>7} {fmt(p,''):>8} {fmt(d,'ms'):>8}")

    def avg(i):
        vals = [r[i] for r in rows if r[i] is not None]
        return np.mean(vals) if vals else float("nan")

    print(f"\n{'media':<26} {avg(0):7.1f} {avg(1):8.1f} {avg(2):6.0f}ms")


if __name__ == "__main__":
    main()
