#!/usr/bin/env python3
"""Dal PDF scansionato di un albo alle singole pagine di fumetto, dritte e ritagliate.

Sostituisce poc/render_pages.sh, che funzionava solo per paperino-park-ranger.pdf: i ritagli
delle due pagine singole erano coordinate fisse trovate a occhio su quel PDF li'. Per la seconda
storia servivano altri numeri, e per la terza altri ancora - quindi qui si misura invece di
scrivere costanti.

    poc/.venv-estrazione/bin/python poc/render_pagine.py pages/paperone-copie-ripetizione.pdf \\
        --prima 67 --doppie 2-5 --rotazione 1=180 --uscita pages/render-paperone

COSA SI MISURA E COSA VA DETTO.

Va detto: quali fogli del PDF sono doppie pagine, di quanto e' ruotato ciascun foglio, e il numero
della prima pagina. Sono cose che si leggono in tre secondi guardando i provini e che nessuna
euristica indovina in modo affidabile (0 gradi e 180 gradi sono identici, geometricamente).

Si misura: dove sta la pagina dentro il foglio, e dove cade la piega.

 - LA PAGINA si trova dalla CORNICE GIALLA, cercata per tinta e non per colore assoluto: sul
   bordo che finisce dentro la piega il giallo e' in ombra, e un test su R/G/B lo perde.
   Quando si vede un bordo solo - succede proprio nella piega - la larghezza si deduce dal
   rapporto noto di una pagina di Topolino e si ancora al bordo che si vede.
 - LA PIEGA e' la colonna piu' scura nella fascia centrale, ricalcolata per ogni foglio: nel PoC
   si era gia' visto che NON sta a meta' del foglio, e tagliare a meta' mangiava l'ultima striscia
   della pagina di sinistra. Si lascia un po' di sovrapposizione: un filo della pagina accanto e'
   meno grave di un balloon tagliato.

Se la cornice non si trova (un albo stampato senza) lo dice e non tira a indovinare: meglio
fermarsi che scrivere dieci ritagli sbagliati.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Manca Pillow. Usa poc/.venv-estrazione/bin/python.")

ROOT = Path(__file__).resolve().parent.parent

# 2550x3507 a 300 dpi: il formato di una pagina di Topolino. Serve a dedurre la larghezza
# quando si vede un bordo solo, e a controllare che il ritaglio sia sensato.
RAPPORTO = 3507 / 2550          # 1.375
SOVRAPPOSIZIONE = 30            # px lasciati oltre la piega, come nel PoC


def intervallo(testo):
    """"2-5" -> {2,3,4,5};  "1,3" -> {1,3}."""
    fuori = set()
    for pezzo in testo.split(","):
        if "-" in pezzo:
            a, b = pezzo.split("-")
            fuori.update(range(int(a), int(b) + 1))
        elif pezzo.strip():
            fuori.add(int(pezzo))
    return fuori


def cornice(im, passo=4, frazione=0.45):
    """Il rettangolo della cornice gialla. Ritorna (x0, y0, x1, y1) o None."""
    hsv = im.convert("HSV")
    w, h = hsv.size
    W, H = max(1, w // passo), max(1, h // passo)
    p = hsv.resize((W, H)).load()
    col, rig = [0] * W, [0] * H
    for y in range(H):
        for x in range(W):
            tinta, sat, val = p[x, y]
            if 25 <= tinta <= 50 and sat > 110 and val > 90:   # giallo, anche in ombra
                col[x] += 1
                rig[y] += 1
    if not max(col) or not max(rig):
        return None

    def estremi(conteggi):
        soglia = max(conteggi) * frazione
        forti = [i for i, v in enumerate(conteggi) if v >= soglia]
        return min(forti) * passo, (max(forti) + 1) * passo

    x0, x1 = estremi(col)
    y0, y1 = estremi(rig)
    return x0, y0, x1, y1


def raddrizza_larghezza(x0, x1, y0, y1, larghezza_foglio, doppia):
    """Se si e' visto un bordo verticale solo, deduce l'altro dal rapporto noto.

    Succede quando un lato della pagina finisce nella piega del volume ed e' in ombra: la
    cornice c'e' ma il giallo e' troppo scuro per essere riconosciuto. L'altezza invece si
    misura sempre bene, e da quella si ricava la larghezza.
    """
    atteso = (y1 - y0) / RAPPORTO * (2 if doppia else 1)
    if abs((x1 - x0) - atteso) <= 0.12 * atteso:
        return x0, x1, False
    # La fascia trovata e' un bordo solo: si tiene e si mette la pagina dal lato in cui ci sta.
    if x1 + atteso <= larghezza_foglio:          # il bordo visto e' quello di SINISTRA
        return x0, round(x0 + atteso), True
    return max(0, round(x1 - atteso)), x1, True


def piega(im, x0, x1, y0, y1):
    """La colonna piu' scura nella fascia centrale: e' la piega, e non sta a meta'."""
    grigio = im.convert("L").crop((x0, y0, x1, y1))
    w, h = grigio.size
    riga = grigio.resize((w, 1)).load()
    lo, hi = int(w * 0.40), int(w * 0.60)
    buio = min(range(lo, hi), key=lambda x: riga[x, 0])
    return x0 + buio


