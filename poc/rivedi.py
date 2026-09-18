#!/usr/bin/env python3
"""Genera una pagina HTML per rivedere a mano il copione estratto in automatico.

Fase 5 del piano (poc/PIANO-estrazione.md). L'estrazione automatica arriva al 100% sul testo e
sull'ordine ma al 89-91% sull'attribuzione dei personaggi: una dozzina di battute a storia vanno
corrette. Rileggere una proposta e' questione di minuti, trascrivere da zero erano ore - ma solo
se rileggerla e' comodo.

    poc/.venv-estrazione/bin/python poc/rivedi.py poc/estrazione/riquadri
    (apri poc/revisione/index.html, correggi, premi "Scarica il copione")
    poc/.venv-estrazione/bin/python poc/rivedi.py --applica ~/Scaricati/copione-rivisto.json

La pagina e' un file statico: niente server, niente dipendenze oltre a Pillow, funziona da file://.

DUE SCELTE DI FONDO, tutte e due imparate misurando (vedi §5-ter del piano):

1. SI MOSTRANO TUTTE LE ATTRIBUZIONI, sempre. L'idea di segnalare solo le battute "incerte" e'
   stata provata e scartata: su due giri indipendenti dello stesso modello, 10 errori su 15 erano
   sbagliati IDENTICAMENTE in tutti e due i giri. Un punteggio di confidenza avrebbe dato per
   sicure proprio le battute sbagliate. I controlli qui sotto colorano, non filtrano.

2. I CONTROLLI SONO FATTI, NON STIME. Segnalano cose verificabili - una battuta che nomina il
   personaggio a cui e' attribuita, due riquadri sovrapposti, una battuta senza riquadro - non
   "quanto e' sicuro il modello". Il primo di questi ha pescato un errore vero nel PoC
   ("GIA', PUOI DIRLO FORTE, MATT!" attribuita a Matt).

Il riquadro di ogni battuta e' nel sistema di riferimento dell'IMMAGINE RIDOTTA che il modello ha
guardato, non del PNG a 300 dpi: le immagini si riscrivono qui alla stessa dimensione, se no i
riquadri cadrebbero fuori posto.
"""

import argparse
import json
import re
import unicodedata
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Una sola fonte di verita' per il ridimensionamento della pagina, il cast e i tipi: se cambia
# la fascia di risoluzione, i riquadri devono restare nello stesso sistema di riferimento.
# (E' anche l'import che segnala la mancanza di Pillow con un messaggio utile.)
import estrai_copione as E  # noqa: E402

POC = Path(__file__).resolve().parent
ROOT = POC.parent


def breve(percorso):
    """Il percorso accorciato rispetto alla radice del progetto, se ci sta dentro."""
    percorso = Path(percorso).resolve()
    try:
        return str(percorso.relative_to(ROOT))
    except ValueError:
        return str(percorso)


def carica(cartella):
    pagine = {}
    for f in sorted(Path(cartella).glob("p*.json")):
        if not f.stem[1:].isdigit():
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        pagine[d.get("page", int(f.stem[1:]))] = d
    if not pagine:
        sys.exit(f"Nessun pNN.json in {cartella}")
    return pagine


def immagine_pagina(numero, uscita):
    """Riscrive la pagina alla stessa dimensione che il modello ha visto, in JPEG."""
    sorgente = ROOT / "pages" / "render" / f"p{numero}.png"
    if not sorgente.exists():
        return None, (0, 0)
    dati, _, _, vista, _ = E.prepara(sorgente, "alta", "jpeg", 88)
    nome = f"p{numero}.jpg"
    (uscita / nome).write_bytes(dati)
    return nome, vista


# Quando il nome NON e' un vocativo ma una presentazione: "io sono Otis", "chiamatemi Susy",
# "il mio nome e' Bob", "qui parla il ranger Paperino". Senza queste, il controllo sul nome
# sparava quattro falsi allarmi per storia - tre solo nella pagina in cui i turisti si
# presentano uno dopo l'altro - e nessun errore vero: un avviso che grida e non prende niente
# insegna solo a ignorarlo.
PRESENTAZIONI = ("IO SONO", "SONO", "MI CHIAMO", "IL MIO NOME", "IL MIO NOME E",
                 "CHIAMATEMI", "QUI PARLA", "QUI", "PARLA", "IL RANGER", "RANGER")


