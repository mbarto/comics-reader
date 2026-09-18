#!/usr/bin/env python3
"""Dal testo stampato sulla pagina al testo da dare al sintetizzatore.

Fase 6 del piano (poc/PIANO-estrazione.md). Il fumetto e' scritto TUTTO IN MAIUSCOLO, con
l'apostrofo al posto dell'accento (CAFFE'), i numeri in cifre (13.123 PASSI) e le onomatopee in
inglese (GROWL). Un sintetizzatore italiano su quella roba fa disastri: compita le maiuscole,
legge "caffe" senza accento, dice "tredicimilacentoventitre punto" e pronuncia "grovl".

Il PoC risolveva scrivendo a mano un secondo campo, 'text_tts', per tutte e 131 le battute. Ma
questa e' l'unica parte del lavoro che **non richiede di guardare la pagina**: e' una funzione del
testo, quindi si scrive una volta e vale per tutte le storie. Il modello non c'entra, e infatti
poc/estrai_copione.py non lo chiede piu'.

    poc/pronuncia.py COPIONE [--voices voices.json] [--scrivi]
    poc/pronuncia.py --verifica                    # il metro: 131 battute d'oro

COPIONE e' una cartella di pNN.json o un singolo file. Senza --scrivi non tocca niente e mostra
soltanto cosa farebbe.

COSA FA, in ordine (l'ordine conta: i numeri vanno convertiti prima che il punto di '13.123'
venga scambiato per una fine di frase):

  1. normalizza apostrofi e virgolette tipografiche, toglie le virgolette che avvolgono tutta la
     battuta e i puntini di sospensione a inizio balloon (sono la coda della battuta precedente:
     la frase continua, quindi non va nemmeno rimaiuscolata)
  2. i nomi propri della storia si mettono da parte interi, cercati per come sono STAMPATI, e si
     rimettono alla fine: cosi' nessuna regola li tocca, e "Parco Nazionale" resta maiuscolo dove
     "il parco e' pieno di gente" no
  3. le sigle diventano parole (3D -> tre di), e poi i numeri (13.123 -> tredicimilacentoventitré)
  4. ogni parola passa dal dizionario (poc/pronuncia.json) e poi dalle regole
  5. l'apostrofo finale diventa accento, tranne nei troncamenti: CAFFE' -> caffè ma PO' -> po'
  6. gli imperativi con pronome attaccato riprendono l'accento: DATEMI -> dàtemi
  7. si rimette la maiuscola a inizio di ogni frase - ma non dopo i puntini, dove la frase non e'
     finita, sta sospesa
  8. le onomatopee ripetute si separano: SLAP SLAP -> Slap! Slap!

QUELLO CHE NON FA, e sono decisioni, non dimenticanze:

  - non abbassa le parole che sul copione non sono gia' tutte maiuscole: i crediti ("Disegni di
    Luca Usai") arrivano dall'estrattore in maiuscolo e minuscolo, e sono gia' giusti cosi'. Dal
    dizionario pero' ci passano lo stesso, perche' l'estrattore ogni tanto normalizza da solo il
    MAIUSCOLO della pagina ("UACK!" -> "Uack!") e quella resta un'onomatopea da rendere.
  - non prova a indovinare l'accento delle parole italiane che non conosce. Sbagliarne una che
    andava bene fa piu' danno che lasciarne una storta: il TTS l'accento piano lo azzecca da solo
    nella stragrande maggioranza dei casi, ed e' l'eccezione che sta nel dizionario.
  - non inventa onomatopee. Una che non e' nel dizionario esce com'e' scritta, e la si sente
    subito al primo ascolto: e' li' che si aggiunge la riga al file, una volta per tutte.

IL METRO. Con --verifica riconverte le 131 battute di poc/script/oro/ e le confronta con il
'text_tts' scritto a mano nel PoC, che e' l'unica definizione di "pronuncia giusta" che esista in
questo progetto. Non e' un metro perfetto - alcune di quelle 131 sono scelte di gusto di chi le ha
scritte, non regole - ma e' un numero, e senza un numero ogni variante si giudica a impressione.
"""

import argparse
import json
import re
import sys
from pathlib import Path

POC = Path(__file__).resolve().parent
DIZIONARIO_DEFAULT = POC / "pronuncia.json"
ORO_DEFAULT = POC / "script" / "oro"

