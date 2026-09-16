#!/usr/bin/env bash
# Pipeline della storia: riferimento vocale -> sintesi -> regia e montaggio.
#
#   ./poc/run_poc.sh --page 42     sintesi + montaggio di una pagina
#   ./poc/run_poc.sh --all         tutte le pagine trascritte, un file per pagina
#   ./poc/run_poc.sh --story       tutte le pagine in un unico file
#   ./poc/run_poc.sh --assemble --page 42    solo regia e montaggio (niente GPU)
#   ./poc/run_poc.sh --voice       rigenera le finestre di riferimento
#
# La sintesi salta le clip gia' fatte e non cambiate, quindi --all e --story dopo una
# modifica a una battuta sola costano quanto quella battuta. Per vedere prima cosa
# verrebbe rifatto:
#   poc/.venv-chatterbox/bin/python poc/synthesize_chatterbox.py --all --dry-run

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/poc/.venv/bin/python"                  # montaggio: ffmpeg + numpy
PY_CB="$ROOT/poc/.venv-chatterbox/bin/python"    # sintesi: torch 2.6 + transformers 5.x

for p in "$PY" "$PY_CB"; do
  if [[ ! -x "$p" ]]; then
    echo "Ambiente mancante: $p" >&2
    exit 1
  fi
done

case "${1:-}" in
  --voice)
    exec "$ROOT/poc/prepare_voice.sh"
    ;;
  --assemble)
    shift
    exec "$PY" "$ROOT/poc/assemble.py" "$@"
    ;;
  --page)
    pagina="${2:?serve il numero di pagina}"
    echo "== Sintesi pagina $pagina =="
    "$PY_CB" "$ROOT/poc/synthesize_chatterbox.py" --page "$pagina"
    echo
    echo "== Regia e montaggio =="
    exec "$PY" "$ROOT/poc/assemble.py" --page "$pagina"
    ;;
  --all|--story)
    modo="$1"
    echo "== Sintesi di tutte le pagine trascritte =="
    "$PY_CB" "$ROOT/poc/synthesize_chatterbox.py" --all
    echo
    echo "== Regia e montaggio =="
    exec "$PY" "$ROOT/poc/assemble.py" "$modo"
    ;;
  *)
    sed -n '2,12p' "$0" >&2
    exit 1
    ;;
esac
