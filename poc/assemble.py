#!/usr/bin/env python3
"""Fase 3+5 — regia e montaggio, pagina per pagina.

Applica a ogni clip grezza di poc/clips/pNN/ il trattamento del personaggio (pitch,
filtri, volume) definito in voices.json, poi concatena inserendo le pause previste e
normalizza il risultato.

Non serve la GPU: si puo' ritarare la regia e rilanciare questo script in pochi secondi.

Uso:
    poc/.venv/bin/python poc/assemble.py --page 41      una pagina
    poc/.venv/bin/python poc/assemble.py --all          tutte le pagine, una per una
    poc/.venv/bin/python poc/assemble.py --story        tutte le pagine in un file unico

La storia intera NON e' la concatenazione degli mp3 delle singole pagine: quelli sono gia'
normalizzati uno per uno, e rimetterli in fila farebbe saltare il volume a ogni pagina.
Si concatenano invece i pezzi lavorati e si normalizza una volta sola, alla fine.
"""

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from intonation import describe as measure_intonation

POC = Path(__file__).resolve().parent
SR = 24000  # frequenza di uscita del modello (uguale per XTTS-v2 e Chatterbox)


def run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"Comando fallito:\n  {' '.join(shlex.quote(c) for c in cmd)}\n{proc.stderr[-2000:]}")
    return proc


def script_path(page):
    return POC / "script" / f"p{page}.json"


def clips_dir(page):
    return POC / "clips" / f"p{page}"


def pagine_disponibili():
    """Le pagine per cui esiste uno script, in ordine di lettura."""
    return sorted(int(p.stem[1:]) for p in (POC / "script").glob("p*.json") if p.stem[1:].isdigit())


def pitch_ratio(src, preset, target_hz):
    """Fattore di trasposizione per portare la clip all'altezza voluta.

    Il 'pitch' del personaggio e' relativo alla voce reale di Mauro: 1.06 significa
    "il 6% sopra la sua voce", non "il 6% sopra quello che ha generato il modello".
    """
    wanted = target_hz * float(preset.get("pitch", 1.0))
    if not target_hz:
        return float(preset.get("pitch", 1.0))
    measured = measure_intonation(str(src))
    if measured is None:
        return float(preset.get("pitch", 1.0))   # clip troppo corta per misurare
    ratio = wanted / measured[0]
    # Trasporre a valle e' proprio cio' che rende metallica la voce: qui si interviene solo
    # per scarti percepibili e mai oltre i due semitoni. La correzione grossa l'ha gia' fatta
    # prepare_voice.sh sul riferimento, dove non lascia artefatti.
    if 0.965 < ratio < 1.035:          # meno di mezzo semitono: non si sente, non si tocca
        return 1.0
    return min(1.12, max(0.89, ratio))  # +/- 2 semitoni


def build_filter(preset, cleanup=(), source_eq=(), post_cleanup=()):
    """Catena ffmpeg per un personaggio: pulizia, pitch, carattere, volume, expander.

    La pulizia va per prima: applicata dopo, i filtri di carattere (saturazione del
    filtro radio, compressori sulle onomatopee) avrebbero gia' amplificato il fruscio.
    L'expander invece va per ultimo, cosi' abbassa anche il fondo che i compressori e
    l'EQ di presenza hanno appena rialzato.
    """
    chain = list(cleanup) + list(source_eq)
    pitch = float(preset.get("pitch", 1.0))
    if abs(pitch - 1.0) > 1e-3:
        # rubberband sposta l'altezza senza cambiare la durata; formant=preserved
        # evita l'effetto "voce da cartone animato" tenendo le formanti al loro posto.
        chain.append(f"rubberband=pitch={pitch:.4f}:formant=preserved:pitchq=quality")
    chain.extend(preset.get("filters", []))
    gain = float(preset.get("gain_db", 0.0))
    if abs(gain) > 1e-3:
        chain.append(f"volume={gain:.2f}dB")
    chain.extend(post_cleanup)
    chain.append(f"aresample={SR}")
    return ",".join(chain)