def main():
    ap = argparse.ArgumentParser(description="Dal PDF di un albo alle pagine singole.")
    ap.add_argument("pdf")
    ap.add_argument("--uscita", required=True)
    ap.add_argument("--prima", type=int, required=True,
                    help="numero della prima pagina della storia")
    ap.add_argument("--doppie", default="",
                    help="quali FOGLI del PDF sono doppie pagine, es. 2-5")
    ap.add_argument("--rotazione", nargs="*", default=[],
                    help="gradi antiorari per foglio, es. 1=180 2-5=90 (di suo 0)")
    ap.add_argument("--dpi", type=int, default=300)
    args = ap.parse_args()

    if not shutil.which("pdftoppm"):
        sys.exit("Manca pdftoppm (pacchetto poppler-utils).")
    doppie = intervallo(args.doppie)
    rotazioni = {}
    for pezzo in args.rotazione:
        if not re.fullmatch(r"[\d,\-]+=-?\d+", pezzo):
            sys.exit(f"Rotazione non capita: {pezzo!r}. Si scrive cosi': 1=180 oppure 2-5=90")
        fogli, gradi = pezzo.split("=")
        for f in intervallo(fogli):
            rotazioni[f] = int(gradi)

    uscita = Path(args.uscita)
    uscita.mkdir(parents=True, exist_ok=True)
    numero = args.prima
    scritte, problemi = [], []

    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", str(args.dpi), "-png", args.pdf, f"{tmp}/f"],
                       check=True)
        fogli = sorted(Path(tmp).glob("f*.png"))
        print(f"{len(fogli)} fogli a {args.dpi} dpi\n")

        for indice, percorso in enumerate(fogli, 1):
            im = Image.open(percorso)
            gradi = rotazioni.get(indice, 0)
            if gradi:
                im = im.rotate(gradi, expand=True)
            doppia = indice in doppie

            bordi = cornice(im)
            if bordi is None:
                problemi.append(f"foglio {indice}: nessuna cornice gialla trovata")
                continue
            x0, y0, x1, y1 = bordi
            x0, x1, dedotta = raddrizza_larghezza(x0, x1, y0, y1, im.width, doppia)

            if doppia:
                taglio = piega(im, x0, x1, y0, y1)
                zone = [(x0, min(taglio + SOVRAPPOSIZIONE, x1)),
                        (max(x0, taglio - SOVRAPPOSIZIONE), x1)]
            else:
                zone = [(x0, x1)]

            for a, b in zone:
                pagina = im.crop((a, y0, b, y1))
                f = uscita / f"p{numero}.png"
                pagina.save(f)
                rapporto = pagina.height / pagina.width
                avviso = ""
                if not doppia and abs(rapporto - RAPPORTO) > 0.12:
                    avviso = f"  !! rapporto {rapporto:.2f}, atteso {RAPPORTO:.2f}"
                    problemi.append(f"p{numero}: ritaglio sospetto ({avviso.strip()})")
                print(f"  foglio {indice} -> p{numero}  {pagina.width}x{pagina.height}"
                      f"{'  (larghezza dedotta)' if dedotta else ''}{avviso}")
                scritte.append(f)
                numero += 1

    print(f"\n{len(scritte)} pagine in {uscita}")
    if problemi:
        print("\nda guardare a occhio:")
        for p in problemi:
            print(f"  - {p}")
        print("  (apri le immagini: un ritaglio sbagliato qui si porta dietro tutto il resto)")


if __name__ == "__main__":
    main()
