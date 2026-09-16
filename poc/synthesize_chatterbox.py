#!/usr/bin/env python3
"""Fase 4 — sintesi con Chatterbox Multilingual.

Legge poc/script/pNN.json e poc/voices.json e scrive una clip WAV per balloon in
poc/clips/pNN/, che assemble.py poi monta.

Perche' Chatterbox e non XTTS-v2 (poc/synthesize.py, ormai superato): XTTS produce un
timbro che all'ascolto risulta metallico anche senza alcun post-processing, e nessuna
taratura della catena lo toglie (giri 8-10 del piano).

Gira nel suo venv separato, perche' pretende torch 2.6 e transformers 5.x, incompatibili
con quelli di coqui-tts:

    poc/.venv-chatterbox/bin/python poc/synthesize_chatterbox.py --page 42
    poc/.venv-chatterbox/bin/python poc/synthesize_chatterbox.py --all
    poc/.venv-chatterbox/bin/python poc/synthesize_chatterbox.py --page 42 --only 7 8

Ogni battuta viene controllata appena generata (gli stessi controlli di check_clips.py) e
rifatta con un altro seed se esce difettosa: il modello ogni tanto tronca una parola, va in
clipping o produce una clip muta, e sono difetti che la post-produzione non puo' togliere.
Non si ritenta invece sui vuoti interni e sulle code, che assemble.py sistema da solo.

Di default NON risintetizza una clip gia' fatta il cui testo e i cui parametri non sono
cambiati: con 300 balloon una rigenerazione completa costa troppo per ritoccare una
battuta sola. Con --force si rifa' tutto.

Nota sui riferimenti: usa poc/voice_ref_plain/, cioe' le finestre SENZA la
pre-compensazione dell'intonazione, che era tarata sulla deriva specifica di XTTS.
"""

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_clips import difetti, difetti_grezza, da_rigenerare, gravita   # noqa: E402
from intonation import f0_track                          # noqa: E402

POC = Path(__file__).resolve().parent
LANGUAGE = "it"
SEED = 1234
TENTATIVI = 5   # prese al massimo per battuta, con seed diversi. Cinque e non tre perche' le
                # battute cortissime ("Fine.", "Siamo...", "Beeeeeh!") sbagliano spesso: il
                # modello dice la parola e poi divaga, e in tre tentativi capita di non
                # trovarne una pulita. Sulle battute normali il ciclo si ferma alla prima.
VICINO_ST = 1.0  # con --scegli-altezza, una presa entro un semitono dal bersaglio va bene cosi'


def altezza(x, sr):
    """F0 mediana della presa, o None se e' troppo corta per misurarla."""
    import numpy as np
    f0 = f0_track(np.asarray(x, dtype=np.float64), sr)
    if f0.size < 20:
        return None
    return float(np.median(f0))
REF_DIR = POC / "voice_ref_plain"
MODEL_DIR = POC / "models" / "chatterbox"

# Pre-compensazione dell'intonazione del riferimento, misurata su tre frasi:
#   riferimento x1.00 -> uscita 140 Hz | x0.92 -> 126 Hz | x0.86 -> 118 Hz
# La voce di Mauro sta a 122 Hz, quindi x0.89. La risposta e' quasi lineare, al
# contrario di XTTS che aveva salti bruschi. Intonare il riferimento invece
# dell'uscita evita il phase vocoder a valle, che suona metallico.
REF_PITCH = 0.89


def reference_wav():
    """Chatterbox prende un solo file di riferimento: si usa il piu' pulito.

    A differenza di XTTS, che media il condizionamento su piu' campioni, qui conta la
    qualita' del singolo spezzone.
    """
    refs = sorted(REF_DIR.glob("ref_[0-9].wav"))
    if not refs:
        sys.exit(f"Nessun riferimento in {REF_DIR}:\n"
                 f"  REF_PITCH=1.0 REF_DIR=poc/voice_ref_plain ./poc/prepare_voice.sh")
    return refs[0]   # prepare_voice.sh ordina ref_1..N dal piu' pulito al meno pulito


def speaker_reference(base, speaker, pitch, cache_dir):
    """Riferimento intonato all'altezza del personaggio.

    Il 'pitch' di voices.json e' lo scostamento dalla voce reale di Mauro: qui diventa
    l'altezza del riferimento dato al modello, cosi' Chatterbox genera gia' alla nota
    giusta e l'uscita non va piu' trasposta.

    Il rapporto finisce nel nome del file: altrimenti, cambiando il 'pitch' di un
    personaggio in voices.json, si riuserebbe il riferimento vecchio senza accorgersene.
    """
    ratio = REF_PITCH * float(pitch)
    dst = cache_dir / f"ref_{speaker}_{ratio:.4f}.wav"
    if not dst.exists():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(base), "-af",
                        f"rubberband=pitch={ratio:.4f}:formant=preserved:pitchq=quality",
                        str(dst)], check=True)
    return dst, ratio


