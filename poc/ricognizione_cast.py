#!/usr/bin/env python3
"""Guarda le prime pagine di un fumetto e propone il cast: chi parla, e come si riconosce.

Il buco piu' grosso del piano (poc/PIANO-estrazione.md, §9). L'attribuzione dei personaggi passa
dal 66% al 90% solo grazie alla scheda del cast, che per Park Ranger e' scritta a mano in
voices.json. Per una storia mai vista quel file non esiste: questo script lo propone, e un occhio
umano lo corregge prima di far partire l'estrazione.

    poc/.venv-estrazione/bin/python poc/ricognizione_cast.py pages/render/p4*.png
    poc/.venv-estrazione/bin/python poc/ricognizione_cast.py pages/render/p4*.png --voices nuovo.json

Una sola chiamata con tutte le pagine insieme: il cast si vede solo guardando piu' pagine di
seguito - chi ricorre, come lo chiamano gli altri, chi ha una battuta sola.

TRE COSE CHE FA, E UNA CHE NON FA.

 - Distingue i personaggi NOTI (Paperino, Paperone, i nipoti: il modello li riconosce) da quelli
   INVENTATI per la storia, che esistono solo li' dentro. Per i secondi la descrizione e' l'unica
   cosa che permettera' di distinguerli, ed e' li' che deve essere precisa.
 - Ordina per numero di battute e propone la voce propria solo ai principali. Il PoC si e' fermato
   a sette personaggi e TECNOLOGIE.md dice che e' gia' oltre quello che Chatterbox sa distinguere:
   le comparse vanno sul narratore, se no si spendono voci per una battuta sola.
 - Scrive un voices.json di partenza, tenendo dal file esistente tutto cio' che non dipende dal
   cast (pulizia, canali, pause, EQ).

 - NON sa tarare le voci. 'speed', 'pitch', 'exaggeration' escono con valori prudenti e vanno
   regolati a orecchio: e' la lezione 2 e 4 del §8 di TECNOLOGIE.md, e nessuna misura automatica
   sa dire se una voce e' giusta per un personaggio.
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estrai_copione as E  # noqa: E402

POC = Path(__file__).resolve().parent
ROOT = POC.parent

# Valori di partenza per un personaggio nuovo: quelli del narratore del PoC, cioe' la voce
# naturale senza trucchi. Si parte da li' e si tara a orecchio, non il contrario.
BASE = {"speed": 1.0, "pitch": 1.0, "gain_db": 0.0, "filters": [],
        "exaggeration": 0.6, "cfg_weight": 0.45}


def schema(massimo):
    personaggio = {
        "nome": {"type": "string",
                 "description": "chiave breve, minuscola, senza spazi: il nome proprio se la "
                                "storia lo dice, se no una parola che lo descriva"},
        "nome_in_chiaro": {"type": "string",
                           "description": "come lo chiamano nella storia; vuoto se non lo "
                                          "nominano mai"},
        "noto": {"type": "boolean",
                 "description": "vero se e' un personaggio famoso riconoscibile da chiunque, "
                                "falso se esiste solo in questa storia"},
        "descrizione": {"type": "string",
                        "description": "chi e': ruolo, carattere, cosa fa nella storia. Deve "
                                       "bastare a distinguerlo dagli altri del cast"},
        "come_riconoscerlo": {"type": "string",
                              "description": "i tratti visibili: eta', corporatura, vestiti, "
                                             "colore, cosa porta con se'"},
        "battute": {"type": "integer",
                    "description": "quante battute gli si possono attribuire in queste pagine"},
        "voce_propria": {"type": "boolean",
                         "description": f"vero per i principali, al massimo {massimo}; falso per "
                                        f"le comparse, che leggera' il narratore"},
    }
    return {
        "type": "object",
        "properties": {
            "storia": {"type": "string", "description": "il titolo, se compare"},
            "personaggi": {"type": "array",
                           "items": {"type": "object", "properties": personaggio,
                                     "required": list(personaggio),
                                     "additionalProperties": False}},
            "note": {"type": "string",
                     "description": "cio' di cui non sei sicuro: personaggi mai nominati, due "
                                    "che si somigliano, chi compare ma non parla"},
        },
        "required": ["storia", "personaggi", "note"],
        "additionalProperties": False,
    }


def istruzioni(massimo, quante):
    return f"""Stai preparando la lettura ad alta voce di un fumetto e devi decidere il cast.
Ti do {quante} pagine di seguito della stessa storia. Elenca CHI PARLA, in modo che poi qualcuno
- che vedra' una pagina per volta, senza il resto - riesca a capire chi dice cosa.

E' questo il punto: la tua descrizione e' l'unico appiglio che avra'. Se due personaggi si
somigliano e tu scrivi "un turista", chi legge una vignetta affollata non potra' distinguerli.
Scrivi cosa li separa: chi e' vecchio e chi giovane, chi e' grasso e chi magro, di che colore e'
il vestito, chi porta lo zaino, chi ansima e chi comanda, come parla ciascuno.