def normalizza(testo):
    """Maiuscolo, senza accenti, senza punteggiatura, con gli spazi ai bordi.

    Gli accenti si TOLGONO, non si cancellano: una prima versione li buttava via con la
    punteggiatura, e "IL MIO NOME E' BOB" diventava "IL MIO NOME BOB", che non corrispondeva
    a nessuna formula di presentazione.
    """
    d = unicodedata.normalize("NFD", (testo or "").upper())
    d = "".join(c for c in d if not unicodedata.combining(c))
    return " " + re.sub(r"[^A-Z0-9']+", " ", d).strip() + " "


def si_presenta(testo, nome):
    """Vero se il nome viene subito dopo una formula di presentazione."""
    return any(f" {formula} {nome} " in testo for formula in PRESENTAZIONI)


def controlli(entries):
    """I controlli deterministici. Ritorna, per ogni battuta, la lista dei motivi di sospetto."""
    esiti = [[] for _ in entries]
    for i, e in enumerate(entries):
        parlante = (e.get("speaker") or "").lower()
        # 1. la battuta nomina il personaggio a cui e' attribuita.
        #    La punteggiatura si azzera PRIMA di cercare: una prima versione cercava lo stesso
        #    separatore da tutt'e due i lati (" MATT ", ",MATT,") e non scattava mai, perche' il
        #    caso vero e' " MATT!" - spazio prima, punto esclamativo dopo.
        #    Alla radio ci si annuncia col proprio nome ("Ranger Hilde a Picco Fiocco!"): e' un
        #    nominativo, non un vocativo, e senza l'eccezione il controllo grida a ogni chiamata.
        if parlante and parlante != "narratore" and not e.get("radio"):
            testo = normalizza(e.get("text"))
            if f" {parlante.upper()} " in testo and not si_presenta(testo, parlante.upper()):
                esiti[i].append(f"nomina {parlante}: chi viene chiamato per nome "
                                f"di solito non e' chi parla")
        # 2. senza riquadro: non si puo' controllare sulla pagina
        if not e.get("bbox"):
            esiti[i].append("nessun riquadro")
    # 3. riquadri molto sovrapposti fra loro
    for i, a in enumerate(entries):
        for j, b in enumerate(entries[i + 1:], i + 1):
            ra, rb = a.get("bbox"), b.get("bbox")
            if not ra or not rb:
                continue
            dx = min(ra["x"] + ra["w"], rb["x"] + rb["w"]) - max(ra["x"], rb["x"])
            dy = min(ra["y"] + ra["h"], rb["y"] + rb["h"]) - max(ra["y"], rb["y"])
            if dx > 0 and dy > 0:
                area = dx * dy
                if area > 0.5 * min(ra["w"] * ra["h"], rb["w"] * rb["h"]):
                    esiti[i].append(f"riquadro sovrapposto alla battuta {b.get('seq')}")
                    esiti[j].append(f"riquadro sovrapposto alla battuta {a.get('seq')}")
    return esiti


