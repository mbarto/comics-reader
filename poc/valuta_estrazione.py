#!/usr/bin/env python3
"""Confronta un copione estratto in automatico con quello trascritto a mano.

Il PoC ha lasciato aperto il problema piu' grosso: le 131 battute sono state lette e trascritte
a mano, una per una, e per un secondo fumetto il conto ricomincia da zero. Prima di provare ad
automatizzare quel lavoro serve un metro, se no ogni variante si giudica a impressione - ed e'
gia' successo, col suono, di inseguire per ore un difetto che non c'era.

Il metro esiste gia' e non costa niente: 'poc/script/oro/' sono 131 battute verificate a mano,
con ordine, parlante e tipo. Questo script ci confronta un copione qualsiasi e stampa i numeri
che decidono se una variante e' meglio di un'altra.

    poc/valuta_estrazione.py CANDIDATO [--oro poc/script/oro] [--pagina 41] [--dettagli] [--json]

CANDIDATO e' una cartella di pNN.json, o un singolo file.

Quattro misure, in ordine di gravita' del danno che il difetto fa all'ascolto:

  battute   quante ne ha trovate e quante se n'e' inventate. Una saltata e' una battuta muta,
            una in piu' e' una voce che legge qualcosa che non c'e'.
  ordine    inversioni e tau di Kendall. Sbagliare l'ordine rovina il dialogo anche quando ogni
            singola battuta e' trascritta alla perfezione.
  parlante  percentuale di attribuzioni esatte. E' la parte difficile: dipende dalla coda del
            balloon, dal colore e da chi e' inquadrato, non dalle lettere.
  testo     tasso d'errore per parola (WER) sulle battute accoppiate. E' la parte che un OCR
            farebbe gia' oggi, ed e' quella che ci si aspetta vada meglio.

In piu', perche' cambiano l'audio e non si vedono nel testo: il 'tipo' (sfx e credits hanno una
regia loro in voices.json) e i flag 'radio'/'channel'.

Come vengono accoppiate le battute. Non per posizione - basterebbe un balloon saltato a sfasare
tutto il resto e il punteggio del testo crollerebbe per un errore d'ordine. Si accoppiano per
somiglianza del testo, dentro la stessa pagina, prendendo le coppie piu' simili per prime. Sotto
'SOGLIA_COPPIA' non e' la stessa battuta: e' una mancata piu' una di troppo.

Il limite di questo metodo, dichiarato: una battuta trovata nel posto giusto ma trascritta cosi'
male da non somigliare piu' all'originale viene contata come mancante, non come errore di testo.
Il punteggio delle battute e quello del testo non sono quindi del tutto indipendenti. E' un caso
che nella pratica si vede poco, e l'alternativa - accoppiare per coordinate - richiederebbe i
riquadri, che il copione d'oro non ha.

Non misura 'text_tts': e' una trasformazione deterministica a valle (dizionario di pronuncia),
non un compito del modello. Se e' assente dal candidato non e' un errore.
"""

import argparse
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

POC = Path(__file__).resolve().parent
ORO_DEFAULT = POC / "script" / "oro"

# Sotto questa somiglianza (0 = niente in comune, 1 = identiche) due battute non sono la stessa.
# 0,45 tiene accoppiate trascrizioni mediocri ma riconoscibili, e separa battute diverse dello
# stesso personaggio, che in un fumetto si somigliano parecchio ("GIA'!" / "GIA', MATT!").
SOGLIA_COPPIA = 0.45

CAMPI_FLAG = ("radio", "channel")


# ---------------------------------------------------------------- normalizzazione e distanze