CHI METTERE. Solo chi PRONUNCIA qualcosa: dialoghi, ma anche un verso o un'onomatopea che esca da
lui. Chi compare e non parla non entra nel cast; mettilo semmai nelle note.

'noto' vero solo per i personaggi che chiunque riconoscerebbe (Paperino, Paperone, Topolino,
Qui Quo Qua...). Per quelli inventati per questa storia vale falso, e per loro la descrizione
conta il doppio, perche' non c'e' nient'altro a cui appoggiarsi.

'nome': se la storia lo chiama per nome, usa quello, minuscolo. Se non lo nomina mai, scegli una
parola che lo descriva (per esempio "panettiere", "turista", "capostazione") e lascia
'nome_in_chiaro' vuoto: e' un segnale utile, vuol dire che nessuno in pagina lo chiamera' mai.

'battute': contale davvero, non stimarle a occhio. Serve a decidere chi merita una voce.

'voce_propria': al massimo {massimo} personaggi, quelli con piu' battute. Tutti gli altri a falso:
le loro battute le leggera' il narratore. Non e' un giudizio sul personaggio, e' che oltre una
mezza dozzina di voci quelle in piu' non si distinguono all'ascolto.

IL NARRATORE non va nell'elenco: c'e' sempre, e legge le didascalie, il titolo, i crediti e le
onomatopee che non vengono da nessuno.

Nelle 'note' scrivi cio' di cui NON sei sicuro: un personaggio che non viene mai nominato, due che
potresti aver confuso, qualcuno che forse compare piu' avanti. Meglio un dubbio dichiarato che una
descrizione sicura e sbagliata."""


def proponi(client, immagini, modello, sforzo, massimo, rifai):
    contenuto, pagine = [], []
    for percorso in immagini:
        dati, media, _, _, _ = E.prepara(percorso, E.FASCIA_DI.get(modello, "alta"), "jpeg", 90)
        nome = Path(percorso).stem
        pagine.append(nome)
        contenuto.append({"type": "text", "text": f"Pagina {nome}:"})
        contenuto.append({"type": "image", "source": {
            "type": "base64", "media_type": media,
            "data": base64.b64encode(dati).decode()}})
    contenuto.append({"type": "text",
                      "text": "Chi parla in questa storia? Preparane il cast."})

    regole = istruzioni(massimo, len(immagini))
    sch = schema(massimo)
    chiave = E.impronta(regole, json.dumps(sch, sort_keys=True), modello, sforzo,
                        *(str(p) for p in immagini))
    cache = POC / "estrazione" / "cache-cast" / f"{chiave}.json"
    if cache.exists() and not rifai:
        salvato = json.loads(cache.read_text(encoding="utf-8"))
        salvato["misura"]["da_cache"] = True
        return salvato["cast"], salvato["misura"]

    risposta = client.messages.create(
        model=modello, max_tokens=16000,
        system=[{"type": "text", "text": regole, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": contenuto}],
        output_config={"effort": sforzo, "format": {"type": "json_schema", "schema": sch}},
        thinking={"type": "adaptive"},
    )
    if risposta.stop_reason == "max_tokens":
        sys.exit("Risposta troncata: rilancia con meno pagine.")
    testo = next(b.text for b in risposta.content if b.type == "text")
    cast = json.loads(testo)

    u = risposta.usage
    pin, pout = E.PREZZI.get(modello, (0.0, 0.0))
    misura = {
        "pagine": pagine, "modello": modello, "sforzo": sforzo,
        "token_ingresso": u.input_tokens + (u.cache_read_input_tokens or 0)
        + (u.cache_creation_input_tokens or 0),
        "token_uscita": u.output_tokens,
        "costo_usd": round((u.input_tokens * pin
                            + (u.cache_creation_input_tokens or 0) * pin * 1.25
                            + (u.cache_read_input_tokens or 0) * pin * 0.1
                            + u.output_tokens * pout) / 1e6, 4),
        "da_cache": False,
    }
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"cast": cast, "misura": misura}, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    return cast, misura


def assegna_voci(cast, massimo):
    """Chi ha voce propria lo decide l'aritmetica, non il modello.

    Glielo si chiede lo stesso nel prompt - serve a fargli contare le battute sul serio - ma la
    scelta finale si rifa' qui: alla prova su 'le copie a ripetizione' aveva dato voce a un
    personaggio da 3 battute lasciandone fuori uno da 6. Ordinare e tagliare e' una riga, e non
    c'e' motivo di affidarla a un giudizio.
    """
    ordinati = sorted(cast["personaggi"], key=lambda p: (-p["battute"], p["nome"]))
    for posto, p in enumerate(ordinati):
        p["voce_propria"] = posto < massimo
    cast["personaggi"] = ordinati
    return cast


def scrivi_voices(cast, modello_voices, destinazione):
    """Un voices.json di partenza: la regia del cast e' nuova, tutto il resto si eredita."""
    base = json.loads(Path(modello_voices).read_text(encoding="utf-8"))
    narratore = dict(
        BASE, descrizione="Didascalie, titolo, crediti e le onomatopee che non vengono da nessuno. "
                          "Neutro, un filo piu' lento e posato.", speed=0.94)
    parlanti = {"narratore": narratore}

    # ANCHE le comparse entrano nel cast, con i parametri del narratore. Devono restare
    # NOMINABILI: alla prima prova su 'le copie a ripetizione' il venditore di posate, retrocesso
    # perche' ha una battuta sola, era sparito dall'elenco - e la sua battuta e' finita al cuoco,
    # che e' l'altro personaggio col muso da cane. Se il modello non puo' dire "il venditore",
    # non tace: sceglie il meno sbagliato fra quelli che gli restano.
    # Suonando come il narratore, il risultato e' quello voluto senza toccare la sintesi.
    for p in cast["personaggi"]:
        pezzi = [p["descrizione"].strip()]
        if p.get("come_riconoscerlo"):
            pezzi.append(f"Si riconosce da: {p['come_riconoscerlo'].strip()}")
        if not p.get("nome_in_chiaro"):
            pezzi.append("Nella storia non viene mai chiamato per nome.")
        if not p["voce_propria"]:
            pezzi.append("COMPARSA: ha poche battute, e le legge il narratore. "
                         "Va comunque riconosciuto, se no le sue battute finiscono a qualcun altro.")
        voce = dict(narratore) if not p["voce_propria"] else dict(BASE)
        parlanti[p["nome"]] = dict(voce, descrizione=" ".join(pezzi))
    base["speakers"] = parlanti
    base["cast_nota"] = (
        "Cast proposto da poc/ricognizione_cast.py e DA RIVEDERE. Le descrizioni servono "
        "all'estrazione del copione, che senza di esse sbaglia un'attribuzione su tre. I valori "
        "di voce (speed, pitch, exaggeration, cfg_weight) sono di partenza, non tarati: vanno "
        "regolati a orecchio, uno per volta.")
    Path(destinazione).write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")