PAGINA = """<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revisione del copione</title>
<style>
:root {
  --sfondo: #f4f2ee; --carta: #fff; --testo: #1c1a17; --tenue: #6b655c;
  --bordo: #d8d3c9; --accento: #b3441a; --evidenza: #fff3c4; --sospetto: #f5b942;
}
@media (prefers-color-scheme: dark) { :root:not([data-tema="chiaro"]) {
  --sfondo: #16150f; --carta: #211f19; --testo: #ece7dc; --tenue: #9a9287;
  --bordo: #3b372e; --accento: #e07a4a; --evidenza: #3d3416; --sospetto: #c4903a;
}}
* { box-sizing: border-box; }
body { margin: 0; background: var(--sfondo); color: var(--testo);
  font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; }
header { position: sticky; top: 0; z-index: 10; background: var(--carta);
  border-bottom: 1px solid var(--bordo); padding: 10px 16px;
  display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
h1 { font-size: 16px; margin: 0 8px 0 0; font-weight: 650; }
nav { display: flex; gap: 4px; flex-wrap: wrap; }
nav button { font: inherit; padding: 3px 9px; border: 1px solid var(--bordo);
  background: transparent; color: var(--testo); border-radius: 6px; cursor: pointer; }
nav button.attiva { background: var(--accento); color: #fff; border-color: var(--accento); }
.avanzo { margin-left: auto; display: flex; gap: 8px; align-items: center; }
.scarica { font: inherit; font-weight: 600; padding: 6px 14px; border-radius: 6px;
  border: 1px solid var(--accento); background: var(--accento); color: #fff; cursor: pointer; }
.stato { color: var(--tenue); font-size: 13px; }
main { display: grid; grid-template-columns: minmax(320px, 46%) 1fr; gap: 16px; padding: 16px;
  align-items: start; }
@media (max-width: 900px) { main { grid-template-columns: 1fr; } }
.tela { position: relative; position: sticky; top: 64px; background: var(--carta);
  border: 1px solid var(--bordo); border-radius: 8px; overflow: hidden; }
.tela img { display: block; width: 100%; height: auto; }
.riq { position: absolute; border: 2px solid rgba(179,68,26,.75); border-radius: 3px;
  cursor: pointer; transition: background .12s, border-color .12s; }
.riq span { position: absolute; top: -1px; left: -1px; background: var(--accento); color: #fff;
  font-size: 11px; font-weight: 700; padding: 0 4px; border-radius: 2px 0 3px 0; }
.riq.viva { background: rgba(255,210,60,.35); border-color: #f5b942; border-width: 3px; }
.lista { display: flex; flex-direction: column; gap: 6px; }
.riga { background: var(--carta); border: 1px solid var(--bordo); border-radius: 8px;
  padding: 8px 10px; display: grid; gap: 6px 8px;
  grid-template-columns: 52px 104px 116px 1fr; align-items: center; }
.riga.viva { border-color: var(--sospetto); box-shadow: 0 0 0 2px var(--evidenza); }
.riga.nuovo-pannello { margin-top: 12px; }
.pos { font: inherit; width: 100%; text-align: center; padding: 3px; border-radius: 5px;
  border: 1px solid var(--bordo); background: transparent; color: var(--testo); }
select, .testo { font: inherit; padding: 4px 6px; border-radius: 5px;
  border: 1px solid var(--bordo); background: transparent; color: var(--testo); width: 100%; }
.testo { min-height: 2.1em; white-space: pre-wrap; }
.sotto { grid-column: 1 / -1; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sotto select { width: auto; }
.testo:focus { outline: 2px solid var(--accento); outline-offset: 1px; }
.attrezzi { display: flex; gap: 3px; }
.attrezzi button { font: 12px/1 inherit; padding: 4px 6px; border: 1px solid var(--bordo);
  background: transparent; color: var(--tenue); border-radius: 5px; cursor: pointer; }
.attrezzi button:hover { color: var(--accento); border-color: var(--accento); }
.pronuncia { grid-column: 4; font-size: 12.5px; color: var(--tenue); padding: 0 6px; }
.pronuncia:empty { display: none; }
.note { grid-column: 1 / -1; font-size: 12.5px; color: #8a5a00; }
.note:empty { display: none; }
@media (prefers-color-scheme: dark) { :root:not([data-tema="chiaro"]) .note { color: var(--sospetto); } }
.note b { font-weight: 600; }
.vuoto { color: var(--tenue); font-style: italic; padding: 24px; text-align: center; }
label.bandierina { display: inline-flex; gap: 5px; align-items: center; font-size: 12.5px;
  color: var(--tenue); white-space: nowrap; cursor: pointer; }
label.bandierina input { margin: 0; }
.pannello { grid-column: 1 / -1; font-size: 12px; color: var(--tenue); letter-spacing: .04em;
  text-transform: uppercase; }
</style></head><body>
<header>
  <h1>Revisione del copione</h1>
  <nav id="nav"></nav>
  <div class="avanzo">
    <span class="stato" id="stato"></span>
    <button class="scarica" id="scarica">Scarica il copione</button>
  </div>
</header>
<main>
  <div class="tela" id="tela"></div>
  <div class="lista" id="lista"></div>
</main>
<script>
const DATI = __DATI__;
const CAST = __CAST__;
const TIPI = __TIPI__;
const CANALI = ["", "sussurro"];
const PRESENTAZIONI = __PRESENTAZIONI__;
let pagina = Object.keys(DATI).map(Number).sort((a,b)=>a-b)[0];
let toccato = false;

const el = (t, p = {}) => Object.assign(document.createElement(t), p);

function segnaTocco() {
  toccato = true;
  document.getElementById("stato").textContent = "modifiche non salvate";
}

function rinumera() {
  DATI[pagina].entries.forEach((e, i) => e.seq = i + 1);
}

function disegna() {
  const d = DATI[pagina];
  const tela = document.getElementById("tela");
  tela.innerHTML = "";
  if (d.immagine) {
    const img = el("img", { src: d.immagine, alt: "pagina " + pagina });
    tela.append(img);
    d.entries.forEach((e, i) => {
      if (!e.bbox) return;
      const r = el("div", { className: "riq" });
      r.style.left   = (100 * e.bbox.x / d.larghezza) + "%";
      r.style.top    = (100 * e.bbox.y / d.altezza)   + "%";
      r.style.width  = (100 * e.bbox.w / d.larghezza) + "%";
      r.style.height = (100 * e.bbox.h / d.altezza)   + "%";
      r.append(el("span", { textContent: e.seq }));
      r.onmouseenter = () => evidenzia(i, true);
      r.onmouseleave = () => evidenzia(i, false);
      r.onclick = () => {
        const riga = document.getElementById("riga" + i);
        riga.scrollIntoView({ block: "center", behavior: "smooth" });
        riga.querySelector(".testo").focus();
      };
      r.dataset.i = i;
      tela.append(r);
    });
  } else {
    tela.append(el("div", { className: "vuoto",
      textContent: "Immagine non trovata per questa pagina." }));
  }

  const lista = document.getElementById("lista");
  lista.innerHTML = "";
  let pannelloPrec = null;
  d.entries.forEach((e, i) => {
    const riga = el("div", { className: "riga", id: "riga" + i });
    if (pannelloPrec !== null && e.panel !== pannelloPrec) riga.classList.add("nuovo-pannello");
    pannelloPrec = e.panel;
    riga.onmouseenter = () => evidenzia(i, true);
    riga.onmouseleave = () => evidenzia(i, false);

    const pos = el("input", { className: "pos", value: e.seq, type: "number", min: 1,
      title: "posizione nell'ordine di lettura: cambiala per spostare la battuta" });
    pos.onchange = () => {
      const a = i, b = Math.max(0, Math.min(d.entries.length - 1, pos.valueAsNumber - 1));
      const [x] = d.entries.splice(a, 1); d.entries.splice(b, 0, x);
      rinumera(); segnaTocco(); disegna();
    };

    const tipo = el("select", { title: "tipo di battuta" });
    TIPI.forEach(t => tipo.append(el("option", { value: t, textContent: t, selected: t === e.type })));
    tipo.onchange = () => { e.type = tipo.value; segnaTocco(); };

    const chi = el("select", { title: "chi parla" });
    CAST.forEach(c => chi.append(el("option", { value: c, textContent: c, selected: c === e.speaker })));
    chi.onchange = () => { e.speaker = chi.value; segnaTocco(); aggiornaNote(i); };

    const attrezzi = el("div", { className: "attrezzi" });
    const bottone = (etichetta, titolo, azione) => {
      const b = el("button", { textContent: etichetta, title: titolo });
      b.onclick = azione; attrezzi.append(b);
    };
    bottone("\\u2191", "sposta su", () => {
      if (i === 0) return;
      [d.entries[i-1], d.entries[i]] = [d.entries[i], d.entries[i-1]];
      rinumera(); segnaTocco(); disegna();
    });
    bottone("\\u2193", "sposta giu'", () => {
      if (i === d.entries.length - 1) return;
      [d.entries[i+1], d.entries[i]] = [d.entries[i], d.entries[i+1]];
      rinumera(); segnaTocco(); disegna();
    });
    bottone("\\u2295", "unisci alla precedente", () => {
      if (i === 0) return;
      d.entries[i-1].text = (d.entries[i-1].text + " " + e.text).trim();
      d.entries.splice(i, 1); rinumera(); segnaTocco(); disegna();
    });
    bottone("+", "aggiungi una battuta dopo questa", () => {
      d.entries.splice(i + 1, 0, { seq: 0, panel: e.panel, type: "dialogue",
        speaker: e.speaker, text: "" });
      rinumera(); segnaTocco(); disegna();
    });
    bottone("\\u2715", "elimina", () => {
      if (!confirm("Eliminare questa battuta?\\n\\n" + e.text)) return;
      d.entries.splice(i, 1); rinumera(); segnaTocco(); disegna();
    });

    const testo = el("div", { className: "testo", contentEditable: "plaintext-only",
      textContent: e.text, spellcheck: false });

    // La pronuncia e' la stessa battuta come la sentira' il sintetizzatore: la calcola
    // poc/pronuncia.py, qui si legge e basta. Si corregge nel dizionario, non riga per riga,
    // perche' una parola resa male e' resa male in tutte le storie.
    const pronuncia = el("div", { className: "pronuncia" });
    const mostraPronuncia = () => {
      pronuncia.textContent = (e.text_tts && e.text_tts !== e.text) ? "\\u266a " + e.text_tts : "";
    };
    mostraPronuncia();

    testo.oninput = () => {
      e.text = testo.textContent;
      // Cambiato il testo, la pronuncia calcolata prima non vale piu' - e siccome la sintesi
      // legge 'text_tts' quando c'e', lasciarla li' vorrebbe dire far leggere la vecchia
      // battuta. Si butta, e si rifa' passare pronuncia.py dopo --applica.
      delete e.text_tts;
      mostraPronuncia();
      segnaTocco(); aggiornaNote(i);
    };

    const radio = el("input", { type: "checkbox", checked: !!e.radio });
    radio.onchange = () => { e.radio = radio.checked; segnaTocco(); };
    const etichettaRadio = el("label", { className: "bandierina" });
    etichettaRadio.append(radio, document.createTextNode("radio"));

    const canale = el("select", { title: "canale" });
    CANALI.forEach(c => canale.append(el("option", { value: c,
      textContent: c || "\\u2014", selected: c === (e.channel || "") })));
    canale.onchange = () => { e.channel = canale.value; segnaTocco(); };

    const sotto = el("div", { className: "sotto" });
    sotto.append(attrezzi, etichettaRadio, canale);

    const note = el("div", { className: "note", id: "note" + i });

    riga.append(pos, tipo, chi, testo, pronuncia, sotto, note);
    lista.append(riga);
    aggiornaNote(i, riga);
  });

  document.querySelectorAll("#nav button").forEach(b =>
    b.classList.toggle("attiva", Number(b.dataset.p) === pagina));
}

function evidenzia(i, acceso) {
  const riga = document.getElementById("riga" + i);
  if (riga) riga.classList.toggle("viva", acceso);
  const r = document.querySelector('.riq[data-i="' + i + '"]');
  if (r) r.classList.toggle("viva", acceso);
}

function aggiornaNote(i) {
  const e = DATI[pagina].entries[i];
  const note = document.getElementById("note" + i);
  if (!note) return;
  const motivi = [];
  const chi = (e.speaker || "").toLowerCase();
  // Alla radio ci si annuncia col proprio nome ("Ranger Hilde a Picco Fiocco!"): e' un
  // nominativo, non un vocativo, e senza questa eccezione il controllo grida a ogni chiamata.
  if (chi && chi !== "narratore" && !e.radio) {
    const t = " " + (e.text || "").toUpperCase().normalize("NFD").replace(/\p{M}/gu, "")
      .replace(/[^A-Z0-9']+/g, " ").trim() + " ";
    const N = chi.toUpperCase();
    const presenta = PRESENTAZIONI.some(f => t.includes(" " + f + " " + N + " "));
    if (t.includes(" " + N + " ") && !presenta)
      motivi.push("nomina <b>" + chi + "</b>: chi viene chiamato per nome di solito non parla");
  }
  if (!e.bbox) motivi.push("nessun riquadro sulla pagina");
  if (!(e.text || "").trim()) motivi.push("testo vuoto");
  note.innerHTML = motivi.length ? "\\u26a0 " + motivi.join(" \\u00b7 ") : "";
}

// Separata dal download perche' cosi' si puo' provare: il collaudo la chiama e confronta il
// risultato con il copione di partenza, senza passare da un file scaricato a mano.
function costruisciUscita() {
  const fuori = {};
  for (const [p, d] of Object.entries(DATI)) {
    fuori[p] = { page: Number(p), entries: d.entries.map(e => {
      const b = { seq: e.seq, panel: e.panel, type: e.type, speaker: e.speaker, text: e.text };
      if (e.text_tts) b.text_tts = e.text_tts;
      if (e.radio) b.radio = true;
      if (e.channel) b.channel = e.channel;
      if (e.bbox) b.bbox = e.bbox;
      return b;
    })};
  }
  return fuori;
}

function scarica() {
  const blob = new Blob([JSON.stringify(costruisciUscita(), null, 2)], { type: "application/json" });
  const a = el("a", { href: URL.createObjectURL(blob), download: "copione-rivisto.json" });
  a.click(); URL.revokeObjectURL(a.href);
  toccato = false;
  document.getElementById("stato").textContent = "scaricato";
}

const nav = document.getElementById("nav");
Object.keys(DATI).map(Number).sort((a,b)=>a-b).forEach(p => {
  const b = el("button", { textContent: p });
  b.dataset.p = p;
  b.onclick = () => { pagina = p; disegna(); window.scrollTo({ top: 0 }); };
  nav.append(b);
});
document.getElementById("scarica").onclick = scarica;
window.onbeforeunload = () => toccato ? "Ci sono modifiche non salvate." : undefined;
disegna();
</script></body></html>
"""


