#!/usr/bin/env python3
"""Estrae il copione di una pagina di fumetto guardandola, e misura quanto e' costato.

Fase 2 del piano (poc/PIANO-estrazione.md): la linea di base. Un passo solo, la pagina intera,
il modello restituisce direttamente ordine di lettura, parlante, tipo e testo. Serve a due cose:
avere un primo punteggio da poc/valuta_estrazione.py, e soprattutto sapere quanto pesa davvero il
RAGIONAMENTO, che e' l'unica cifra del piano che puo' cambiare l'ordine di grandezza del costo.

    poc/.venv-estrazione/bin/python poc/estrai_copione.py pages/render/p41.png
    poc/.venv-estrazione/bin/python poc/estrai_copione.py pages/render/p4*.png --etichetta prova

Poi:
    python3 poc/valuta_estrazione.py poc/estrazione/base

Serve una credenziale: ANTHROPIC_API_KEY nell'ambiente.

Cosa NON fa, di proposito:
 - non produce 'text_tts'. E' una trasformazione deterministica a valle (dizionario di pronuncia,
   fase 6), non un compito del modello, e chiederla qui sporcherebbe la misura del ragionamento.
   Con --con-tts la si chiede lo stesso, per vedere quanto costa.
 - non produce i riquadri dei balloon. Con --riquadri li chiede: e' la precondizione della fase 3
   (ritagliare per leggere il testo a risoluzione nativa) e una passata sola basta a sapere se le
   coordinate sono abbastanza buone per ritagliarci sopra.

Il cast dei personaggi viene da poc/voices.json ed entra nello schema come elenco chiuso: il
modello non puo' inventare un nome. Per una storia nuova il cast non si conosce in anticipo -
e' un problema aperto, non risolto qui (vedi il piano, fase 8).
"""

import argparse
import base64
import hashlib
import io
import json
import math
import os
import sys
import time
from pathlib import Path

try:
    import anthropic
    from PIL import Image
except ImportError as e:
    sys.exit(f"Manca una dipendenza ({e.name}). Usa poc/.venv-estrazione/bin/python, "
             f"oppure ricrea l'ambiente con poc/setup.sh --venv")

POC = Path(__file__).resolve().parent
ROOT = POC.parent

