#!/usr/bin/env bash
# Fase 7.1 — dal PDF scansionato alle 12 pagine singole e dritte della storia.
#
#   ./poc/render_pages.sh
#
# Produce pages/render/p41.png ... p52.png a 300 dpi.
#
# Perche' non e' un semplice pdftoppm:
#  - le pagine PDF 2-6 sono DOPPIE e ruotate di 90°: vanno ruotate in senso ORARIO
#    (verificato: cosi' la pagina pari finisce a sinistra e la dispari a destra);
#  - la piega NON sta a meta' del foglio (sta a x~1906-1959 su 3508): tagliare a meta'
#    mangiava l'ultima striscia della pagina di sinistra. La piega si trova cercando la
#    colonna piu' scura vicino al centro, ed e' ricalcolata per ogni foglio;
#  - le pagine PDF 1 e 7 sono dritte ma contengono anche pagine di altri articoli,
#    quindi si ritagliano a coordinate fisse, trovate a occhio e verificate.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PDF="$ROOT/pages/paperino-park-ranger.pdf"
OUT="$ROOT/pages/render"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$OUT"
echo "== Rendering a 300 dpi"
pdftoppm -r 300 -png -f 1 -l 7 "$PDF" "$TMP/pdf"

echo "== Pagine 1 e 7: ritaglio della sola pagina di fumetto"
convert "$TMP/pdf-1.png" -crop 1680x2330+390+20  +repage "$OUT/p41.png"
convert "$TMP/pdf-7.png" -crop 1515x2110+795+30  +repage "$OUT/p52.png"

echo "== Pagine 2-6: rotazione oraria, taglio sulla piega, rifilatura"
OVERLAP=30   # meglio un filo della pagina accanto che un balloon tagliato
for pdfp in 2 3 4 5 6; do
  sinistra=$((38 + pdfp * 2)); destra=$((sinistra + 1))
  convert "$TMP/pdf-$pdfp.png" -rotate 90 "$TMP/rot-$pdfp.png"
  # niente "read W H": identify non stampa il newline finale e read uscirebbe con 1, che con set -e ferma tutto
  W=$(identify -format "%w" "$TMP/rot-$pdfp.png")
  H=$(identify -format "%h" "$TMP/rot-$pdfp.png")

  # colonna piu' scura nella fascia centrale = la piega
  piega=$(convert "$TMP/rot-$pdfp.png" -colorspace gray -resize x1\! txt:- \
          | tail -n +2 | sed 's/[,:()]/ /g' \
          | awk -v lo=$((W*40/100)) -v hi=$((W*60/100)) \
                '$1>lo && $1<hi { if (min=="" || $4<min) { min=$4; x=$1 } } END { print x }')

  convert "$TMP/rot-$pdfp.png" -crop $((piega + OVERLAP))x${H}+0+0 +repage \
          -fuzz 18% -trim +repage "$OUT/p$sinistra.png"
  convert "$TMP/rot-$pdfp.png" -crop $((W - piega + OVERLAP))x${H}+$((piega - OVERLAP))+0 +repage \
          -fuzz 18% -trim +repage "$OUT/p$destra.png"
  echo "   pdf-$pdfp  piega x=$piega  ->  p$sinistra.png + p$destra.png"
done

echo
identify -format "%f  %wx%h\n" "$OUT"/p*.png | sort -V