def pulisci_clip(src, dst, cfg):
    """Accorcia i vuoti interni e i silenzi ai bordi della clip generata.

    Chatterbox, sui testi con puntini di sospensione, ogni tanto si ferma per secondi in
    mezzo a una frase: "Qui parla il ranger... [2,3 s] ...Paperino!". La pipeline di XTTS
    lo correggeva gia' (collapse_gaps in synthesize.py) ed e' rimasta indietro nel cambio
    di modello. Qui sta in post, non nella sintesi, cosi' si ritara in pochi secondi e
    vale anche sulle clip gia' generate.

    Le pause del racconto le decide il montaggio: dentro la battuta servono solo respiri.
    Del vuoto originale se ne tiene un pezzo invece di tagliarlo netto, perche' un
    silenzio digitale in mezzo a una frase si sente come una giunta.
    """
    import numpy as np
    import soundfile as sf

    x, sr = sf.read(str(src))
    if x.ndim > 1:
        x = x.mean(1)

    w = max(int(sr * 0.025), 1)
    n = len(x) // w
    if n == 0:
        sf.write(str(dst), x, sr)
        return 0.0, 0.0
    rms = np.sqrt((x[:n * w] ** 2).reshape(n, w).mean(1))
    # soglia prudente: meglio lasciare un vuoto che mangiare una consonante debole
    sonoro = rms > max(rms.max() * 0.06, 10 ** (-45 / 20))
    if not sonoro.any():
        sf.write(str(dst), x, sr)
        return 0.0, 0.0

    # segmenti sonori, per poter riconoscere una coda spuria in fondo
    segmenti, run = [], 0
    for i, s in enumerate(list(sonoro) + [False]):
        if s:
            run += 1
        elif run:
            segmenti.append(((i - run) * w, i * w))
            run = 0

    # Coda spuria: il modello ogni tanto chiude la battuta, sta zitto, e poi piazza un
    # frammento forte tagliato di netto a fine file (il "long_tail" per cui Chatterbox
    # forza l'EOS). All'ascolto e' un colpo secco fra una battuta e l'altra. Si toglie solo
    # se e' corto, isolato da un silenzio e attaccato alla fine del file: una parola vera
    # dopo una pausa e' piu' lunga di cosi', e non va mangiata.
    coda_max = int(sr * cfg.get("coda_spuria_max_ms", 150) / 1000)
    coda_sil = int(sr * cfg.get("coda_silenzio_min_ms", 250) / 1000)
    coda_tolta = 0.0
    while len(segmenti) >= 2:
        s0, s1 = segmenti[-1]
        prec_fine = segmenti[-2][1]
        if (s1 - s0) <= coda_max and (s0 - prec_fine) >= coda_sil and (len(x) - s1) <= int(sr * 0.05):
            coda_tolta += (s1 - s0) / sr
            segmenti.pop()
        else:
            break

    bordo = int(sr * cfg.get("trim_edges_ms", 120) / 1000)
    primo = segmenti[0][0]
    ultimo = segmenti[-1][1]
    inizio = max(0, primo - bordo)
    fine = min(len(x), ultimo + bordo)

    max_gap = int(sr * cfg.get("max_gap_ms", 450) / 1000)
    keep = int(sr * cfg.get("keep_gap_ms", 260) / 1000)

    vuoti = [(a[1], b[0]) for a, b in zip(segmenti, segmenti[1:]) if b[0] - a[1] > max_gap]

    pezzi, cursore, tolto = [], inizio, 0
    for s0, s1 in vuoti:
        pezzi.append(x[cursore:s0])
        pezzi.append(x[s0:s0 + keep])   # un pezzo del silenzio vero, non digitale
        tolto += (s1 - s0) - keep
        cursore = s1
    pezzi.append(x[cursore:fine])
    y = np.concatenate(pezzi)

    # Dissolvenza ai bordi: il modello taglia la coda dell'ultima parola mentre sta ancora
    # sfumando, e attaccata alla battuta dopo si sente come uno scatto. Si applica SOLO se
    # la fine e' gia' quasi spenta: se la clip finisce forte e' una parola troncata sul
    # serio, e va lasciata evidente perche' check_clips la segnali e la sintesi la rifaccia.
    dissolvenza = int(sr * cfg.get("dissolvenza_ms", 15) / 1000)
    soglia_fine = cfg.get("dissolvenza_max_dbfs", -20.0)
    if dissolvenza and len(y) > 2 * dissolvenza:
        y[:dissolvenza] *= np.linspace(0.0, 1.0, dissolvenza)
        coda_rms = float(np.sqrt((y[-int(sr * 0.05):] ** 2).mean()))
        if 20 * np.log10(max(coda_rms, 1e-12)) < soglia_fine:
            y[-dissolvenza:] *= np.linspace(1.0, 0.0, dissolvenza)

    sf.write(str(dst), y, sr)
    return tolto / sr, coda_tolta