# Vocale + apostrofo finale -> vocale accentata. La E non c'e': e' l'unica ambigua (e' / é) e la
# decide 'acuto_suffissi' nel dizionario.
GRAVE = {"a": "à", "i": "ì", "o": "ò", "u": "ù", "e": "è"}
ACUTO = {"e": "é"}

UNITA = ["zero", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove",
         "dieci", "undici", "dodici", "tredici", "quattordici", "quindici", "sedici",
         "diciassette", "diciotto", "diciannove"]
DECINE = ["", "", "venti", "trenta", "quaranta", "cinquanta", "sessanta", "settanta", "ottanta",
          "novanta"]

# Il segnaposto che tiene il posto di un nome proprio mentre il resto della frase viene
# trasformato. Fatto di sole lettere, in maiuscolo e minuscolo: cosi' i numeri non lo toccano, la
# conversione delle maiuscole lo lascia stare (non e' tutto maiuscolo) e a inizio frase si prende
# lui la maiuscola invece di darla alla parola dopo.
SEGNAPOSTO = "Nomeproprio"
LETTERE = "abcdefghijklmnopqrstuvwxyz"


def lettere(i: int) -> str:
    return "".join(LETTERE[int(c)] for c in str(i))


# Una parola: lettere, con eventuali apostrofi dentro (QUANT'E') o in coda (CAFFE').
PAROLA = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*'?", re.UNICODE)
# Un numero, anche col punto delle migliaia all'italiana: 13.123. Deve stare per conto suo: la
# cifra attaccata a una lettera fa parte di una sigla ("3D"), e quella la prende un'altra regola.
NUMERO = re.compile(r"(?<![\w.])(?:\d{1,3}(?:\.\d{3})+|\d+)(?!\w)")


def numero_in_lettere(n: int) -> str:
    """13123 -> 'tredicimilacentoventitré'. In italiano si scrive tutto attaccato."""
    if n < 20:
        return UNITA[n]
    if n < 100:
        d, u = divmod(n, 10)
        testa = DECINE[d]
        # venti + uno = ventuno, non ventiuno: davanti a vocale la decina perde la sua
        if u in (1, 8):
            testa = testa[:-1]
        return testa + (coda(u) if u else "")
    if n < 1000:
        c, r = divmod(n, 100)
        testa = "cento" if c == 1 else UNITA[c] + "cento"
        return testa + (numero_in_lettere(r) if r else "")
    if n < 1_000_000:
        k, r = divmod(n, 1000)
        testa = "mille" if k == 1 else numero_in_lettere(k) + "mila"
        return testa + (numero_in_lettere(r) if r else "")
    if n < 1_000_000_000:
        m, r = divmod(n, 1_000_000)
        testa = "un milione" if m == 1 else numero_in_lettere(m) + " milioni"
        return testa + (" " + numero_in_lettere(r) if r else "")
    m, r = divmod(n, 1_000_000_000)
    testa = "un miliardo" if m == 1 else numero_in_lettere(m) + " miliardi"
    return testa + (" " + numero_in_lettere(r) if r else "")


def coda(u: int) -> str:
    """L'ultima cifra di un numero composto. Il 3 finale prende l'accento: ventitré."""
    return "tré" if u == 3 else UNITA[u]


