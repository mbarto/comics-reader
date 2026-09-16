#!/usr/bin/env python3
"""Controllo automatico delle clip: localizza i punti da riascoltare.

Non giudica la qualita' — quella la decide l'orecchio di Mauro. Serve a trasformare un
"c'e' qualche artefatto qua e la'" in un elenco di minuti e secondi da verificare, che
con 300 balloon e' l'unico modo per non riascoltare tutto.

Cerca: clip muta o incompleta (il modello si ferma a meta' battuta), troncata, in clipping,
con vuoti o code di silenzio, con ritmo anomalo, e con ripetizioni (lo stesso pezzo detto due
volte per un balloon solo).

Gli stessi controlli li usa synthesize_chatterbox.py per decidere se ritentare una presa
(vedi RIPARABILI_IN_POST: sui difetti che il montaggio sa gia' togliere non si ritenta).

Uso:
    poc/.venv/bin/python poc/check_clips.py 41 42
    poc/.venv/bin/python poc/check_clips.py            (tutte le pagine trascritte)
"""

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

POC = Path(__file__).resolve().parent

CODA_MAX_S = 0.60        # silenzio in fondo oltre il quale vale la pena guardare
VUOTO_MAX_S = 0.90       # pausa interna sospetta
TRONCATA_DBFS = -20.0    # livello negli ultimi 50 ms: sopra, la clip e' tagliata netta.
                         # Stessa soglia di 'dissolvenza_max_dbfs' in voices.json, e non e' un
                         # caso: sotto quel livello la parola sta gia' sfumando e il montaggio
                         # la chiude con una dissolvenza di 15 ms, quindi non e' un difetto ne'
                         # da segnalare ne' da rifare. Sopra, la parola e' tagliata a meta' e
                         # nessuna post-produzione la recupera.
# Caratteri al secondo del solo PARLATO (senza le pause interne), tarati sulla distribuzione
# delle 131 clip della storia: mediana 20,3, primo e novantanovesimo percentile 12,0 e 32,9.
# Le prime soglie erano state stimate su dieci clip di una pagina sola e su una misura che
# includeva le pause, quindi una battuta con i puntini di sospensione risultava "lenta"
# solo per via della pausa.
LENTA, VELOCE = 10.0, 34.0
INCOMPLETA = 45.0        # oltre questo ritmo il testo non e' stato detto: il modello si e'
                         # fermato a meta'. "Tsk! Faremo con la mia!" usciva a 66 car/s.
TESTO_MIN = 15           # sotto questa lunghezza il ritmo non e' misurabile: "Chi?" dura
                         # quanto vuole senza che questo voglia dire niente
CODA_SPURIA_MAX_S = 0.15   # stesse soglie di clip_cleanup in voices.json
CODA_SILENZIO_MIN_S = 0.25
RIPETIZIONE = 0.83       # somiglianza dell'inviluppo con se stesso a un ritardo: sopra questa
                         # soglia il modello ha ridetto lo stesso pezzo. Le clip pulite stanno
                         # a 0,80 o meno; i casi veri misurati stavano fra 0,84 e 0,95.
RIPETIZIONE_LAG_MIN = 0.40   # sotto questo ritardo si confrontano sillabe, non frasi

# Difetti che assemble.py toglie da solo: non sono un motivo per rifare la presa.
RIPARABILI_IN_POST = ("coda", "vuoto", "coda spuria")


def _db(x):
    return 20 * np.log10(max(float(x), 1e-12))


def segmenti_sonori(x, sr, finestra_ms=25):
    """Tratti di suono, in campioni, separati dai silenzi."""
    w = max(int(sr * finestra_ms / 1000), 1)
    n = len(x) // w
    if n == 0:
        return [], w
    rms = np.sqrt((x[:n * w] ** 2).reshape(n, w).mean(1))
    # soglia prudente: meglio lasciare un vuoto che mangiare una consonante debole
    sonoro = rms > max(rms.max() * 0.06, 10 ** (-45 / 20))
    segmenti, run = [], 0
    for i, s in enumerate(list(sonoro) + [False]):
        if s:
            run += 1
        elif run:
            segmenti.append(((i - run) * w, i * w))
            run = 0
    return segmenti, w