def genera(cartella, uscita):
    pagine = carica(cartella)
    uscita.mkdir(parents=True, exist_ok=True)
    dati, senza_immagine, sospette = {}, [], 0
    for numero in sorted(pagine):
        d = pagine[numero]
        nome, (larghezza, altezza) = immagine_pagina(numero, uscita)
        if nome is None:
            senza_immagine.append(numero)
        sospette += sum(1 for m in controlli(d["entries"]) if m)
        dati[str(numero)] = {"entries": d["entries"], "immagine": nome,
                             "larghezza": larghezza, "altezza": altezza}

    testo = (PAGINA
             .replace("__DATI__", json.dumps(dati, ensure_ascii=False))
             .replace("__CAST__", json.dumps(E.cast_da_voices(), ensure_ascii=False))
             .replace("__TIPI__", json.dumps(E.TIPI, ensure_ascii=False))
             .replace("__PRESENTAZIONI__", json.dumps(PRESENTAZIONI, ensure_ascii=False)))
    (uscita / "index.html").write_text(testo, encoding="utf-8")

    battute = sum(len(d["entries"]) for d in pagine.values())
    print(f"{len(pagine)} pagine, {battute} battute  ->  {breve(uscita)}/index.html")
    if senza_immagine:
        print(f"  !! senza immagine: {', '.join('p' + str(p) for p in senza_immagine)}")
    senza_riquadro = sum(1 for d in pagine.values() for e in d["entries"] if not e.get("bbox"))
    if senza_riquadro:
        print(f"  !! {senza_riquadro} battute senza riquadro: si rivedono, ma non si possono "
              f"indicare sulla pagina (rilancia l'estrazione con --riquadri)")
    print(f"  {sospette} battute portano un controllo acceso — sono un avviso, non un filtro: "
          f"vanno guardate tutte")
    print(f"\n  apri:  file://{(uscita / 'index.html').resolve()}")