def silenzio(path, ms):
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"anullsrc=r={SR}:cl=mono", "-t", f"{ms/1000:.3f}",
         "-c:a", "pcm_s16le", str(path)])


def lavora_pagina(page, voices):
    """Regia clip per clip di una pagina. Ritorna i pezzi (clip e pause) in ordine."""
    path = script_path(page)
    if not path.exists():
        sys.exit(f"Manca {path}: la pagina {page} non e' ancora trascritta.")
    script = json.loads(path.read_text(encoding="utf-8"))

    defaults = voices["defaults"]
    speakers = voices["speakers"]
    type_overrides = voices.get("type_overrides", {})
    channels = voices.get("channels", {})
    pauses = voices["pauses_ms"]
    cleanup = voices.get("cleanup", {}).get("filters", [])
    post_cleanup = voices.get("cleanup", {}).get("post_filters", [])
    source_eq = voices.get("source_eq", {}).get("filters", [])
    target_hz = float(voices.get("pitch_target_hz", 0) or 0)
    if voices.get("pitch_handled_upstream"):
        # l'altezza l'ha gia' decisa il modello, intonando il riferimento: qui non si
        # trasporta piu' nulla, perche' e' la trasposizione a valle a suonare metallica
        target_hz = 0.0

    src_dir = clips_dir(page)
    work_dir = src_dir / "processed"
    work_dir.mkdir(parents=True, exist_ok=True)
    clip_cleanup = voices.get("clip_cleanup", {})

    pieces = []
    entries = script["entries"]
    for entry in entries:
        seq, speaker = entry["seq"], entry["speaker"]
        src = src_dir / f"{seq:02d}_{speaker}.wav"
        if not src.exists():
            sys.exit(f"Manca {src}: esegui prima poc/synthesize_chatterbox.py --page {page}")

        preset = {**defaults, **speakers.get(speaker, {})}
        override = type_overrides.get(entry["type"], {})
        # i filtri del tipo (es. sfx) si sommano a quelli del personaggio
        preset = {**preset, **{k: v for k, v in override.items() if k != "filters"}}
        preset["filters"] = list(preset.get("filters", [])) + list(override.get("filters", []))

        # Il canale e' come la voce arriva a chi ascolta, non chi la produce: nella pagina 42
        # la scena cambia stazione e dalla ricetrasmittente esce la voce di Paperino, non piu'
        # quella di Hilde. Quindi il filtro radio sta sulla battuta, non sul personaggio, e si
        # somma in coda ai filtri di carattere.
        canale = channels.get(entry.get("channel") or ("radio" if entry.get("radio") else ""), {})
        # 'exaggeration' e 'cfg_weight' del canale li ha gia' usati la sintesi: qui si
        # applicano solo volume e filtri
        if canale:
            preset["filters"] = preset["filters"] + list(canale.get("filters", []))
            preset["gain_db"] = float(preset.get("gain_db", 0.0)) + float(canale.get("gain_db", 0.0))

        preset = {**preset, "pitch": 1.0 if not target_hz and voices.get("pitch_handled_upstream")
                  else pitch_ratio(src, preset, target_hz)}

        dst = work_dir / f"{seq:02d}_{speaker}.wav"
        if clip_cleanup.get("attiva", True):
            ripulita = work_dir / f"{seq:02d}_{speaker}_pulita.wav"
            tolto, coda = pulisci_clip(src, ripulita, clip_cleanup)
            if tolto > 0.05 or coda:
                dettagli = []
                if tolto > 0.05:
                    dettagli.append(f"accorciati {tolto:.2f}s di vuoti")
                if coda:
                    dettagli.append(f"tolta una coda spuria di {coda*1000:.0f} ms")
                print(f"   seq {seq:2d}: {', '.join(dettagli)}", flush=True)
            src = ripulita
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
             "-af", build_filter(preset, cleanup, source_eq, post_cleanup),
             "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
        pieces.append(dst)

        # pausa da inserire dopo questa clip
        nxt = next((e for e in entries if e["seq"] == seq + 1), None)
        if nxt is None:
            ms = pauses["page_end"]
        elif entry["type"] == "title":
            ms = pauses["after_title"]
        elif entry["type"] == "credits":
            ms = pauses["after_credits"]
        elif nxt["panel"] != entry["panel"]:
            ms = pauses["panel_change"]
        else:
            ms = pauses["same_panel"]

        sil = work_dir / f"{seq:02d}_pause_{ms}.wav"
        silenzio(sil, ms)
        pieces.append(sil)

    return pieces