def _ripetizioni_nel_testo(testo):
    """Quante volte il testo ripete una parola di fila: 'Slap! Slap!' una, 'Ih, ih, ih!' due.

    Serve a non prendere per difetto le ripetizioni volute, che nelle onomatopee sono la norma.
    """
    import re
    parole = re.findall(r"\w+", testo.lower())
    return sum(1 for a, b in zip(parole, parole[1:]) if a == b)


def ripetizione(x, sr):
    """Il modello ha ridetto un pezzo? Si confronta l'inviluppo di energia con se stesso a
    vari ritardi: se una frase e' stata ripetuta, l'inviluppo si somiglia a quel ritardo.

    Non si guarda la durata: una ripetizione su un testo corto ("Beeeeeh!" detto due volte)
    resta dentro i tempi plausibili e passerebbe inosservata, ed e' proprio quello che e'
    successo nelle pagine 48 e 49.
    """
    h = max(int(sr * 0.02), 1)
    n = len(x) // h
    if n < 40:
        return 0.0, 0.0
    e = np.log(np.sqrt((x[:n * h] ** 2).reshape(n, h).mean(1)) + 1e-6)
    e = e - e.mean()
    best, lag_best = 0.0, 0.0
    for lag in range(int(RIPETIZIONE_LAG_MIN / 0.02), min(int(2.5 / 0.02), n - 20)):
        a, b = e[:-lag], e[lag:]
        if len(a) < 20:
            break
        c = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
        if c > best:
            best, lag_best = c, lag * 0.02
    return best, lag_best


def difetti(x, sr, testo, e_sfx):
    """Elenco dei difetti della clip. I nomi che iniziano per RIPARABILI_IN_POST li
    sistema il montaggio; gli altri richiedono un'altra presa."""
    if x.ndim > 1:
        x = x.mean(1)
    segmenti, w = segmenti_sonori(x, sr)
    if not segmenti:
        return ["muta"]

    trovati = []
    primo, ultimo = segmenti[0][0], segmenti[-1][1]

    coda = (len(x) - ultimo) / sr
    if coda > CODA_MAX_S:
        trovati.append(f"coda {coda:.2f}s")

    for a, b in zip(segmenti, segmenti[1:]):
        vuoto = (b[0] - a[1]) / sr
        if vuoto > VUOTO_MAX_S:
            trovati.append(f"vuoto {vuoto:.2f}s")

    # Una clip che finisce con del segnale e' tagliata. Due casi diversi: se l'ultimo
    # tratto e' corto e isolato e' una coda spuria, che il montaggio toglie; se e' lungo
    # e' una parola vera troncata, e l'unico rimedio e' rigenerare.
    fine_alta = _db(np.sqrt((x[-int(sr * 0.05):] ** 2).mean())) > TRONCATA_DBFS
    if fine_alta:
        s0, s1 = segmenti[-1]
        prec = segmenti[-2][1] if len(segmenti) >= 2 else 0
        spuria = ((s1 - s0) / sr <= CODA_SPURIA_MAX_S
                  and (s0 - prec) / sr >= CODA_SILENZIO_MIN_S
                  and (len(x) - s1) / sr <= 0.05)
        trovati.append("coda spuria" if spuria else "troncata")

    if np.max(np.abs(x)) >= 0.999:
        trovati.append("clipping")

    # il ritmo si misura sul parlato, non sulla clip: silenzi iniziali e finali lo
    # falserebbero, ed e' proprio quello che si sta cercando altrove
    # Il ritmo si misura sul solo parlato, sommando i tratti sonori: contare anche le pause
    # interne confonde "parla piano" con "fa una pausa a effetto", e soprattutto nasconde le
    # clip incomplete, dove il modello si ferma a meta' battuta e lascia silenzio.
    # Niente soglia minima di durata: era proprio quella a nascondere il caso peggiore, la
    # clip troppo corta per contenere il testo.
    parlato = sum(b - a for a, b in segmenti) / sr
    if not e_sfx and len(testo) >= TESTO_MIN and parlato > 0.05:
        cps = len(testo) / parlato
        if cps > INCOMPLETA:
            trovati.append(f"incompleta {cps:.0f} car/s")
        elif cps > VELOCE:
            trovati.append(f"veloce {cps:.1f} car/s")
        elif cps < LENTA:
            trovati.append(f"lenta {cps:.1f} car/s")

    return trovati


