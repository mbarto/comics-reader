#!/usr/bin/env python3
"""Dereverberazione WPE del campione vocale, prima del ritaglio delle finestre.

XTTS clona le condizioni acustiche del riferimento insieme al timbro: se la stanza in cui
e' stata fatta la registrazione ha delle riflessioni, tutta la lettura del fumetto suona
come se i personaggi fossero in quella stanza. Il denoise non serve a niente qui, perche'
il riverbero non e' rumore additivo ma una convoluzione del segnale con la risposta
all'impulso dell'ambiente.

WPE (Weighted Prediction Error) stima la coda riverberante dai ritardi precedenti e la
sottrae, lasciando il suono diretto.

Uso:
    poc/.venv/bin/python poc/dereverb.py ingresso.wav uscita.wav [--iterations 5] [--taps 12]
"""

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf
from nara_wpe.wpe import wpe
from nara_wpe.utils import stft, istft

# Parametri STFT: 512 campioni a 22.05 kHz sono ~23 ms, la finestra classica per il parlato.
STFT_OPTS = dict(size=512, shift=128)


def dereverb(x, iterations=5, taps=12, delay=3):
    """Applica WPE a un segnale mono.

    taps  = quanti ritardi usare per stimare la coda (piu' alti = code piu' lunghe stimate)
    delay = quanti frame saltare prima di iniziare a sottrarre, per non intaccare il
            suono diretto e le prime riflessioni, che danno naturalezza alla voce
    """
    Y = stft(x, **STFT_OPTS).transpose(1, 0)          # (frequenze, frame)
    Y = Y[None, ...]                                   # WPE vuole (canali, freq, frame)
    Z = wpe(Y, taps=taps, delay=delay, iterations=iterations, statistics_mode="full")
    z = istft(Z[0].transpose(1, 0), size=STFT_OPTS["size"], shift=STFT_OPTS["shift"])
    return z[:len(x)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--iterations", type=int, default=5)
    ap.add_argument("--taps", type=int, default=12)
    ap.add_argument("--delay", type=int, default=3)
    args = ap.parse_args()

    x, sr = sf.read(args.src)
    x = x if x.ndim == 1 else x.mean(1)
    z = dereverb(x.astype(np.float64), args.iterations, args.taps, args.delay)

    # WPE puo' alzare leggermente il livello: si riporta al picco di partenza
    peak_in, peak_out = np.max(np.abs(x)), np.max(np.abs(z)) + 1e-12
    z = z * min(1.0, peak_in / peak_out)

    sf.write(args.dst, z.astype(np.float32), sr)
    print(f"{Path(args.src).name} -> {Path(args.dst).name}  "
          f"({len(z)/sr:.1f}s, taps={args.taps}, iter={args.iterations})")


if __name__ == "__main__":
    main()
