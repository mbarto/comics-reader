#!/usr/bin/env bash
# Fase 1 — prepara le finestre di riferimento per il cloning XTTS-v2.
#
# Produce in poc/voice_ref/:
#   ref_full.wav   tutta la registrazione ripulita (mono 22.05 kHz, -20 LUFS)
#   ref_1..N.wav   le N finestre piu' pulite, tagliate sulle pause naturali
#   _dereverb.wav  solo con DEREVERB=1: la sorgente dereverberata (cache, ~2 min)
#
# XTTS-v2 accetta piu' file di riferimento e ne media il condizionamento: le finestre
# separate danno un clone piu' stabile del singolo spezzone lungo. Siccome e' una media,
# una finestra rumorosa peggiora anche le altre: se ne tagliano piu' del necessario e si
# tengono solo le migliori.
#
# Uso:
#   ./poc/prepare_voice.sh                               # registrazione predefinita
#   VOICE=voice/voce_mauro2.flac ./poc/prepare_voice.sh  # un'altra registrazione
#   REF_PITCH=1.0 REF_DIR=poc/voice_ref_plain ./poc/prepare_voice.sh   # senza pre-compensazione
#   DEREVERB=1 ./poc/prepare_voice.sh                    # con dereverberazione WPE

set -euo pipefail
export LC_ALL=C   # ffprobe stampa i decimali col punto: evita che printf inciampi sul locale it_IT

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${VOICE:-$ROOT/voice/voce_mauro4.flac}"
[[ "$SRC" = /* ]] || SRC="$ROOT/$SRC"
DST="${REF_DIR:-$ROOT/poc/voice_ref}"
[[ "$DST" = /* ]] || DST="$ROOT/$DST"
PY="$ROOT/poc/.venv/bin/python"
DRY="$DST/_dereverb.wav"

KEEP=3          # finestre tenute (3 x ~10 s = i 30 s che XTTS usa al massimo)

# Pre-compensazione dell'intonazione del riferimento.
#
# XTTS genera sistematicamente piu' acuto del riferimento: con le finestre non trasposte
# (117-146 Hz) esce a 145-176 Hz, contro i 122 Hz della voce di Mauro. Correggere l'uscita
# con rubberband funziona sull'altezza ma la rende metallica, perche' un phase vocoder che
# trasporta di -6 semitoni lascia artefatti che l'orecchio sente subito.
#
# Trasponendo invece il RIFERIMENTO, l'uscita la sintetizza comunque il vocoder da zero e
# resta pulita. Misurato: riferimento x0.79 -> uscite 113/132/141/115 Hz su quattro frasi,
# mediana 123 Hz. La risposta non e' lineare (x0.80 da' gia' mediana 137), quindi questo
# valore va ritarato con poc/intonation.py se si cambia registrazione, ed e' specifico di
# XTTS: un altro modello ha un'altra deriva, quindi va rimisurata (REF_PITCH=1.0 la disattiva).
REF_PITCH="${REF_PITCH:-0.79}"
WIN_MIN=7.0     # durata minima accettabile di una finestra
WIN_MAX=12.0    # oltre questa lunghezza la finestra viene chiusa

[[ -f "$SRC" ]] || { echo "Sorgente non trovata: $SRC" >&2; exit 1; }
echo "== sorgente: $(basename "$SRC") =="

# Catena comune: taglio del rumble, denoise, normalizzazione EBU R128, 22.05 kHz.
# Il denoise va PRIMA della normalizzazione, altrimenti lavora su un segnale gia' amplificato.
CLEAN="highpass=f=70,afftdn=nr=20:nf=-56,loudnorm=I=-20:TP=-2:LRA=11,aresample=22050"

mkdir -p "$DST"

# --- dereverberazione (opzionale, spenta di default) --------------------------
# WPE toglie il riverbero della stanza, che XTTS altrimenti clona insieme al timbro.
# Sulle misure fa molto bene, MA a 20 tap la voce perde corpo e suona piu' artificiale:
# all'ascolto Mauro ha preferito la versione senza. Con una registrazione gia' asciutta
# non serve. Resta disponibile per sorgenti molto riverberanti.
if [[ "${DEREVERB:-0}" == "1" ]]; then
  if [[ ! -f "$DRY" || "$SRC" -nt "$DRY" ]]; then
    echo "== dereverberazione WPE (un paio di minuti, poi resta in cache) =="
    ffmpeg -y -loglevel error -i "$SRC" -ac 1 -ar 22050 "$DST/_mono.wav"
    "$PY" "$ROOT/poc/dereverb.py" "$DST/_mono.wav" "$DRY" --taps 20
    rm -f "$DST/_mono.wav"
  else
    echo "== dereverberazione: uso la cache $(basename "$DRY") =="
  fi
  SOURCE="$DRY"
  FILTERS="$CLEAN"                                   # gia' mono dopo il dereverb
else
  SOURCE="$SRC"
  FILTERS="pan=mono|c0=0.5*c0+0.5*c1,$CLEAN"         # downmix (innocuo se gia' mono)
fi

# --- finestre candidate -------------------------------------------------------
# Ricavate dalle pause vere della registrazione invece che scritte a mano: ogni finestra
# comincia dove finisce un silenzio e finisce dove ne comincia un altro, cosi' nessuna
# parola viene troncata a meta'. Serve per cambiare registrazione senza ritarare nulla.
echo "== individuazione delle pause =="
SILENCES="$DST/_silences.txt"
ffmpeg -hide_banner -i "$SOURCE" -af "silencedetect=n=-35dB:d=0.30" -f null - 2>&1 \
  | grep -oE 'silence_(start|end): [0-9.]+' > "$SILENCES"

# NB: il programma python arriva dall'heredoc, quindi occupa gia' stdin: i dati vanno
# passati per forza come file, non in pipe.
mapfile -t WINDOWS < <(
  "$PY" - "$WIN_MIN" "$WIN_MAX" "$KEEP" "$SILENCES" <<'PY'
import sys

win_min, win_max, keep = float(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3])

starts, ends = [], []
for line in open(sys.argv[4], encoding="utf-8"):
    kind, value = line.strip().split(": ")
    (starts if kind == "silence_start" else ends).append(float(value))

# La registrazione puo' cominciare gia' in mezzo al parlato: in quel caso il primo
# confine utile e' l'istante zero.
if not ends or (starts and starts[0] < ends[0]):
    ends.insert(0, 0.0)

ends_set, starts_set = set(ends), set(starts)
boundaries = sorted(ends_set | starts_set)


def cut(minimum):
    """Apre una finestra alla fine di una pausa e la chiude alla prima pausa successiva
    che la renda abbastanza lunga. Le finestre non si sovrappongono."""
    out, begin = [], None
    for b in boundaries:
        if begin is None:
            if b in ends_set:
                begin = b
            continue
        if b in starts_set and b - begin >= minimum:
            out.append((begin, min(b - begin, win_max)))
            begin = None
    return out


# Soglia adattiva: su una registrazione corta, o con pause distribuite male, pretendere
# finestre lunghe ne lascia troppo poche. Si scende finche' non ce ne sono abbastanza.
minimum = win_min
while minimum >= 4.0:
    windows = cut(minimum)
    if len(windows) >= keep:
        break
    minimum -= 0.5
else:
    windows = cut(4.0)

print(f"# soglia {minimum:.1f}s", file=sys.stderr)
for start, dur in windows:
    print(f"{start:.2f} {dur:.2f}")
PY
)

if (( ${#WINDOWS[@]} < KEEP )); then
  echo "Solo ${#WINDOWS[@]} finestre utilizzabili: ne servono almeno $KEEP." >&2
  echo "Serve piu' materiale, oppure abbassa WIN_MIN (ora $WIN_MIN s)." >&2
  exit 1
fi
echo "   ${#WINDOWS[@]} finestre candidate"
rm -f "$SILENCES"

if [[ "$REF_PITCH" != "1.0" ]]; then
  FILTERS="$FILTERS,rubberband=pitch=$REF_PITCH:formant=preserved:pitchq=quality"
  echo "== pre-compensazione intonazione del riferimento: x$REF_PITCH =="
fi

echo "== ref_full.wav (registrazione completa ripulita) =="
ffmpeg -y -loglevel error -i "$SOURCE" \
  -af "$FILTERS" -ac 1 -c:a pcm_s16le "$DST/ref_full.wav"

rm -f "$DST"/ref_[0-9].wav "$DST"/cand_*.wav

i=1
for w in "${WINDOWS[@]}"; do
  read -r START DUR <<< "$w"
  echo "== candidata $i (da ${START}s, durata ${DUR}s) =="
  ffmpeg -y -loglevel error -ss "$START" -t "$DUR" -i "$SOURCE" \
    -af "$FILTERS" -ac 1 -c:a pcm_s16le "$DST/cand_$i.wav"
  i=$((i+1))
done

echo
echo "== selezione delle $KEEP finestre piu' pulite =="
"$PY" - "$DST" "$KEEP" <<'PY'
import glob, os, re, sys
import numpy as np, soundfile as sf

dst, keep = sys.argv[1], int(sys.argv[2])

def snr(path):
    """Rapporto tra il parlato (90mo percentile) e la finestra piu' silenziosa."""
    x, sr = sf.read(path)
    x = x if x.ndim == 1 else x.mean(1)
    w = int(sr * 0.2)
    n = len(x) // w
    r = np.array([np.sqrt(np.mean(x[i*w:(i+1)*w] ** 2)) + 1e-12 for i in range(n)])
    db = 20 * np.log10(r)
    return float(np.percentile(db, 90) - db.min())

cands = sorted(glob.glob(os.path.join(dst, "cand_*.wav")),
               key=lambda p: int(re.search(r"(\d+)", os.path.basename(p)).group(1)))
ranked = sorted(((snr(c), c) for c in cands), reverse=True)
for rank, (s, c) in enumerate(ranked, 1):
    print(f"  {'tenuta ' if rank <= keep else 'scartata'} {os.path.basename(c):<12} SNR {s:5.1f} dB")
for i, (s, c) in enumerate(ranked[:keep], 1):
    os.replace(c, os.path.join(dst, f"ref_{i}.wav"))
for _, c in ranked[keep:]:
    os.remove(c)
PY

echo
echo "== verifica =="
for f in "$DST"/ref_*.wav; do
  dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")
  lvl=$(ffmpeg -hide_banner -i "$f" -af volumedetect -f null - 2>&1 \
        | grep -E "mean_volume|max_volume" | tr '\n' ' ' | sed 's/\[[^]]*\] //g')
  printf "%-14s %6.2fs  %s\n" "$(basename "$f")" "$dur" "$lvl"
done