def canale_di(entry, channels):
    """Il canale della battuta: 'radio', 'sussurro', o niente.

    E' una proprieta' della battuta e non del personaggio, perche' la stessa voce puo'
    arrivare in diretta, dalla ricetrasmittente o a mezza voce (vedi la pagina 42, dove a
    meta' pagina la scena cambia stazione).
    """
    nome = entry.get("channel") or ("radio" if entry.get("radio") else "")
    return nome, channels.get(nome, {})


def impronta(entry, preset, ex, cfg, scelta_altezza=False):
    """Impronta di cio' che determina la clip: se non cambia, la clip non va rifatta."""
    dati = {
        "text": entry.get("text_tts") or entry["text"],
        "speaker": entry["speaker"],
        "exaggeration": ex,
        "cfg_weight": cfg,
        "pitch": preset.get("pitch", 1.0),
        "ref_pitch": REF_PITCH,
        "seed": SEED,
        "language": LANGUAGE,
    }
    if entry.get("channel") or entry.get("radio"):
        # il canale entra nell'impronta solo quando c'e': cosi' le clip senza canale
        # conservano la firma che avevano prima che i canali esistessero
        dati["canale"] = entry.get("channel") or "radio"
    if scelta_altezza:
        # la chiave compare solo quando la selezione e' attiva: cosi' le cache gia' fatte
        # senza di essa restano valide e non si risintetizza mezzo fumetto per una prova
        dati["scelta_altezza"] = True
    return hashlib.sha256(json.dumps(dati, sort_keys=True).encode()).hexdigest()[:16]