def difetti_grezza(x, sr, testo):
    """Difetti che si vedono solo sulla clip GREZZA, non su quella lavorata.

    Il montaggio accorcia i vuoti, e cosi' facendo cancella le tracce di due guasti diversi:
    la periodicita' che tradisce la ripetizione ("Beeeeeh! Beeeeeh!" scende da 0,86 a 0,55) e
    il silenzio in mezzo a una parola sola. Sono entrambi difetti di generazione: accorciare
    il silenzio non rimette insieme la parola, e l'unico rimedio e' rifare la presa.
    """
    if x.ndim > 1:
        x = x.mean(1)
    trovati = []

    somiglianza, lag = ripetizione(x, sr)
    if somiglianza > RIPETIZIONE and _ripetizioni_nel_testo(testo) == 0:
        trovati.append(f"ripetizione a {lag:.1f}s")

    # Dentro una o due parole un vuoto lungo non e' una pausa a effetto: e' il modello che si
    # perde a meta'. "Siamo..." usciva in tre tratti con 1,18 s di silenzio in mezzo.
    if len(testo.split()) <= 2:
        segmenti, _ = segmenti_sonori(x, sr)
        for a, b in zip(segmenti, segmenti[1:]):
            vuoto = (b[0] - a[1]) / sr
            if vuoto > VUOTO_MAX_S:
                trovati.append(f"spezzata, vuoto {vuoto:.2f}s")
                break
    return trovati


def da_rigenerare(elenco):
    """Solo i difetti che la post-produzione non sa togliere."""
    return [d for d in elenco if not d.startswith(RIPARABILI_IN_POST)]


def gravita(elenco):
    """Quanto e' compromessa una presa: serve a scegliere la meno peggio fra i tentativi."""
    peso = {"muta": 10, "incompleta": 8, "spezzata": 5, "ripetizione": 4, "troncata": 3,
            "clipping": 1}
    return sum(next((v for k, v in peso.items() if d.startswith(k)), 2) for d in da_rigenerare(elenco))


def difetti_file(path, testo, e_sfx):
    x, sr = sf.read(str(path))
    return difetti(x, sr, testo, e_sfx)


def pagine_disponibili():
    return sorted(int(p.stem[1:]) for p in (POC / "script").glob("p*.json") if p.stem[1:].isdigit())


def main():
    pagine = [int(a) for a in sys.argv[1:]] or pagine_disponibili()
    voices = json.loads((POC / "voices.json").read_text(encoding="utf-8"))
    pause = voices["pauses_ms"]
    segnalate = 0

    for page in pagine:
        script = json.loads((POC / "script" / f"p{page}.json").read_text(encoding="utf-8"))
        entries = script["entries"]
        work = POC / "clips" / f"p{page}" / "processed"
        print(f"--- pagina {page}")
        t = 0.0
        for entry in entries:
            nome = f"{entry['seq']:02d}_{entry['speaker']}"
            path = work / f"{nome}.wav"
            if not path.exists():
                print(f"  {nome}: manca la clip lavorata")
                continue
            testo = entry.get("text_tts") or entry["text"]
            x, sr = sf.read(str(path))
            if x.ndim > 1:
                x = x.mean(1)
            trovati = difetti(x, sr, testo, entry["type"] == "sfx")
            grezza = POC / "clips" / f"p{page}" / f"{nome}.wav"
            if grezza.exists():
                g, gsr = sf.read(str(grezza))
                trovati += difetti_grezza(g, gsr, testo)
            if trovati:
                segnalate += 1
                print(f"  {int(t)//60}:{int(t)%60:02d}  {nome:<16} {', '.join(trovati):<26} "
                      f"{testo[:40]}")
            t += len(x) / sr

            # la pausa che assemble.py inserisce dopo questa clip, per tenere il conto giusto
            nxt = next((e for e in entries if e["seq"] == entry["seq"] + 1), None)
            if nxt is None:
                t += pause["page_end"] / 1000
            elif entry["type"] == "title":
                t += pause["after_title"] / 1000
            elif entry["type"] == "credits":
                t += pause["after_credits"] / 1000
            elif nxt["panel"] != entry["panel"]:
                t += pause["panel_change"] / 1000
            else:
                t += pause["same_panel"] / 1000

    print(f"\n{segnalate} clip da riascoltare." if segnalate else "\nNessuna anomalia.")


if __name__ == "__main__":
    main()
