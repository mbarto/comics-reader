#!/usr/bin/env python3
"""Fase 4 — sintesi delle clip con XTTS-v2 clonando la voce di riferimento.

Legge poc/script.json e poc/voices.json, produce una clip WAV grezza per ogni balloon
in poc/clips/. Qui si applica solo la velocita' di lettura ('speed'), perche' e' un
parametro della sintesi; pitch, filtri e volume li applica assemble.py, cosi' si puo'
ritarare la regia senza rifare la sintesi sulla GPU.

Uso:
    poc/.venv/bin/python poc/synthesize.py [--only SEQ [SEQ ...]] [--cpu]


⚠️ SUPERATO dal giro 10: la sintesi si fa con synthesize_chatterbox.py. Questo script
legge ancora il vecchio layout a pagina singola (poc/script.json, poc/clips/*.wav), che
non esiste piu': va adattato a poc/script/pNN.json prima di poterlo rieseguire. Resta
come riferimento di come era fatta la sintesi con XTTS-v2.
"""

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("COQUI_TOS_AGREED", "1")  # XTTS-v2 e' sotto licenza CPML

POC = Path(__file__).resolve().parent
MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
LANGUAGE = "it"
SEED = 1234
MAX_ATTEMPTS = 4  # tentativi contro loop e prese rumorose di XTTS
MIN_SNR_DB = 30.0  # sotto questa soglia la presa viene rifatta


def load_model(device):
    """Scarica (al primo avvio) e carica XTTS-v2 con l'API di basso livello.

    Si usa Xtts direttamente invece di TTS.api perche' cosi' i latenti del parlante
    si calcolano una volta sola e vengono riusati per tutte le clip: e' piu' veloce
    e da' un timbro piu' costante tra un balloon e l'altro.
    """
    import torch
    from TTS.tts.configs.xtts_config import XttsConfig
    from TTS.tts.models.xtts import Xtts
    from TTS.utils.manage import ModelManager

    print(f"[1/4] modello {MODEL_NAME}...", flush=True)
    model_path, _, _ = ModelManager().download_model(MODEL_NAME)
    model_path = Path(model_path)

    config = XttsConfig()
    config.load_json(str(model_path / "config.json"))
    model = Xtts.init_from_config(config)
    model.load_checkpoint(config, checkpoint_dir=str(model_path), eval=True)
    model.to(device)
    torch.manual_seed(SEED)
    return model


def trim_silence(wav, sr=24000, thresh_ratio=0.01, pad_ms=60):
    """Taglia il silenzio iniziale e finale generato da XTTS.

    Le pause tra i balloon le mette assemble.py in modo calibrato: le code di silenzio
    della sintesi, che variano da clip a clip, falserebbero il ritmo del montaggio.
    """
    import numpy as np

    peak = float(np.max(np.abs(wav))) if wav.size else 0.0
    if peak == 0.0:
        return wav
    loud = np.flatnonzero(np.abs(wav) > peak * thresh_ratio)
    if loud.size == 0:
        return wav
    pad = int(sr * pad_ms / 1000)
    start = max(0, int(loud[0]) - pad)
    end = min(wav.size, int(loud[-1]) + pad)
    return wav[start:end]


def _quiet_runs(wav, sr=24000, thresh_ratio=0.02, win_ms=20):
    """Intervalli (inizio, fine) in cui l'inviluppo del segnale sta sotto soglia."""
    import numpy as np

    win = max(1, int(sr * win_ms / 1000))
    env = np.convolve(np.abs(wav), np.ones(win) / win, mode="same")
    peak = float(env.max()) if env.size else 0.0
    if peak == 0.0:
        return []
    quiet = env < peak * thresh_ratio

    edges = np.diff(quiet.astype(np.int8))
    starts = list(np.flatnonzero(edges == 1) + 1)
    ends = list(np.flatnonzero(edges == -1) + 1)
    if quiet.size and quiet[0]:
        starts.insert(0, 0)
    if quiet.size and quiet[-1]:
        ends.append(quiet.size)
    return list(zip(starts, ends))


def collapse_gaps(wav, sr=24000, min_gap_ms=350, max_gap_ms=260):
    """Accorcia i silenzi interni troppo lunghi lasciandone uno naturale.

    XTTS, sui testi con puntini di sospensione e con riferimenti che contengono pause,
    a volte inserisce vuoti di diversi secondi in mezzo a una frase. Le pause del
    racconto le decide assemble.py: qui servono solo i respiri interni alla battuta.
    """
    import numpy as np

    min_gap = int(sr * min_gap_ms / 1000)
    keep = int(sr * max_gap_ms / 1000)
    runs = [(s, e) for s, e in _quiet_runs(wav, sr) if e - s > min_gap]
    if not runs:
        return wav

    pieces, cursor = [], 0
    for s, e in runs:
        pieces.append(wav[cursor:s])
        pieces.append(wav[s:s + keep])  # un pezzo del silenzio originale, non digitale
        cursor = e
    pieces.append(wav[cursor:])
    return np.concatenate(pieces)


def speech_duration(wav, sr=24000):
    """Durata del solo parlato, al netto dei silenzi: e' questa che va confrontata
    con la lunghezza del testo per accorgersi che il modello e' andato in loop."""
    quiet = sum(e - s for s, e in _quiet_runs(wav, sr))
    return max(0.0, (len(wav) - quiet) / sr)


