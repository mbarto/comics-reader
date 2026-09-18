#!/usr/bin/env bash
# Ricostruisce da zero l'ambiente del progetto: i tre virtualenv e i pesi del modello.
#
#   ./poc/setup.sh              tutto
#   ./poc/setup.sh --venv       solo gli ambienti Python
#   ./poc/setup.sh --pesi       solo i pesi del modello (3,0 GB)
#
# Serve perche' il resto del progetto non e' ricostruibile senza: 11,5 GB di virtualenv e
# 3,0 GB di pesi che, se si perdono, costano il giro piu' doloroso di tutto il lavoro.
#
# PERCHE' TRE AMBIENTI: i due modelli TTS provati hanno dipendenze incompatibili fra loro.
# Chatterbox pretende torch 2.6 e transformers 5.x, coqui-tts torch 2.5 e transformers 4.x.
# Il venv di coqui resta perche' ci girano le misure e il montaggio (numpy, soundfile, ffmpeg).
# Il terzo, .venv-estrazione, sta a parte per il motivo opposto: estrarre il copione dalle pagine
# non ha niente a che fare con la sintesi, e non deve trascinarsi dietro 11 GB di torch per due
# librerie da 48 MB.
#
# TRAPPOLE, tutte incontrate sul campo e tutte gia' applicate qui sotto:
#  - UV_HTTP_TIMEOUT / UV_CONCURRENT_DOWNLOADS: con i valori di default uv multiplexa decine di
#    download su un'unica connessione HTTP/2 verso il CDN di PyPI, e quella connessione si pianta
#    senza errore restando appesa fino al timeout;
#  - transformers<5 per coqui-tts: dichiara >=4.57 senza limite superiore, uv installa la 5.x che
#    ha rimosso isin_mps_friendly, e l'import di TTS esplode;
#  - setuptools<81: serve a resemble-perth (il watermarker) per pkg_resources, rimosso dalla 81;
#  - i pesi si scaricano con curl -C - e non con huggingface_hub, che su una rete instabile resta
#    appeso a meta' file SENZA sollevare eccezioni: nessun ritentativo puo' intervenire.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UV="${UV:-$HOME/.local/bin/uv}"
MODELLI="$ROOT/poc/models/chatterbox"
REPO="https://huggingface.co/ResembleAI/chatterbox/resolve/main"
PESI=(t3_mtl23ls_v2.safetensors s3gen.pt ve.pt conds.pt
      grapheme_mtl_merged_expanded_v1.json Cangjie5_TC.json)

export UV_HTTP_TIMEOUT=90
export UV_CONCURRENT_DOWNLOADS=4

crea_venv() {
  if [[ ! -x "$UV" ]]; then
    echo "Manca uv in $UV. Installalo con:  pip3 install --user uv" >&2
    echo "(serve perche' python3-venv/ensurepip non sono installati sul sistema)" >&2
    exit 1
  fi

  echo "== Ambiente 1/3: montaggio e misure (piu' XTTS-v2, ormai superato)"
  "$UV" venv "$ROOT/poc/.venv" --python 3.10
  VIRTUAL_ENV="$ROOT/poc/.venv" "$UV" pip install \
    torch==2.5.1+cu121 torchaudio==2.5.1+cu121 --index-url https://download.pytorch.org/whl/cu121
  VIRTUAL_ENV="$ROOT/poc/.venv" "$UV" pip install \
    "coqui-tts==0.27.5" "transformers>=4.57,<5" numpy soundfile pillow

  echo
  echo "== Ambiente 2/3: sintesi con Chatterbox"
  "$UV" venv "$ROOT/poc/.venv-chatterbox" --python 3.10
  VIRTUAL_ENV="$ROOT/poc/.venv-chatterbox" "$UV" pip install \
    "chatterbox-tts==0.1.7" "setuptools<81" soundfile

  echo
  echo "== Ambiente 3/3: estrazione del copione dalle pagine (48 MB, niente torch)"
  "$UV" venv "$ROOT/poc/.venv-estrazione" --python 3.10
  VIRTUAL_ENV="$ROOT/poc/.venv-estrazione" "$UV" pip install anthropic pillow
}

scarica_pesi() {
  mkdir -p "$MODELLI"
  echo "== Pesi del modello in $MODELLI (3,0 GB in totale)"
  for f in "${PESI[@]}"; do
    echo "-- $f"
    # -C -            riprende dal byte esatto se il trasferimento si interrompe
    # --speed-limit   abbandona la connessione se scende sotto 10 kB/s per 30 s: su questa rete
    #                 i trasferimenti non muoiono, si impiantano, e senza questo restano appesi
    # --ipv4 --http1.1  con HTTP/2 arrivavano "Connection reset by peer" a meta' file
    until curl -L --ipv4 --http1.1 -C - \
               --speed-limit 10000 --speed-time 30 \
               --retry 100 --retry-delay 5 --retry-all-errors \
               -o "$MODELLI/$f" "$REPO/$f"; do
      echo "   interrotto, riprendo dal punto in cui era arrivato..."
      sleep 5
    done
  done
}

case "${1:-tutto}" in
  --venv) crea_venv ;;
  --pesi) scarica_pesi ;;
  tutto)  crea_venv; echo; scarica_pesi ;;
  *) sed -n '2,8p' "$0" >&2; exit 1 ;;
esac

echo
echo "== Verifica"
"$ROOT/poc/.venv/bin/python" -c "import numpy, soundfile; print('  ambiente montaggio: ok')"
"$ROOT/poc/.venv-chatterbox/bin/python" -c "
import torch
print(f'  ambiente sintesi: torch {torch.__version__}, cuda {torch.cuda.is_available()}')"
"$ROOT/poc/.venv-estrazione/bin/python" -c "
import anthropic, PIL; print(f'  ambiente estrazione: anthropic {anthropic.__version__}')"
for f in "${PESI[@]}"; do
  [[ -s "$MODELLI/$f" ]] || { echo "  MANCA $f" >&2; exit 1; }
done
echo "  pesi: $(du -sh "$MODELLI" | cut -f1)"
echo
echo "Manca ancora la voce di riferimento: vedi voice/README.md"