def normalizza(testo):
    """Il testo ridotto a cio' che conta per dire se e' stato letto bene.

    Il campo 'text' e' il testo come stampato, e il lettering dei fumetti e' tutto maiuscolo con
    gli accenti resi da un apostrofo: CAFFE'. Un candidato ragionevole puo' scrivere "Caffe'",
    "CAFFE'" o "caffe`" e aver letto benissimo. Quindi: minuscolo, via gli accenti, l'apostrofo
    diventa spazio (se no "l'inizio" farebbe una parola sola e "L' INIZIO" due), via la
    punteggiatura, spazi compattati.
    """
    t = unicodedata.normalize("NFD", testo or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    fuori = []
    for c in t:
        if c.isalnum():
            fuori.append(c)
        else:
            fuori.append(" ")
    return " ".join("".join(fuori).split())


def parole(testo):
    return normalizza(testo).split()


def distanza(a, b):
    """Levenshtein su liste di parole: quante sostituzioni, inserimenti e cancellazioni."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    riga = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prec, riga[0] = riga[0], i
        for j, cb in enumerate(b, 1):
            costo = prec + (ca != cb)
            prec = riga[j]
            riga[j] = min(riga[j] + 1, riga[j - 1] + 1, costo)
    return riga[-1]


def somiglianza(a, b):
    pa, pb = parole(a), parole(b)
    if not pa and not pb:
        return 1.0
    massimo = max(len(pa), len(pb))
    return 1.0 - distanza(pa, pb) / massimo if massimo else 1.0


# ---------------------------------------------------------------- accoppiamento

def accoppia(candidate, oro):
    """Accoppia le battute di una pagina per somiglianza del testo, le piu' simili per prime.

    Restituisce (coppie, cand_in_piu', oro_mancanti). Le coppie sono (indice_cand, indice_oro,
    somiglianza). Avido, non ottimo: dentro una pagina ci sono una decina di battute e testi
    distinti, quindi la differenza con un assegnamento ottimo e' teorica. Se un giorno non lo
    fosse piu', si vedrebbe come un punteggio del testo peggiore del vero, mai migliore.
    """
    punteggi = []
    for i, c in enumerate(candidate):
        for j, o in enumerate(oro):
            s = somiglianza(c.get("text", ""), o.get("text", ""))
            if s >= SOGLIA_COPPIA:
                punteggi.append((s, i, j))
    punteggi.sort(key=lambda x: (-x[0], x[1], x[2]))

    presi_c, presi_o, coppie = set(), set(), []
    for s, i, j in punteggi:
        if i in presi_c or j in presi_o:
            continue
        presi_c.add(i)
        presi_o.add(j)
        coppie.append((i, j, s))
    return (coppie,
            [i for i in range(len(candidate)) if i not in presi_c],
            [j for j in range(len(oro)) if j not in presi_o])


def inversioni(coppie, candidate, oro):
    """Quante coppie di battute il candidato mette in ordine invertito rispetto all'oro.

    Si guardano i 'seq', non le posizioni nella lista: un copione puo' elencare le battute in
    ordine sparso e dichiarare la sequenza giusta, e sarebbe corretto.
    """
    punti = sorted(((oro[j].get("seq", j), candidate[i].get("seq", i)) for i, j, _ in coppie))
    n = len(punti)
    disc = sum(1 for a in range(n) for b in range(a + 1, n) if punti[a][1] > punti[b][1])
    totali = n * (n - 1) // 2
    return disc, totali


# ---------------------------------------------------------------- valutazione

def carica(percorso):
    """Le pagine di un copione: {numero_pagina: [battute]}. Accetta cartella o singolo file."""
    percorso = Path(percorso)
    file = ([percorso] if percorso.is_file()
            else sorted(p for p in percorso.glob("p*.json") if p.stem[1:].isdigit()))
    if not file:
        sys.exit(f"Nessun pNN.json in {percorso}")
    pagine = {}
    for f in file:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            sys.exit(f"{f}: JSON non valido ({e})")
        entries = d.get("entries")
        if entries is None:
            sys.exit(f"{f}: manca la chiave 'entries'")
        pagine[d.get("page", int(f.stem[1:]))] = entries
    return pagine


def flag(e):
    """I campi che cambiano la resa audio senza comparire nel testo."""
    return tuple(str(e.get(c)) if e.get(c) is not None else "" for c in CAMPI_FLAG)


def valuta(cand_pagine, oro_pagine):
    r = {
        "oro_totale": 0, "cand_totale": 0, "accoppiate": 0,
        "mancanti": [], "in_piu": [],
        "parole_oro": 0, "errori_parole": 0, "testo_esatto": 0,
        "parlante_ok": 0, "tipo_ok": 0, "flag_ok": 0,
        "disc": 0, "coppie_ordinabili": 0, "pagine_in_ordine": 0, "pagine_confrontate": 0,
        "confusioni": Counter(), "pagine_assenti": [], "per_pagina": {}, "peggiori": [],
    }

    for pagina in sorted(oro_pagine):
        oro = oro_pagine[pagina]
        r["oro_totale"] += len(oro)
        if pagina not in cand_pagine:
            r["pagine_assenti"].append(pagina)
            r["mancanti"] += [(pagina, e.get("seq"), e.get("text", "")) for e in oro]
            r["parole_oro"] += sum(len(parole(e.get("text", ""))) for e in oro)
            r["errori_parole"] += sum(len(parole(e.get("text", ""))) for e in oro)
            continue

        cand = cand_pagine[pagina]
        r["cand_totale"] += len(cand)
        r["pagine_confrontate"] += 1
        coppie, in_piu, mancanti = accoppia(cand, oro)
        r["accoppiate"] += len(coppie)
        r["mancanti"] += [(pagina, oro[j].get("seq"), oro[j].get("text", "")) for j in mancanti]
        r["in_piu"] += [(pagina, cand[i].get("seq"), cand[i].get("text", "")) for i in in_piu]

        # le battute non accoppiate pesano comunque sul testo: tutte le loro parole sono errori
        for j in mancanti:
            n = len(parole(oro[j].get("text", "")))
            r["parole_oro"] += n
            r["errori_parole"] += n

        p_esatto = p_parlante = 0
        for i, j, _ in coppie:
            c, o = cand[i], oro[j]
            po, pc = parole(o.get("text", "")), parole(c.get("text", ""))
            d = distanza(pc, po)
            r["parole_oro"] += len(po)
            r["errori_parole"] += d
            if d == 0:
                r["testo_esatto"] += 1
                p_esatto += 1
            elif len(po):
                r["peggiori"].append((d / len(po), pagina, o.get("seq"),
                                      o.get("text", ""), c.get("text", "")))

            pari = (str(c.get("speaker", "")).strip().lower()
                    == str(o.get("speaker", "")).strip().lower())
            r["parlante_ok"] += pari
            p_parlante += pari
            if not pari:
                r["confusioni"][(o.get("speaker"), c.get("speaker"))] += 1
            r["tipo_ok"] += (str(c.get("type", "")).strip().lower()
                             == str(o.get("type", "")).strip().lower())
            r["flag_ok"] += flag(c) == flag(o)

        disc, tot = inversioni(coppie, cand, oro)
        r["disc"] += disc
        r["coppie_ordinabili"] += tot
        if disc == 0:
            r["pagine_in_ordine"] += 1
        r["per_pagina"][pagina] = {
            "oro": len(oro), "cand": len(cand), "accoppiate": len(coppie),
            "mancanti": len(mancanti), "in_piu": len(in_piu),
            "testo_esatto": p_esatto, "parlante_ok": p_parlante, "inversioni": disc,
        }

    r["peggiori"].sort(reverse=True)
    return r


def percentuale(n, d):
    return 100.0 * n / d if d else float("nan")


def tau(r):
    if not r["coppie_ordinabili"]:
        return float("nan")
    return 1.0 - 2.0 * r["disc"] / r["coppie_ordinabili"]


# ---------------------------------------------------------------- stampa

def stampa(r, dettagli):
    acc, oro_tot, cand_tot = r["accoppiate"], r["oro_totale"], r["cand_totale"]
    richiamo, precisione = percentuale(acc, oro_tot), percentuale(acc, cand_tot)
    wer = percentuale(r["errori_parole"], r["parole_oro"])

    pagine = sorted(r["per_pagina"]) + r["pagine_assenti"]
    print(f"confronto su {len(pagine)} pagin{'a' if len(pagine) == 1 else 'e'}: "
          f"{', '.join('p' + str(p) for p in sorted(pagine))}")
    if r.get("ignorate"):
        print(f"           {len(r['ignorate'])} pagine d'oro non sono nel candidato e restano "
              f"fuori dal conto ({', '.join('p' + str(p) for p in r['ignorate'])}); "
              f"con --tutte varrebbero come mancanti")
    if r.get("fuori_oro"):
        print(f"           {len(r['fuori_oro'])} pagine del candidato non hanno un riferimento "
              f"d'oro e restano fuori dal conto "
              f"({', '.join('p' + str(p) for p in r['fuori_oro'])})")
    if r["pagine_assenti"]:
        print(f"        !! {len(r['pagine_assenti'])} pagine assenti dal candidato, contate "
              f"come mancanti: {', '.join('p' + str(p) for p in r['pagine_assenti'])}")
    print()

    print(f"battute    trovate {acc}/{oro_tot}  ({richiamo:.1f}% di richiamo)")
    print(f"           su {cand_tot} proposte   ({precisione:.1f}% di precisione)")
    print(f"           {len(r['mancanti'])} mancanti, {len(r['in_piu'])} di troppo")
    print()
    print(f"ordine     {r['disc']} inversioni su {r['coppie_ordinabili']} coppie"
          f"   (tau = {tau(r):.3f})")
    print(f"           {r['pagine_in_ordine']}/{r['pagine_confrontate']} pagine"
          f" in ordine perfetto")
    print()
    print(f"parlante   {percentuale(r['parlante_ok'], acc):.1f}% esatto"
          f"   ({r['parlante_ok']}/{acc})")
    print(f"tipo       {percentuale(r['tipo_ok'], acc):.1f}% esatto"
          f"   ({r['tipo_ok']}/{acc})")
    print(f"flag       {percentuale(r['flag_ok'], acc):.1f}% esatto"
          f"   ({r['flag_ok']}/{acc})     radio, channel")
    print()
    print(f"testo      WER {wer:.1f}%"
          f"   ({r['errori_parole']} errori su {r['parole_oro']} parole)")
    print(f"           {r['testo_esatto']}/{oro_tot} battute trascritte alla lettera"
          f"  ({percentuale(r['testo_esatto'], oro_tot):.1f}%)")

    if r["confusioni"]:
        print("\nattribuzioni sbagliate piu' frequenti (oro -> candidato):")
        for (o, c), n in r["confusioni"].most_common(5):
            print(f"  {n:>3}x  {o} -> {c}")

    if dettagli:
        if r["mancanti"]:
            print(f"\nbattute mancanti ({len(r['mancanti'])}):")
            for pag, seq, testo in r["mancanti"]:
                print(f"  p{pag} #{seq}  {testo[:70]}")
        if r["in_piu"]:
            print(f"\nbattute di troppo ({len(r['in_piu'])}):")
            for pag, seq, testo in r["in_piu"]:
                print(f"  p{pag} #{seq}  {testo[:70]}")
        if r["peggiori"]:
            print("\ntrascrizioni peggiori:")
            for tasso, pag, seq, o, c in r["peggiori"][:10]:
                print(f"  p{pag} #{seq}  ({tasso:.0%} di errore)")
                print(f"      oro: {o[:78]}")
                print(f"      cand: {c[:78]}")
        print("\nper pagina:")
        print(f"  {'pag':>4} {'oro':>4} {'cand':>5} {'acc':>4} {'manc':>5} {'+':>3}"
              f" {'testo':>6} {'parl':>5} {'inv':>4}")
        for pag in sorted(r["per_pagina"]):
            p = r["per_pagina"][pag]
            print(f"  {pag:>4} {p['oro']:>4} {p['cand']:>5} {p['accoppiate']:>4}"
                  f" {p['mancanti']:>5} {p['in_piu']:>3} {p['testo_esatto']:>6}"
                  f" {p['parlante_ok']:>5} {p['inversioni']:>4}")

    print(f"\nuna riga sola:  battute {richiamo:.0f}/{precisione:.0f}%"
          f"  ordine tau {tau(r):.2f}"
          f"  parlante {percentuale(r['parlante_ok'], acc):.0f}%"
          f"  testo WER {wer:.1f}%")


def come_json(r):
    acc = r["accoppiate"]
    return {
        "battute_oro": r["oro_totale"], "battute_candidato": r["cand_totale"],
        "accoppiate": acc,
        "richiamo": percentuale(acc, r["oro_totale"]) / 100,
        "precisione": percentuale(acc, r["cand_totale"]) / 100,
        "mancanti": len(r["mancanti"]), "in_piu": len(r["in_piu"]),
        "inversioni": r["disc"], "coppie_ordinabili": r["coppie_ordinabili"],
        "tau": tau(r),
        "pagine_in_ordine": r["pagine_in_ordine"],
        "pagine_confrontate": r["pagine_confrontate"],
        "parlante": percentuale(r["parlante_ok"], acc) / 100,
        "tipo": percentuale(r["tipo_ok"], acc) / 100,
        "flag": percentuale(r["flag_ok"], acc) / 100,
        "wer": percentuale(r["errori_parole"], r["parole_oro"]) / 100,
        "testo_esatto": percentuale(r["testo_esatto"], r["oro_totale"]) / 100,
        "pagine_confrontate_elenco": sorted(r["per_pagina"]),
        "pagine_assenti": r["pagine_assenti"],
        "pagine_ignorate": r.get("ignorate", []),
        "pagine_fuori_oro": r.get("fuori_oro", []),
        "per_pagina": r["per_pagina"],
    }


def main():
    ap = argparse.ArgumentParser(
        description="Confronta un copione estratto con quello trascritto a mano.")
    ap.add_argument("candidato", help="cartella di pNN.json, o un singolo file")
    ap.add_argument("--oro", default=str(ORO_DEFAULT), help="copione di riferimento")
    ap.add_argument("--pagina", type=int, action="append",
                    help="limita a una pagina (ripetibile)")
    ap.add_argument("--tutte", action="store_true",
                    help="conta come mancanti le pagine d'oro che il candidato non ha "
                         "(di suo il confronto si limita alle pagine presenti in entrambi)")
    ap.add_argument("--dettagli", action="store_true",
                    help="elenca gli errori uno per uno e la tabella per pagina")
    ap.add_argument("--json", action="store_true", help="stampa solo i numeri, in JSON")
    args = ap.parse_args()

    oro = carica(args.oro)
    cand = carica(args.candidato)
    if args.pagina:
        volute = set(args.pagina)
        mancanti = volute - set(oro)
        if mancanti:
            sys.exit(f"Il copione d'oro non ha la pagina "
                     f"{', '.join(str(p) for p in sorted(mancanti))}")
        oro = {p: v for p, v in oro.items() if p in volute}
        cand = {p: v for p, v in cand.items() if p in volute}

    # Di suo il confronto si limita alle pagine che ci sono da entrambe le parti: provare
    # l'estrattore su una pagina sola e' il caso normale, e contare le altre undici come
    # mancanti darebbe un WER del 96% che non dice niente. Con --tutte si contano, ed e' quello
    # che serve quando si valuta una storia intera e una pagina non e' stata prodotta.
    ignorate = sorted(set(oro) - set(cand))
    if ignorate and not args.tutte:
        oro = {p: v for p, v in oro.items() if p in cand}
    fuori = sorted(set(cand) - set(oro)) if not args.tutte else []
    if fuori:
        cand = {p: v for p, v in cand.items() if p in oro}

    if not oro:
        sys.exit("Nessuna pagina in comune fra candidato e copione d'oro.")

    r = valuta(cand, oro)
    r["ignorate"] = [] if args.tutte else ignorate
    r["fuori_oro"] = fuori
    if args.json:
        print(json.dumps(come_json(r), ensure_ascii=False, indent=2))
    else:
        stampa(r, args.dettagli)


if __name__ == "__main__":
    main()