class Pronuncia:
    """Il convertitore. Tiene insieme il dizionario condiviso e i nomi propri della storia."""

    def __init__(self, dizionario: dict, nomi: list[tuple[str, str]] | None = None):
        self.troncamenti = set(dizionario.get("troncamenti", []))
        self.acuto_suffissi = tuple(dizionario.get("acuto_suffissi", []))
        self.acuto_parole = set(dizionario.get("acuto_parole", []))

        # I tre elenchi del dizionario fanno mestieri diversi ma si consultano allo stesso modo.
        self.parole = {}
        for sezione in ("forestierismi", "onomatopee", "accenti"):
            for k, v in dizionario.get(sezione, {}).items():
                self.parole[k.upper()] = v

        # Le sigle non sono parole: hanno dentro cifre e punti, e vanno sostituite intere prima
        # che le altre regole ci mettano le mani.
        self.sigle = sorted(dizionario.get("sigle", {}).items(), key=lambda kv: -len(kv[0]))

        # I nomi propri si cercano su come sono STAMPATI, prima di ogni altra cosa, e il pezzo di
        # testo che occupano viene messo da parte fino alla fine: un nome non passa dal dizionario
        # ne' dalle regole, e' gia' scritto come va letto. I piu' lunghi per primi, se no "Picco"
        # verrebbe preso da solo e "Picco Fiocco" non si formerebbe mai.
        self.nomi = sorted((nomi or []), key=lambda n: -len(n[0]))

    # ---- la conversione, pezzo per pezzo ---------------------------------------------------

    def converti(self, testo: str, tipo: str = "dialogue") -> str:
        testo = self._normalizza(testo)
        testo, continua = self._scorcia(testo, tipo)
        testo, messi_via = self._metti_via_i_nomi(testo)
        testo = self._sigle(testo)
        testo = NUMERO.sub(lambda m: numero_in_lettere(int(m.group().replace(".", ""))), testo)
        testo = PAROLA.sub(lambda m: self._parola(m.group()), testo)
        if tipo == "sfx":
            testo = self._onomatopea(testo)
        testo = self._maiuscole(testo, continua)
        testo = self._rimetti_i_nomi(testo, messi_via)
        if tipo in ("title", "caption", "credits") and testo and testo[-1] not in ".!?…":
            # Una didascalia che finisce senza punteggiatura ("FINE") il TTS la legge sospesa,
            # come se la frase dovesse continuare.
            testo += "."
        return testo

    def _normalizza(self, t: str) -> str:
        t = (t.replace("’", "'").replace("‘", "'")
              .replace("“", '"').replace("”", '"')
              .replace("…", "..."))
        t = re.sub(r"\s+", " ", t).strip()
        # Nel fumetto capita lo spazio prima del punto interrogativo ("MA CHI... ?"), che e' una
        # spaziatura del lettering. Letto, diventa una pausa che spezza la domanda in due.
        t = re.sub(r"\s+([?!,;:])", r"\1", t)
        return t

    def _scorcia(self, t: str, tipo: str) -> tuple[str, bool]:
        """Toglie le virgolette esterne e i puntini iniziali. Torna anche se la frase continua."""
        if len(t) > 1 and t[0] == '"' and t[-1] == '"' and '"' not in t[1:-1]:
            t = t[1:-1].strip()
        continua = False
        if t.startswith("..."):
            # Un balloon che comincia coi puntini e' la seconda meta' di una frase cominciata nel
            # balloon prima. Letti, quei puntini diventano una pausa in piu' all'attacco: la pausa
            # fra un balloon e l'altro ce l'ha gia' il montaggio (pauses_ms in voices.json).
            t = t[3:].strip()
            continua = True
        # Il trattino di un titolo ("PAPERINO PARK RANGER - UACK!") o dei crediti ("Soggetto di X
        # - Disegni di Y") tiene insieme due cose che vanno lette staccate: di fila suonano come
        # una frase sola. Nel dialogo invece un trattino e' un inciso, e li' non si tocca.
        if tipo in ("title", "credits"):
            t = re.sub(r"\s*[—–-]\s+", ". ", t)
        return t, continua

    def _sigle(self, t: str) -> str:
        for scritta, letta in self.sigle:
            t = re.sub(r"(?<!\w)" + re.escape(scritta) + r"(?!\w)", letta, t)
        return t

    def _parola(self, w: str) -> str:
        # Una parola che sul copione non e' tutta maiuscola e' gia' scritta come va letta: i nomi
        # dei disegnatori nei crediti, e qualsiasi correzione fatta a mano. Non si abbassa e non
        # le si tocca l'apostrofo - ma nel dizionario ci passa lo stesso, perche' l'estrattore
        # ogni tanto normalizza da solo il MAIUSCOLO della pagina ("UACK!" -> "Uack!") e quella
        # resta un'onomatopea da rendere.
        maiuscola = w == w.upper()
        pezzi = w.split("'")
        finale = maiuscola and pezzi[-1] == ""      # l'apostrofo era in coda: CAFFE'
        if finale:
            pezzi = pezzi[:-1]
        fuori = [self._pezzo(p, maiuscola) for p in pezzi]
        if finale:
            fuori[-1] = self._accento_finale(w, fuori[-1])
        return "'".join(fuori)

    def _pezzo(self, p: str, maiuscola: bool) -> str:
        """Un frammento di parola fra due apostrofi: DELL'OSSIGENO -> dell' + ossìgeno."""
        if p.upper() in self.parole:
            return self.parole[p.upper()]
        return self._enclitico(p.lower()) if maiuscola else p

    def _accento_finale(self, intera: str, p: str) -> str:
        """L'apostrofo finale del fumetto e' quasi sempre un accento: CITTA' -> città."""
        su = intera.upper()
        if su in self.troncamenti:
            return p + "'"
        if not p or p[-1] not in GRAVE:
            return p + "'"
        tavola = ACUTO if (su.endswith(self.acuto_suffissi) or su in self.acuto_parole) else GRAVE
        return p[:-1] + tavola.get(p[-1], GRAVE[p[-1]])

    def _enclitico(self, p: str) -> str:
        """DATEMI -> dàtemi. Imperativo di seconda plurale piu' un pronome attaccato.

        Attaccando il pronome la parola diventa sdrucciola e il TTS sposta l'accento in avanti.
        La regola vale solo se davanti al '-te' c'e' una vocale, che e' la sillaba accentata
        dell'imperativo (chiamà-te, seguì-te): serve a non prendere per imperativi parole come
        'sistemi', dove la 'e' non e' un suffisso. I pronomi possono essere due: DATEMELO.

        Gli imperativi di seconda singolare (perdonami, spostati) questa regola non li prende, e
        non e' una dimenticanza: senza il '-te' di mezzo la stessa regola accenterebbe 'salami' e
        'richiami'. Quelli stanno nel dizionario, uno per uno.
        """
        m = re.fullmatch(r"(.+[aeiou])te((?:mi|ti|ci|vi|si|lo|la|li|le|ne|me|ce|ve|glie){1,2})", p)
        if not m:
            return p
        testa = m.group(1)
        return testa[:-1] + GRAVE[testa[-1]] + p[len(testa):]

    def _onomatopea(self, t: str) -> str:
        """SLAP SLAP -> Slap! Slap!. Solo se non c'e' gia' punteggiatura a dire come leggerla."""
        if re.search(r"[.!?,;:]", t):
            return t
        parole = t.split()
        return " ".join(p + "!" for p in parole) if parole else t

    def _metti_via_i_nomi(self, t: str) -> tuple[str, list[str]]:
        """Sostituisce i nomi propri con un segnaposto, e torna l'elenco di cosa c'era."""
        messi_via = []
        for scritto, letto in self.nomi:
            def segna(_m, letto=letto):
                messi_via.append(letto)
                return SEGNAPOSTO + lettere(len(messi_via) - 1)
            t = re.sub(r"\b" + re.escape(scritto) + r"\b", segna, t, flags=re.IGNORECASE)
        return t, messi_via

    def _rimetti_i_nomi(self, t: str, messi_via: list[str]) -> str:
        for i, letto in enumerate(messi_via):
            t = t.replace(SEGNAPOSTO + lettere(i), letto)
        return t

    def _maiuscole(self, t: str, continua: bool) -> str:
        """Maiuscola a inizio frase. Dopo i puntini no: la frase non e' finita, sta sospesa."""
        fuori = []
        attesa = not continua
        i = 0
        while i < len(t):
            c = t[i]
            if attesa and c.isalpha():
                fuori.append(c.upper())
                attesa = False
            else:
                fuori.append(c)
            if c in "!?":
                attesa = True
            elif c == "." and not t[i:i + 3] == "...":
                attesa = not t[max(0, i - 2):i].endswith("..")
            i += 1
        return "".join(fuori)