def pagine_disponibili():
    return sorted(int(p.stem[1:]) for p in (POC / "script").glob("p*.json") if p.stem[1:].isdigit())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", type=int, help="sintetizza una pagina")
    ap.add_argument("--all", action="store_true", help="sintetizza tutte le pagine trascritte")
    ap.add_argument("--only", nargs="+", type=int, metavar="SEQ",
                    help="solo questi balloon (richiede --page)")
    ap.add_argument("--force", action="store_true",
                    help="risintetizza anche le clip gia' fatte e non cambiate")
    ap.add_argument("--exaggeration", type=float, default=None,
                    help="forza l'intensita' espressiva per tutti (default: da voices.json)")
    ap.add_argument("--cfg", type=float, default=None,
                    help="forza l'aderenza al riferimento per tutti (default: da voices.json)")
    ap.add_argument("--scegli-altezza", action="store_true",
                    help="fra le prese pulite tiene quella con l'altezza piu' vicina al bersaglio "
                         "del personaggio, invece della prima (genera sempre piu' prese: piu' lento)")
    ap.add_argument("--dry-run", action="store_true",
                    help="dice solo cosa rifarebbe, senza caricare il modello")
    ap.add_argument("--cpu", action="store_true")
    args = ap.parse_args()

    if args.only and not args.page:
        ap.error("--only vale su una pagina sola: aggiungi --page N")
    pagine = [args.page] if args.page else (pagine_disponibili() if args.all else [])
    if not pagine:
        ap.error("scegli --page N o --all")

    voices = json.loads((POC / "voices.json").read_text(encoding="utf-8"))
    speakers = voices["speakers"]
    channels = voices.get("channels", {})
    # il 'pitch' del personaggio e' lo scostamento dalla voce reale di Mauro: il bersaglio
    # in Hz e' quindi la sua altezza moltiplicata per quello scostamento
    base_hz = float(voices.get("pitch_target_hz", 0) or 0)
    ref = reference_wav()
    cache_dir = POC / "voice_ref_cb"
    cache_dir.mkdir(exist_ok=True)

    # Prima si guarda cosa c'e' da fare: se la cache copre tutto, il modello non si carica
    # nemmeno (sono ~30 s di caricamento e 2,5 GB di VRAM per non generare niente).
    lavoro = []
    for page in pagine:
        path = POC / "script" / f"p{page}.json"
        if not path.exists():
            sys.exit(f"Manca {path}: la pagina {page} non e' ancora trascritta.")
        script = json.loads(path.read_text(encoding="utf-8"))
        out_dir = POC / "clips" / f"p{page}"
        out_dir.mkdir(parents=True, exist_ok=True)
        cache_file = out_dir / ".cache.json"
        cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}

        entries = script["entries"]
        if args.only:
            entries = [e for e in entries if e["seq"] in set(args.only)]

        da_fare = []
        for entry in entries:
            preset = speakers.get(entry["speaker"], {})
            _, canale = canale_di(entry, channels)
            ex_base = canale.get("exaggeration", preset.get("exaggeration", 0.7))
            cfg_base = canale.get("cfg_weight", preset.get("cfg_weight", 0.4))
            ex = args.exaggeration if args.exaggeration is not None else ex_base
            cfg = args.cfg if args.cfg is not None else cfg_base
            nome = f"{entry['seq']:02d}_{entry['speaker']}"
            firma = impronta(entry, preset, ex, cfg, args.scegli_altezza)
            in_cache = cache.get(nome)
            if isinstance(in_cache, dict):      # formato nuovo: firma + seed + difetti
                in_cache = in_cache.get("firma")
            gia_fatta = (out_dir / f"{nome}.wav").exists() and in_cache == firma
            if args.force or not gia_fatta:
                da_fare.append((entry, preset, ex, cfg, nome, firma))
        saltate = len(entries) - len(da_fare)
        print(f"pagina {page}: {len(da_fare)} da sintetizzare, {saltate} gia' a posto", flush=True)
        if da_fare:
            lavoro.append((page, out_dir, cache_file, cache, da_fare))

    if not lavoro:
        print("Niente da fare: tutte le clip sono aggiornate.")
        return

    if args.dry_run:
        for page, _out_dir, _cf, _cache, da_fare in lavoro:
            for entry, _preset, ex, cfg, nome, _firma in da_fare:
                print(f"  p{page} {nome:<16} ex{ex} cfg{cfg}  "
                      f"{(entry.get('text_tts') or entry['text'])[:44]}")
        print(f"(dry run: {sum(len(l[4]) for l in lavoro)} clip da sintetizzare)")
        return

    import torch
    import torchaudio
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    device = "cpu" if args.cpu else ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[1/2] modello Chatterbox Multilingual su {device}, riferimento {ref.name}...", flush=True)
    # from_local invece di from_pretrained: i pesi vengono scaricati a parte con curl,
    # perche' huggingface_hub su questa rete resta appeso a meta' file senza sollevare
    # eccezioni, quindi nessun meccanismo di ritentativo puo' intervenire.
    if not MODEL_DIR.exists():
        sys.exit(f"Pesi mancanti in {MODEL_DIR}: esegui prima lo script di download.")
    model = ChatterboxMultilingualTTS.from_local(str(MODEL_DIR), device=device)

    for page, out_dir, cache_file, cache, da_fare in lavoro:
        print(f"[2/2] pagina {page}: {len(da_fare)} clip", flush=True)
        for entry, preset, ex, cfg, nome, firma in da_fare:
            text = entry.get("text_tts") or entry["text"]
            sref, ratio = speaker_reference(ref, entry["speaker"], preset.get("pitch", 1.0), cache_dir)

            bersaglio = base_hz * float(preset.get("pitch", 1.0)) if (args.scegli_altezza and base_hz) else 0.0

            prese = []
            for tentativo in range(TENTATIVI):
                seed = SEED + tentativo
                torch.manual_seed(seed)
                wav = model.generate(text, language_id=LANGUAGE, audio_prompt_path=str(sref),
                                     exaggeration=ex, cfg_weight=cfg)
                if not torch.is_tensor(wav):
                    wav = torch.tensor(wav)
                if wav.dim() == 1:
                    wav = wav.unsqueeze(0)

                campioni = wav.cpu().numpy()[0]
                guasti = (difetti(campioni, model.sr, text, entry["type"] == "sfx")
                          + difetti_grezza(campioni, model.sr, text))
                gravi = da_rigenerare(guasti)
                hz = altezza(campioni, model.sr) if bersaglio else None
                scarto = abs(12 * math.log2(hz / bersaglio)) if (hz and bersaglio) else None
                prese.append((gravita(guasti), scarto, seed, wav, guasti, hz))

                if gravi:
                    print(f"      presa {tentativo+1}: {', '.join(gravi)} -> rifaccio", flush=True)
                    continue
                if not bersaglio:
                    break
                if scarto is None or scarto <= VICINO_ST:
                    break   # pulita e gia' in tono: inutile spendere altre prese
                print(f"      presa {tentativo+1}: pulita ma {hz:.0f} Hz contro {bersaglio:.0f} "
                      f"({scarto:.1f} semitoni) -> provo ancora", flush=True)

            # prima le prese sane, poi, se si sceglie l'altezza, la piu' in tono
            _, _, seed, wav, guasti, hz = min(
                prese, key=lambda p: (p[0], p[1] if p[1] is not None else 99))
            torchaudio.save(str(out_dir / f"{nome}.wav"), wav.cpu(), model.sr)

            # la cache si scrive dopo ogni clip: un'interruzione a meta' pagina non
            # costringe a rifare quelle gia' buone
            cache[nome] = {"firma": firma, "seed": seed, "difetti": guasti}
            cache_file.write_text(json.dumps(cache, indent=2, sort_keys=True))
            residui = da_rigenerare(guasti)
            nota = f"  [{', '.join(residui)}]" if residui else ""
            tono = f" {hz:.0f}Hz" if hz else ""
            print(f"  seq {entry['seq']:2d}  {entry['speaker']:<12} {wav.shape[-1]/model.sr:5.2f}s  "
                  f"rif x{ratio:.3f} ex{ex} cfg{cfg} seed{seed}{tono}  {text[:28]}{nota}", flush=True)

    print("fatto.", flush=True)


if __name__ == "__main__":
    main()