def monta(pieces, nome, work_dir):
    """Concatena i pezzi, normalizza una volta sola e scrive wav + mp3."""
    out_dir = POC / "out" / "pagine" if nome.startswith("p") and nome != "storia" else POC / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    listfile = work_dir / f"concat_{nome}.txt"
    # percorsi assoluti: per la storia intera i pezzi stanno in cartelle diverse
    listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in pieces), encoding="utf-8")

    raw = work_dir / f"raw_{nome}.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listfile), "-c", "copy", str(raw)])

    wav_out = out_dir / f"{nome}.wav"
    mp3_out = out_dir / f"{nome}.mp3"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "1",
         "-c:a", "pcm_s16le", str(wav_out)])
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_out),
         "-c:a", "libmp3lame", "-q:a", "2", str(mp3_out)])

    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(wav_out)],
                         capture_output=True, text=True).stdout.strip()
    print(f"OK  {mp3_out}  ({float(dur):.1f}s)")
    return wav_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", type=int, help="monta una sola pagina")
    ap.add_argument("--all", action="store_true", help="monta ogni pagina in un file separato")
    ap.add_argument("--story", action="store_true",
                    help="monta tutte le pagine in un unico file, normalizzato una volta sola")
    args = ap.parse_args()

    voices = json.loads((POC / "voices.json").read_text(encoding="utf-8"))
    pagine = pagine_disponibili()
    if not pagine:
        sys.exit("Nessuno script in poc/script/: niente da montare.")

    if args.page:
        pieces = lavora_pagina(args.page, voices)
        monta(pieces, f"p{args.page}", clips_dir(args.page) / "processed")
        return

    if args.story:
        # la pausa fra una pagina e l'altra e' gia' 'page_end', in coda a ogni pagina
        tutti = []
        for page in pagine:
            print(f"-- pagina {page}", flush=True)
            tutti.extend(lavora_pagina(page, voices))
        work = POC / "clips"
        monta(tutti, "storia", work)
        return

    if args.all:
        for page in pagine:
            print(f"-- pagina {page}", flush=True)
            pieces = lavora_pagina(page, voices)
            monta(pieces, f"p{page}", clips_dir(page) / "processed")
        return

    ap.error("scegli --page N, --all o --story")


if __name__ == "__main__":
    main()