def applica(percorso, destinazione):
    fuori = json.loads(Path(percorso).read_text(encoding="utf-8"))
    destinazione.mkdir(parents=True, exist_ok=True)
    for chiave, d in sorted(fuori.items(), key=lambda kv: int(kv[0])):
        numero = int(d.get("page", chiave))
        f = destinazione / f"p{numero}.json"
        if f.exists():
            shutil.copy2(f, f.with_suffix(".json.prima"))
        f.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  p{numero}: {len(d['entries'])} battute")
    print(f"\n{len(fuori)} pagine scritte in {breve(destinazione)}"
          f"   (le versioni precedenti sono accanto, con estensione .json.prima)")


def main():
    ap = argparse.ArgumentParser(
        description="Pagina HTML per rivedere a mano il copione estratto.")
    ap.add_argument("copione", nargs="?", help="cartella di pNN.json da rivedere")
    ap.add_argument("--uscita", default=str(POC / "revisione"),
                    help="dove scrivere la pagina HTML e le immagini")
    ap.add_argument("--applica", metavar="FILE",
                    help="riporta un copione-rivisto.json scaricato dalla pagina nei pNN.json")
    ap.add_argument("--destinazione", default=str(POC / "script"),
                    help="con --applica: dove scrivere i pNN.json corretti")
    args = ap.parse_args()

    if args.applica:
        applica(args.applica, Path(args.destinazione))
    elif args.copione:
        genera(args.copione, Path(args.uscita))
    else:
        ap.error("serve una cartella da rivedere, oppure --applica")


if __name__ == "__main__":
    main()