def clip_snr(wav, sr=24000):
    """Rapporto tra parlato e fondo della clip generata.

    XTTS ogni tanto produce una presa visibilmente piu' rumorosa delle altre, con lo
    stesso riferimento e lo stesso testo: conviene accorgersene e riprovare.
    Restituisce None sulle clip troppo corte, dove la misura non sarebbe affidabile
    (la finestra piu' silenziosa sarebbe ancora parlato).
    """
    import numpy as np

    w = int(sr * 0.15)
    n = len(wav) // w
    if n < 6:
        return None
    r = np.array([np.sqrt(np.mean(wav[i*w:(i+1)*w] ** 2)) + 1e-12 for i in range(n)])
    db = 20 * np.log10(r)
    return float(np.percentile(db, 90) - db.min())


def expected_duration(text):
    """Durata plausibile del parlato, usata per accorgersi che XTTS e' andato in loop.

    Su testi brevi e non lessicali ("Hmmpf!") il modello tende a ripetere l'espressione
    piu' volte: il segnale e' una durata molto piu' lunga di quella giustificata dal testo.
    """
    return max(0.9, len(text) / 13.0 + 0.7)


def reference_wavs():
    """Le finestre di riferimento prodotte da prepare_voice.sh."""
    ref_dir = POC / "voice_ref"
    refs = sorted(ref_dir.glob("ref_[0-9].wav"))
    if not refs:
        sys.exit(f"Nessun riferimento in {ref_dir}: esegui prima poc/prepare_voice.sh")
    return [str(p) for p in refs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="+", type=int, metavar="SEQ",
                    help="rigenera solo questi balloon (numero 'seq' di script.json)")
    ap.add_argument("--cpu", action="store_true", help="forza la CPU invece della GPU")
    args = ap.parse_args()

    import torch
    import torchaudio

    device = "cpu" if args.cpu else ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[0/4] device: {device}", flush=True)

    script = json.loads((POC / "script.json").read_text(encoding="utf-8"))
    voices = json.loads((POC / "voices.json").read_text(encoding="utf-8"))
    defaults = voices["defaults"]
    speakers = voices["speakers"]
    type_overrides = voices.get("type_overrides", {})

    model = load_model(device)

    refs = reference_wavs()
    print(f"[2/4] latenti del parlante da {len(refs)} riferimenti...", flush=True)
    gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(audio_path=refs)

    out_dir = POC / "clips"
    out_dir.mkdir(exist_ok=True)

    entries = script["entries"]
    if args.only:
        entries = [e for e in entries if e["seq"] in set(args.only)]

    print(f"[3/4] sintesi di {len(entries)} clip...", flush=True)
    for entry in entries:
        speaker = entry["speaker"]
        preset = {**defaults, **speakers.get(speaker, {})}
        preset.update({k: v for k, v in type_overrides.get(entry["type"], {}).items()
                       if k in ("speed",)})

        text = entry.get("text_tts") or entry["text"]
        out_path = out_dir / f"{entry['seq']:02d}_{speaker}.wav"

        limit = expected_duration(text) * 1.6 + 0.6
        takes, attempts = [], 0
        for attempt in range(MAX_ATTEMPTS):
            attempts = attempt + 1
            torch.manual_seed(SEED + attempt * 977)
            result = model.inference(
                text=text,
                language=LANGUAGE,
                gpt_cond_latent=gpt_cond_latent,
                speaker_embedding=speaker_embedding,
                speed=float(preset["speed"]),
                temperature=0.7,
                repetition_penalty=5.0,
            )
            raw = result["wav"]
            raw = raw.astype("float32") if hasattr(raw, "astype") else torch.tensor(raw).numpy()
            wav = collapse_gaps(trim_silence(raw))
            spoken, snr = speech_duration(wav), clip_snr(wav)
            takes.append((wav, spoken, snr))
            if spoken <= limit and (snr is None or snr >= MIN_SNR_DB):
                break  # parlato coerente col testo e fondo pulito

        # tra le prese senza loop si sceglie la meno rumorosa; se sono tutte in loop,
        # si ripiega sulla piu' breve
        clean = [t for t in takes if t[1] <= limit]
        if clean:
            best, best_speech, best_snr = max(clean, key=lambda t: (t[2] if t[2] is not None else 99))
        else:
            best, best_speech, best_snr = min(takes, key=lambda t: t[1])

        flag = ""
        if best_speech > limit:
            flag = f"  [!] {attempts} prese, parlato sempre oltre il limite di {limit:.1f}s"
        elif best_snr is not None and best_snr < MIN_SNR_DB:
            flag = f"  [!] {attempts} prese, fondo sempre rumoroso"
        elif attempts > 1:
            flag = f"  ({attempts} prese)"

        torchaudio.save(str(out_path), torch.tensor(best).unsqueeze(0), 24000)
        total = len(best) / 24000
        snr_txt = f"{best_snr:4.0f}dB" if best_snr is not None else "  n/d"
        print(f"  seq {entry['seq']:2d}  {speaker:<12} {total:5.2f}s "
              f"(parlato {best_speech:5.2f}s, SNR {snr_txt})  {text[:40]}{flag}", flush=True)

    print(f"[4/4] fatto: clip in {out_dir}", flush=True)


if __name__ == "__main__":
    main()
