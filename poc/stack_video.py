#!/usr/bin/env python3
"""Ricava un'immagine leggibile da un filmato che inquadra una pagina di fumetto.

Un singolo fotogramma di un video 704x576 non basta: il testo dei balloon sta su 5-6 pixel
di altezza ed e' illeggibile. Ma il libro e' tenuto a mano, quindi ogni fotogramma e'
spostato di una frazione di pixel rispetto agli altri: allineandone qualche decina e
mediandoli si abbatte il rumore di compressione e si recupera dettaglio vero.

Verificato su un testo mai trascritto (l'articolo sulla pagina accanto al fumetto): quello
che si legge dallo stack corrisponde alla scansione a 300 dpi.

Uso:
    poc/.venv/bin/python poc/stack_video.py FILMATO --da 1 --a 9 \
        --zona X,Y,LARGH,ALT --uscita out.png [--frames 40] [--fattore 4]

La zona e' in pixel sul fotogramma originale. Senza --zona si prende tutto il fotogramma.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


def nitidezza(a):
    """Varianza del laplaciano: alta quando i bordi sono netti, bassa se e' mosso."""
    lap = (-4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:])
    return lap.var()


def scostamento(rif_fft, c):
    """Di quanto e' spostato questo ritaglio rispetto al riferimento (correlazione di fase)."""
    C = np.fft.fft2(c)
    prod = rif_fft * np.conj(C)
    r = np.fft.ifft2(prod / (np.abs(prod) + 1e-9)).real
    dy, dx = np.unravel_index(np.argmax(r), r.shape)
    h, w = c.shape
    return (dy - h if dy > h // 2 else dy), (dx - w if dx > w // 2 else dx)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("filmato")
    ap.add_argument("--da", type=float, required=True, help="secondo di inizio")
    ap.add_argument("--a", type=float, required=True, help="secondo di fine")
    ap.add_argument("--zona", help="X,Y,LARGHEZZA,ALTEZZA sul fotogramma originale")
    ap.add_argument("--uscita", required=True)
    ap.add_argument("--frames", type=int, default=40, help="quanti fotogrammi impilare")
    ap.add_argument("--fattore", type=int, default=4, help="ingrandimento")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["ffmpeg", "-v", "error", "-i", args.filmato,
                        "-vf", f"select='between(t,{args.da},{args.a})',setpts=N/FRAME_RATE/TB",
                        "-vsync", "0", f"{tmp}/f%04d.png"], check=True)
        files = sorted(Path(tmp).glob("f*.png"))
        if not files:
            sys.exit("Nessun fotogramma in quell'intervallo.")

        if args.zona:
            x, y, w, h = (int(v) for v in args.zona.split(","))
        else:
            im = Image.open(files[0])
            x, y, w, h = 0, 0, im.width, im.height

        def ritaglio(p):
            im = Image.open(p).crop((x, y, x + w, y + h))
            colore = np.asarray(im.convert("RGB"), dtype=np.float64)
            return np.asarray(im.convert("L"), dtype=np.float64), colore

        # si tengono solo i fotogrammi piu' nitidi: uno mosso, mediato, sfoca tutti gli altri
        crops = sorted((( nitidezza(g), g, c) for g, c in (ritaglio(p) for p in files)),
                       key=lambda t: -t[0])[:args.frames]
        print(f"{len(files)} fotogrammi nell'intervallo, ne impilo {len(crops)}")

        # L'allineamento si calcola sulla luminanza, ma la media si fa sui tre canali: il
        # colore dei balloon dice chi parla (rosa Otis, giallo Bob, lilla Susy - vedi la
        # pagina 51), e in bianco e nero quell'informazione si perderebbe.
        rif_fft = np.fft.fft2(crops[0][1])
        W, H = w * args.fattore, h * args.fattore
        somma = np.zeros((H, W, 3))
        n = 0
        for _, g, c in crops:
            dy, dx = scostamento(rif_fft, g)
            if abs(dy) > h // 6 or abs(dx) > w // 6:
                continue          # troppo lontano: e' un'altra inquadratura, non un tremolio
            grande = np.asarray(Image.fromarray(c.astype(np.uint8)).resize((W, H), Image.LANCZOS),
                                dtype=np.float64)
            somma += np.roll(np.roll(grande, dy * args.fattore, 0), dx * args.fattore, 1)
            n += 1

        m = somma / n
        # maschera di contrasto: la media ammorbidisce, qui si riprendono i bordi
        piccola = Image.fromarray(np.clip(m, 0, 255).astype(np.uint8)).resize((w, h), Image.LANCZOS)
        sfocata = np.asarray(piccola.resize((W, H), Image.LANCZOS), dtype=np.float64)
        Image.fromarray(np.clip(m + 1.2 * (m - sfocata), 0, 255).astype(np.uint8)).save(args.uscita)
        print(f"impilati {n} fotogrammi -> {args.uscita} ({W}x{H}, a colori)")


if __name__ == "__main__":
    main()