# ---- il dizionario dei nomi propri della storia ---------------------------------------------

def nomi_della_storia(voices: Path | None) -> list[tuple[str, str]]:
    """I nomi propri stanno nel voices.json della storia: il cast li ha gia' quasi tutti.

    Le chiavi di 'speakers' sono i personaggi che parlano, ed e' esattamente l'elenco che serve.
    'nomi_propri' aggiunge quelli che non parlano: i luoghi, e i personaggi nominati e basta.
    Torna coppie (come e' stampato, come va letto), che per quasi tutti sono la stessa parola a
    parte la maiuscola.
    """
    if not voices:
        return []
    d = json.loads(voices.read_text(encoding="utf-8"))
    nomi = []
    for chiave in d.get("speakers", {}):
        # 'narratore' non e' un personaggio, e le chiavi col trattino basso sono etichette di
        # ruolo che la ricognizione del cast da' a chi non ha un nome ('venditore_posate').
        if chiave == "narratore" or "_" in chiave:
            continue
        nomi.append((chiave, chiave[:1].upper() + chiave[1:]))
    for voce in d.get("nomi_propri", []):
        if isinstance(voce, str):
            nomi.append((voce, voce))
        else:
            nomi.append((voce["scritto"], voce["letto"]))
    return nomi


def carica(percorso: Path) -> list[Path]:
    if percorso.is_dir():
        return sorted(percorso.glob("p*.json"))
    return [percorso]