def stampa(cast, misura):
    print(f"\nstoria: {cast['storia'] or '(titolo non trovato)'}")
    principali = [p for p in cast["personaggi"] if p["voce_propria"]]
    comparse = [p for p in cast["personaggi"] if not p["voce_propria"]]
    print(f"{len(cast['personaggi'])} personaggi che parlano: "
          f"{len(principali)} con voce propria, {len(comparse)} al narratore\n")
    for p in sorted(cast["personaggi"], key=lambda x: -x["battute"]):
        segno = "*" if p["voce_propria"] else " "
        tipo = "noto" if p["noto"] else "nuovo"
        nome = p["nome"] + (f" ({p['nome_in_chiaro']})" if p.get("nome_in_chiaro") else " [mai nominato]")
        print(f" {segno} {nome:32} {p['battute']:>3} battute  {tipo}")
        print(f"     {p['descrizione'][:96]}")
        if p.get("come_riconoscerlo"):
            print(f"     si riconosce da: {p['come_riconoscerlo'][:80]}")
    if cast.get("note"):
        print(f"\nnote del modello:\n  {cast['note']}")
    segno = " (da cache)" if misura["da_cache"] else ""
    print(f"\n{len(misura['pagine'])} pagine, {misura['token_ingresso']} token in / "
          f"{misura['token_uscita']} out, ${misura['costo_usd']:.4f}{segno}")


def main():
    ap = argparse.ArgumentParser(
        description="Propone il cast di un fumetto guardandone le prime pagine.")
    ap.add_argument("pagine", nargs="+", help="immagini delle pagine, in ordine")
    ap.add_argument("--modello", default="claude-opus-5", choices=sorted(E.PREZZI))
    ap.add_argument("--sforzo", default="high",
                    choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--massimo", type=int, default=6,
                    help="quanti personaggi al massimo hanno voce propria, narratore escluso")
    ap.add_argument("--voices", help="scrivi qui un voices.json di partenza")
    ap.add_argument("--modello-voices", default=str(POC / "voices.json"),
                    help="da quale voices.json ereditare pulizia, canali e pause")
    ap.add_argument("--rifai", action="store_true", help="ignora la cache su disco")
    args = ap.parse_args()

    if len(args.pagine) > 20:
        sys.exit(f"{len(args.pagine)} pagine: oltre le 20 immagini per richiesta scatta un limite "
                 f"piu' stretto sulle dimensioni. Dagliene meno - per il cast bastano le prime.")
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        sys.exit("Manca ANTHROPIC_API_KEY nell'ambiente.")

    import anthropic
    cast, misura = proponi(anthropic.Anthropic(), args.pagine, args.modello, args.sforzo,
                           args.massimo, args.rifai)
    cast = assegna_voci(cast, args.massimo)
    stampa(cast, misura)
    if args.voices:
        scrivi_voices(cast, args.modello_voices, args.voices)
        print(f"\nvoices.json di partenza in {args.voices}"
              f"\n  le descrizioni servono all'estrazione: rileggile."
              f"\n  i valori di voce non sono tarati: vanno regolati a orecchio.")


if __name__ == "__main__":
    main()