# Prezzi per milione di token, Claude API, verificati 2026-06. Servono solo a stampare il conto.
PREZZI = {
    "claude-opus-5":   (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

# Quanto grande vede l'immagine ciascuna fascia di modelli, e quanti token di visione costa.
# Un token ogni riquadro di 28x28 px; oltre i limiti l'immagine viene ridotta PRIMA di essere
# guardata, quindi mandarla piu' grande non compra niente e costa solo banda.
FASCE = {
    "alta":     (2576, 4784),   # Claude 4.7 e successivi: opus-5, sonnet-5, opus-4-8
    "standard": (1568, 1568),   # tutti gli altri, haiku-4-5 compreso
}
FASCIA_DI = {"claude-opus-5": "alta", "claude-opus-4-8": "alta",
             "claude-sonnet-5": "alta", "claude-haiku-4-5": "standard"}

TIPI = ["title", "credits", "caption", "dialogue", "sfx"]


# ---------------------------------------------------------------- immagine

def token_visione(larghezza, altezza):
    return math.ceil(larghezza / 28) * math.ceil(altezza / 28)


def prepara(percorso, fascia, formato, qualita):
    """Riduce la pagina a quello che il modello vedra' comunque, e la codifica.

    Ridurla qui invece di lasciarlo fare al server serve a tre cose: sapere in anticipo quanti
    token di visione costera', mandare qualche megabyte invece di quattro, e - se un giorno
    serviranno le coordinate - averle gia' nel sistema di riferimento che il modello usa.
    """
    lato_max, token_max = FASCE[fascia]
    img = Image.open(percorso)
    img = img.convert("RGB")
    w0, h0 = img.size

    scala = min(1.0, lato_max / max(w0, h0))
    w, h = max(1, round(w0 * scala)), max(1, round(h0 * scala))
    if token_visione(w, h) > token_max:
        # stessa regola del server: si scende alla dimensione piu' grande che ci sta nel tetto
        s = math.sqrt(token_max * 784 / (w * h))
        w, h = max(1, int(w * s)), max(1, int(h * s))
    if (w, h) != (w0, h0):
        img = img.resize((w, h), Image.LANCZOS)

    buf = io.BytesIO()
    if formato == "jpeg":
        img.save(buf, "JPEG", quality=qualita, subsampling=0, optimize=True)
        media = "image/jpeg"
    else:
        img.save(buf, "PNG", optimize=True)
        media = "image/png"
    dati = buf.getvalue()
    if len(dati) > 9_500_000:
        sys.exit(f"{percorso}: {len(dati)/1e6:.1f} MB dopo la codifica, oltre il limite di 10 MB "
                 f"per immagine. Usa --formato jpeg.")
    return dati, media, (w0, h0), (w, h), token_visione(w, h)


# ---------------------------------------------------------------- prompt e schema

def cast_da_voices(percorso=None):
    d = json.loads(Path(percorso or POC / "voices.json").read_text(encoding="utf-8"))
    return sorted(d["speakers"].keys())


def scheda_cast(percorso=None):
    """Chi e' chi, preso dalle descrizioni gia' scritte in voices.json.

    Erano nate come appunti di regia per la voce, ma dicono anche chi e' il personaggio ('turista
    anziano e gioviale, il portavoce del gruppo', 'turista senza fiato', 'turista palestrato') -
    ed e' l'unica cosa che permette di distinguere fra loro tre turisti che il modello non ha mai
    visto. Il primo giro sulle 12 pagine passava solo i NOMI, e l'attribuzione stava al 66%.
    Si passano intere: la parte sui decibel il modello la ignora, e non costa niente perche' sta
    nel blocco fisso che va in cache.
    """
    d = json.loads(Path(percorso or POC / "voices.json").read_text(encoding="utf-8"))["speakers"]
    return {k: v.get("descrizione", "") for k, v in sorted(d.items())}


def schema(cast, con_tts, riquadri):
    battuta = {
        "seq": {"type": "integer",
                "description": "progressivo dell'ordine di lettura nella pagina, da 1"},
        "panel": {"type": "integer",
                  "description": "numero della vignetta, da 1; 0 per titolo e crediti"},
        "type": {"type": "string", "enum": TIPI},
        "speaker": {"type": "string", "enum": cast},
        "text": {"type": "string", "description": "il testo come stampato"},
        "radio": {"type": "boolean",
                  "description": "vero solo se la battuta esce da una ricetrasmittente"},
        "channel": {"type": "string", "enum": ["", "sussurro"],
                    "description": "'sussurro' se il balloon e' tratteggiato, se no vuoto"},
    }
    if con_tts:
        battuta["text_tts"] = {"type": "string",
                               "description": "il testo come va letto ad alta voce in italiano"}
    if riquadri:
        # Un oggetto e non un array di 4: lo schema vincolato non accetta 'minItems' maggiore
        # di 1, e cosi' non c'e' nemmeno il rischio di scambiare l'ordine dei quattro numeri.
        battuta["bbox"] = {
            "type": "object",
            "properties": {k: {"type": "integer"} for k in ("x", "y", "w", "h")},
            "required": ["x", "y", "w", "h"], "additionalProperties": False,
            "description": "riquadro del balloon in pixel: angolo in alto a sinistra e dimensioni"}
    return {
        "type": "object",
        "properties": {
            "page": {"type": "integer"},
            "entries": {
                "type": "array",
                "items": {"type": "object", "properties": battuta,
                          "required": list(battuta), "additionalProperties": False},
            },
        },
        "required": ["page", "entries"],
        "additionalProperties": False,
    }


def istruzioni(cast, scheda, riquadri, larghezza, altezza):
    """Le regole. Restano identiche pagina per pagina: e' la parte che si puo' mettere in cache.

    Dicono quasi solo cose che il PoC ha gia' deciso all'ascolto (vedi TECNOLOGIE.md): le
    onomatopee si leggono, i versi degli animali li legge il narratore, il filtro radio lo decide
    la battuta e non il personaggio.
    """
    return f"""Sei un lettore di fumetti che prepara il copione per una lettura ad alta voce.
Guardi UNA pagina e restituisci ogni testo pronunciabile che ci trovi, nell'ordine in cui va
letto.

ORDINE DI LETTURA. E' la cosa piu' importante e quella che si sbaglia piu' facilmente.
Le vignette si leggono all'occidentale: da sinistra a destra, dall'alto in basso; una striscia
per volta. Dentro la vignetta vale lo stesso, ma decide il senso del dialogo: chi fa la domanda
viene prima di chi risponde, anche se il suo balloon e' un filo piu' a destra. La coda del
balloon dice a chi appartiene; se due balloon sono uniti da un ponticello sono la stessa persona
che continua a parlare, e vanno di seguito.
Numera 'seq' da 1 senza salti, seguendo quell'ordine.

COSA RACCOGLIERE. Tutto cio' che una voce deve pronunciare:
- 'dialogue': i balloon dei personaggi.
- 'caption': le didascalie, di solito rettangolari e colorate, voce fuori campo.
- 'sfx': le ONOMATOPEE, anche quando sono disegnate dentro la vignetta e non stanno in un
  balloon. Vanno lette, non saltate: sono parte del racconto. Anche i grugniti e i versi
  ("HRMPF!", "GULP!") sono sfx.
- 'title' e 'credits': solo nella prima pagina di una storia; 'panel' vale 0.
  Anche la parola di chiusura in fondo all'ultima pagina ("FINE") va raccolta, come 'caption'
  del narratore: chiude la lettura.
  I CREDITI (soggetto, sceneggiatura, disegni) sul foglio stanno quasi sempre in fondo, sotto
  l'ultima striscia, ma vanno letti SUBITO DOPO IL TITOLO, come i titoli di testa di un film:
  quindi seq 2. E' una convenzione di questa lettura ad alta voce, non un errore di lettura:
  l'ascoltatore vuole sapere di chi e' la storia prima che cominci, non dopo che e' finita.
Non raccogliere: testo che fa parte del disegno e nessuno pronuncia (insegne, cartelli, marchi,
scritte sui mezzi), a meno che un personaggio non lo stia leggendo ad alta voce.

CHI PARLA. Scegli sempre uno di questi nomi, e nessun altro.

{chr(10).join(f"  {n}: {d}" for n, d in scheda.items())}

Quelle descrizioni nascono come appunti sulla voce, ma dicono anche CHI E' il personaggio: usale
per distinguerli. Tre turisti che si somigliano si separano da quello che fanno e dicono - chi
conta i passi e scherza, chi ansima e chiede ossigeno, chi esibisce i muscoli - non dal disegno.
Guarda chi e' inquadrato nella vignetta e dove punta la coda del balloon, poi controlla che la
battuta sia coerente con il personaggio che hai scelto.
- 'narratore' e' la voce delle didascalie, del titolo e dei crediti. E' anche la voce dei VERSI
  DEGLI ANIMALI e di ogni onomatopea che non venga da un personaggio del cast.
- per un 'sfx' emesso da un personaggio (uno sbuffo, un colpo di tosse) il parlante e' quel
  personaggio.
- il testo aiuta: se una battuta chiama qualcuno per nome, non e' quel qualcuno a dirla.

DUE CASI PARTICOLARI, che cambiano il suono:
- 'radio': vero SOLO quando la battuta arriva da una ricetrasmittente (balloon dal contorno
  spezzato o a zig-zag, spesso con un fulmine). E' una proprieta' della battuta, non del
  personaggio: lo stesso personaggio parla dalla radio in una scena e di persona in un'altra.
- 'channel' = 'sussurro' quando il balloon e' TRATTEGGIATO: qualcosa detto a mezza voce o
  fra se' e se'. Se no lascia 'channel' vuoto.

IL TESTO. Riportalo come e' stampato, comprese le maiuscole. Il lettering dei fumetti rende gli
accenti con un apostrofo (CAFFE', PIU'): lascialo com'e', non correggerlo. Mantieni i puntini di
sospensione e la punteggiatura. Non riassumere e non riscrivere nulla.
{"" if not riquadri else f'''
I RIQUADRI. 'bbox' e' x, y, w, h in pixel sull'immagine che stai guardando, che
e' {larghezza}x{altezza}. Deve contenere tutto il testo della battuta. Meglio un filo largo che
stretto.'''}
Se una pagina non contiene nessun testo pronunciabile, restituisci 'entries' vuoto."""


# ---------------------------------------------------------------- chiamata

def ripulisci(dato, pagina, con_tts, riquadri):
    """Porta la risposta nella forma del copione d'oro: via i campi vuoti che l'oro non scrive."""
    entries = []
    for e in dato.get("entries", []):
        b = {"seq": e.get("seq"), "panel": e.get("panel"), "type": e.get("type"),
             "speaker": e.get("speaker"), "text": e.get("text", "")}
        if con_tts and e.get("text_tts"):
            b["text_tts"] = e["text_tts"]
        if e.get("radio"):
            b["radio"] = True
        if e.get("channel"):
            b["channel"] = e["channel"]
        if riquadri and e.get("bbox"):
            b["bbox"] = e["bbox"]
        entries.append(b)
    entries.sort(key=lambda b: (b["seq"] if isinstance(b["seq"], int) else 0))
    return {"page": pagina, "entries": entries}


_SPESA_MESSAGGIO = {}


def conta_token(client, modello, testo):
    """Quanti token e' davvero il JSON restituito, al netto dell'involucro del messaggio.

    'count_tokens' conta un messaggio intero, che porta con se' una ventina di token di
    intestazione: si misura una volta su un messaggio minimo e si sottrae. Non si paga.
    """
    if modello not in _SPESA_MESSAGGIO:
        vuoto = client.messages.count_tokens(
            model=modello, messages=[{"role": "user", "content": "."}]).input_tokens
        uno = client.messages.count_tokens(
            model=modello, messages=[{"role": "user", "content": ".."}]).input_tokens
        # 'vuoto' e' involucro + il token del punto; la differenza fra i due da' il costo di un
        # carattere in piu', che qui non serve: basta l'involucro, cioe' vuoto meno un token.
        _SPESA_MESSAGGIO[modello] = max(0, vuoto - (uno - vuoto))
    intero = client.messages.count_tokens(
        model=modello, messages=[{"role": "user", "content": testo}]).input_tokens
    return max(1, intero - _SPESA_MESSAGGIO[modello])


def impronta(*pezzi):
    h = hashlib.sha256()
    for p in pezzi:
        h.update(p if isinstance(p, bytes) else str(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def estrai(client, args, percorso, cast):
    pagina = int(Path(percorso).stem.lstrip("p"))
    fascia = FASCIA_DI.get(args.modello, "alta")
    dati, media, originale, vista, tok_vis = prepara(
        percorso, fascia, args.formato, args.qualita)

    sch = schema(cast, args.con_tts, args.riquadri)
    testo_regole = istruzioni(cast, scheda_cast(args.voices), args.riquadri, *vista)

    chiave = impronta(dati, testo_regole, json.dumps(sch, sort_keys=True),
                      args.modello, args.sforzo, args.pensiero, args.max_token)
    cache = POC / "estrazione" / "cache" / f"{chiave}.json"
    if cache.exists() and not args.rifai:
        salvato = json.loads(cache.read_text(encoding="utf-8"))
        salvato["misura"]["da_cache"] = True
        return pagina, salvato["copione"], salvato["misura"]

    corpo = {
        "model": args.modello,
        "max_tokens": args.max_token,
        "system": [{"type": "text", "text": testo_regole,
                    "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media,
                                         "data": base64.b64encode(dati).decode()}},
            {"type": "text", "text": f"Questa e' la pagina {pagina}. Preparane il copione."},
        ]}],
        "output_config": {
            "effort": args.sforzo,
            "format": {"type": "json_schema", "schema": sch},
        },
    }
    # Su Claude Opus 5 il pensiero e' attivo di suo. Chiederlo 'summarized' non cambia il costo
    # (si paga comunque) ma lo rende visibile, che e' tutto il punto della fase 2.
    corpo["thinking"] = ({"type": "disabled"} if args.pensiero == "no"
                         else {"type": "adaptive", "display": "summarized"})

    inizio = time.monotonic()
    risposta = client.messages.create(**corpo)
    secondi = time.monotonic() - inizio

    if risposta.stop_reason == "refusal":
        sys.exit(f"p{pagina}: la richiesta e' stata rifiutata "
                 f"({getattr(risposta.stop_details, 'category', '?')}).")
    if risposta.stop_reason == "max_tokens":
        sys.exit(f"p{pagina}: risposta troncata a {args.max_token} token. "
                 f"Rilancia con --max-token piu' alto.")

    testo = next((b.text for b in risposta.content if b.type == "text"), None)
    if testo is None:
        sys.exit(f"p{pagina}: nessun blocco di testo nella risposta.")
    pensiero = "".join(b.thinking for b in risposta.content
                       if b.type == "thinking" and getattr(b, "thinking", None))

    copione = ripulisci(json.loads(testo), pagina, args.con_tts, args.riquadri)

    u = risposta.usage
    pin, pout = PREZZI.get(args.modello, (0.0, 0.0))
    ingresso = u.input_tokens + (u.cache_read_input_tokens or 0) + \
        (u.cache_creation_input_tokens or 0)
    # Il JSON finale e' l'unica parte dell'uscita che ci serve; il resto e' ragionamento.
    # Va CONTATO, non stimato: una prima versione tirava a indovinare con 3,5 caratteri per
    # token e sbagliava di quasi il doppio (391 invece di 705), tanto da attribuire 354 token
    # di ragionamento a un giro in cui il ragionamento era spento.
    token_json = conta_token(client, args.modello, testo)
    misura = {
        "pagina": pagina, "modello": args.modello, "sforzo": args.sforzo,
        "pensiero": args.pensiero,
        "immagine_originale": f"{originale[0]}x{originale[1]}",
        "immagine_vista": f"{vista[0]}x{vista[1]}",
        "immagine_kb": round(len(dati) / 1024),
        "token_visione_stimati": tok_vis,
        "token_ingresso": ingresso,
        "token_ingresso_nuovi": u.input_tokens,
        "token_cache_scritti": u.cache_creation_input_tokens or 0,
        "token_cache_letti": u.cache_read_input_tokens or 0,
        "token_uscita": u.output_tokens,
        "token_uscita_json": token_json,
        "token_ragionamento": max(0, u.output_tokens - token_json),
        "caratteri_ragionamento": len(pensiero),
        "battute": len(copione["entries"]),
        "secondi": round(secondi, 1),
        "costo_usd": round(
            (u.input_tokens * pin + (u.cache_creation_input_tokens or 0) * pin * 1.25
             + (u.cache_read_input_tokens or 0) * pin * 0.1
             + u.output_tokens * pout) / 1e6, 4),
        "da_cache": False,
    }
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"copione": copione, "misura": misura, "pensiero": pensiero},
                                ensure_ascii=False, indent=2), encoding="utf-8")
    return pagina, copione, misura


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="Estrae il copione di una o piu' pagine di fumetto guardandole.")
    ap.add_argument("pagine", nargs="+", help="immagini pNN.png")
    ap.add_argument("--modello", default="claude-opus-5", choices=sorted(PREZZI))
    ap.add_argument("--sforzo", default="high",
                    choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--pensiero", default="si", choices=["si", "no"],
                    help="'no' spegne il ragionamento: serve a misurare quanto costa")
    ap.add_argument("--etichetta", default="base",
                    help="sottocartella di poc/estrazione/ dove finisce il copione")
    ap.add_argument("--con-tts", action="store_true", help="chiedi anche 'text_tts'")
    ap.add_argument("--riquadri", action="store_true", help="chiedi anche i riquadri dei balloon")
    ap.add_argument("--formato", default="png", choices=["png", "jpeg"])
    ap.add_argument("--qualita", type=int, default=92, help="qualita' JPEG, se --formato jpeg")
    ap.add_argument("--max-token", type=int, default=16000)
    ap.add_argument("--voices", help="un voices.json diverso da poc/voices.json: il cast e le "
                                     "descrizioni vengono da li'")
    ap.add_argument("--rifai", action="store_true", help="ignora la cache su disco")
    args = ap.parse_args()

    if args.pensiero == "no" and args.sforzo in ("xhigh", "max"):
        sys.exit("--pensiero no non e' accettato con sforzo xhigh o max (errore 400 dal server).")
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        sys.exit("Manca ANTHROPIC_API_KEY nell'ambiente.")

    cast = cast_da_voices(args.voices)
    uscita = POC / "estrazione" / args.etichetta
    uscita.mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic()

    misure, totale, secondi = [], 0.0, 0.0
    for percorso in args.pagine:
        pagina, copione, m = estrai(client, args, percorso, cast)
        (uscita / f"p{pagina}.json").write_text(
            json.dumps(copione, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        misure.append(m)
        if not m["da_cache"]:
            totale += m["costo_usd"]
            secondi += m["secondi"]
        segno = " (da cache)" if m["da_cache"] else ""
        print(f"p{pagina}: {m['battute']:>3} battute, "
              f"{m['token_ingresso']:>6} token in / {m['token_uscita']:>6} out "
              f"(di cui {m['token_ragionamento']} di ragionamento), "
              f"{m['secondi']}s, ${m['costo_usd']:.4f}{segno}")

    (uscita / "misura.json").write_text(
        json.dumps(misure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    n = len(misure)
    print(f"\n{n} pagin{'a' if n == 1 else 'e'} in {uscita.relative_to(ROOT)}")
    if totale:
        print(f"speso ${totale:.4f} in {secondi:.0f}s"
              f"   ->  una storia da 12 pagine: ${totale / n * 12:.2f}"
              f"   un albo da 50: ${totale / n * 50:.2f}")
        rag = sum(m["token_ragionamento"] for m in misure if not m["da_cache"])
        usc = sum(m["token_uscita"] for m in misure if not m["da_cache"])
        if usc:
            print(f"ragionamento: ~{100 * rag / usc:.0f}% dei token in uscita")
    print(f"\nora il punteggio:  python3 poc/valuta_estrazione.py "
          f"{uscita.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