# ---- il metro ---------------------------------------------------------------------------

def verifica(pron: Pronuncia, oro: Path, dettagli: bool) -> int:
    uguali = mancate = 0
    sbagliate = []
    for f in carica(oro):
        d = json.loads(f.read_text(encoding="utf-8"))
        for e in d["entries"]:
            atteso = e.get("text_tts")
            if atteso is None:
                continue
            ottenuto = pron.converti(e["text"], e.get("type", "dialogue"))
            if ottenuto == atteso:
                uguali += 1
            else:
                mancate += 1
                sbagliate.append((f.stem, e["seq"], e["text"], atteso, ottenuto))

    tot = uguali + mancate
    if not tot:
        sys.exit("Nessuna battuta con 'text_tts' nel copione d'oro.")
    print(f"battute con pronuncia scritta a mano: {tot}")
    print(f"identiche alla mano:                  {uguali}  ({100 * uguali / tot:.1f}%)")
    print(f"diverse:                              {mancate}")
    if sbagliate and dettagli:
        print("\nLe differenze, una per una (a mano -> automatico):\n")
        for pagina, seq, testo, atteso, ottenuto in sbagliate:
            print(f"  {pagina} #{seq}  {testo}")
            print(f"      a mano:     {atteso}")
            print(f"      automatico: {ottenuto}\n")
    elif sbagliate:
        print("\n--dettagli per vederle una per una.")
    return 0 if mancate == 0 else 1


def main():
    ap = argparse.ArgumentParser(
        description="Aggiunge 'text_tts' a un copione: dal testo stampato a quello da leggere.")
    ap.add_argument("copione", nargs="?", type=Path,
                    help="cartella di pNN.json, o un singolo file")
    ap.add_argument("--voices", type=Path,
                    help="il voices.json della storia, da cui prendere i nomi propri")
    ap.add_argument("--dizionario", type=Path, default=DIZIONARIO_DEFAULT)
    ap.add_argument("--scrivi", action="store_true",
                    help="riscrive i file del copione; senza, mostra soltanto")
    ap.add_argument("--verifica", action="store_true",
                    help="riconverte il copione d'oro e conta quante escono identiche")
    ap.add_argument("--oro", type=Path, default=ORO_DEFAULT)
    ap.add_argument("--dettagli", action="store_true")
    args = ap.parse_args()

    dizionario = json.loads(args.dizionario.read_text(encoding="utf-8"))
    nomi = nomi_della_storia(args.voices)
    pron = Pronuncia(dizionario, nomi)

    if args.verifica:
        sys.exit(verifica(pron, args.oro, args.dettagli))

    if not args.copione:
        ap.error("serve un copione, o --verifica")

    cambiate = 0
    mute = []
    for f in carica(args.copione):
        d = json.loads(f.read_text(encoding="utf-8"))
        for e in d["entries"]:
            tts = pron.converti(e["text"], e.get("type", "dialogue"))
            if tts != e.get("text_tts"):
                cambiate += 1
                if not args.scrivi:
                    print(f"  {f.stem} #{e['seq']}  {e['text']}")
                    print(f"      -> {tts}")
            if not PAROLA.search(tts):
                mute.append(f"{f.stem} #{e['seq']}  {e['text']!r}")
            e["text_tts"] = tts
        if args.scrivi:
            f.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{cambiate} battute {'riscritte' if args.scrivi else 'da riscrivere'}"
          f"{'' if args.scrivi else ' (--scrivi per farlo)'}")
    if mute:
        # Un balloon senza nemmeno una lettera ("!") e' quasi sempre un balloon muto che
        # l'estrattore ha raccolto lo stesso. Da leggere non c'e' niente: o si toglie nella
        # revisione, o il sintetizzatore ci si incarta.
        print(f"\n{len(mute)} battute senza una sola lettera, da togliere in revisione:")
        for m in mute:
            print(f"  {m}")


if __name__ == "__main__":
    main()
