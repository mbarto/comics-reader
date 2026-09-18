# Piano — automatizzare l'estrazione del copione

Il PoC ha lasciato aperto il problema più grosso (`TECNOLOGIE.md` §11): i 131 balloon sono stati
letti e trascritti a mano, uno per uno, in sessione. **Undici minuti di GPU per la sintesi, ore per
la trascrizione.** Questo documento è il piano per chiudere quel buco.

Stato: **fasi 1, 2, 4, 5 fatte e la 8 cominciata.** Testo, battute e ordine sono chiusi;
l'attribuzione sta al 90% su Park Ranger. Il giro completo - PDF, cast, copione, revisione - gira
su una seconda storia mai trascritta (§8-bis), ma senza copione d'oro non se ne puo' misurare la
bonta'. Speso finora in chiamate al modello: $4.55. Aggiornato il 2026-09-18.

---

## 1. Dove sta davvero il costo

Tre cose diverse si nascondono dietro "la generazione del testo è lenta", e conviene separarle
perché si risolvono in modi opposti.

| | cosa costa | quanto |
|---|---|---|
| **a. il modello che guarda la pagina** | token di visione + testo generato | **centesimi** (§4) |
| **b. il farlo dentro una conversazione** | ogni pagina riporta con sé tutto lo storico | **il grosso del conto** |
| **c. l'occhio umano che controlla** | rileggere 131 balloon | ore, oggi |

**La voce (b) è quella che ha fatto male, ed è gratis da togliere.** Leggere 12 pagine di seguito in
una sessione interattiva significa che alla dodicesima il modello sta ancora rileggendo le prime
undici: il costo cresce col quadrato delle pagine, e nessuna delle due parti sta facendo qualcosa di
utile con quel contesto — una pagina di fumetto non ha bisogno di sapere cosa c'era nella pagina
prima, se non per il filo della storia, che sta in tre righe di riassunto.

Dodici chiamate indipendenti da uno script, ognuna con **una pagina e niente altro**, fanno lo
stesso lavoro a costo lineare. È il principio che regge già la pipeline audio — *separare ciò che
costa da ciò che si ritara in pochi secondi* — applicato al pezzo che era rimasto fuori.

La voce (c) non si azzera: resta il controllo umano, e deve restare (§8 di `TECNOLOGIE.md`: il
controllo automatico non sa dire se una lettura è giusta). Ma **rileggere una proposta è minuti,
trascrivere da zero è ore**, ed è lì che va spostato il lavoro (§6).

---

## 2. Quello che il modello vede davvero della pagina

Numeri misurati sui file veri, non stimati (formula ufficiale: un token di visione ogni riquadro di
28×28 px; oltre i limiti l'immagine viene **ridimensionata prima** di essere guardata).

| ciò che mando | Opus 5 / Sonnet 5 (alta risoluzione) | Haiku 4.5 (standard) |
|---|---|---|
| PDF nativo 300 dpi, 2550×3507 | ridotto a **1651×2271** — 4838 token | ridotto a 945×1300 — 1598 token |
| `pages/render/pNN.png`, 1680×2330 | ridotto a 1644×2281 — 4838 token | ridotto a 941×1306 — 1598 token |
| **una striscia, 2550×1169** | **non ridotta** — 3864 token | ridotta a 1568×719 — 1456 token |
| un ritaglio di balloon, 600×300 | **non ridotto** — 242 token | non ridotto — 242 token |

Tre conseguenze che decidono l'architettura:

1. **Una pagina intera non passa mai a più di ~1650 px di larghezza**, qualunque cosa io mandi: il
   tetto è 2576 px di lato lungo *e* 4784 token di visione, e su un foglio 2:3 vince il secondo. Il
   render a 300 dpi che facciamo oggi viene buttato via all'ingresso. Sono ~190 dpi effettivi: bene
   per i balloon, al limite per il corsivo piccolo delle didascalie — esattamente il testo che nel
   giro col filmato è stato il più difficile da leggere.
2. **Un ritaglio passa intatto.** Un balloon a 300 dpi costa 120-250 token e il modello lo vede alla
   risoluzione vera dello scanner. Leggere un balloon per intero costa **venti volte meno** che
   leggere la pagina che lo contiene.
3. **Haiku 4.5 non è di fascia alta risoluzione** (lo sono i modelli dal 4.7 in su). Su una pagina
   intera vedrebbe 945 px di larghezza, e su un lettering tutto maiuscolo con le didascalie in
   corsivo è una perdita che non vale il risparmio. Su un **ritaglio**, invece, vede esattamente
   quello che vede Opus. Questo è il motivo tecnico per cui il piano separa i due passi.

---

## 3. L'architettura proposta: due passi, due mestieri diversi

> ⚠️ **Superata dai fatti, si tiene per memoria.** Il §5-ter ha misurato il testo a **WER 0,1% su 12
> pagine con un passo solo**: il passo B qui sotto è nato per dare risoluzione nativa alla
> trascrizione, e la trascrizione non aveva un problema di risoluzione. Quel che resta valido di
> questa sezione è il ragionamento sui costi (un ritaglio costa venti volte meno della pagina che lo
> contiene) e la nota sulle regole di pronuncia. **Quello che oggi funziona è un passo solo**, con
> due cose che non avevo previsto: una regola sui crediti e la scheda del cast.

Il PoC ha già stabilito qual è la parte difficile: *non* riconoscere le lettere — quella la farebbe
un OCR — ma **l'ordine dei balloon e l'attribuzione dei personaggi**. Sono due problemi con costi
opposti, e oggi li paghiamo insieme al prezzo del più caro.

```
pages/render/pNN.png  (o stack da filmato)
          │
          ├── passo A · REGIA ─────────── pagina intera, 4838 token, modello forte
          │      "quante vignette, in che ordine si leggono, quali balloon ci sono,
          │       dove sta ciascuno, chi parla, che tipo è (dialogo/didascalia/sfx/radio)"
          │      NON chiede il testo esatto
          │      → riquadri + ordine + parlanti
          │
          ├── [ritaglio con margine, solo Pillow, zero costo]
          │
          ├── passo B · TRASCRIZIONE ──── N ritagli, ~180 token l'uno, modello piccolo
          │      "cosa c'è scritto qui dentro, alla lettera"
          │      → testo verbatim, a risoluzione nativa
          │
          ├── [fusione + regole di pronuncia deterministiche → text_tts]
          │
          ▼
   poc/script/pNN.json  (stesso schema di oggi, più le coordinate)
          │
          ▼
   revisione umana in una pagina HTML (§6)  →  pipeline audio invariata
```

**Perché due passi e non uno.** Il passo A ha bisogno di vedere tutta la pagina insieme (la coda del
balloon, il colore, chi è inquadrato, la griglia delle vignette) ma non ha bisogno di risoluzione. Il
passo B ha bisogno del contrario: risoluzione vera su un'area piccolissima, e nessun contesto. Farli
insieme costringe a pagare risoluzione alta su tutta la pagina — che come visto al §2 **non si può
nemmeno comprare**: il ridimensionamento la toglie comunque.

**Sui riquadri approssimativi.** La documentazione avverte che le coordinate che il modello restituisce
sono approssimate. Non è un problema qui: si ritaglia con un **margine generoso** (20-30%), e un
ritaglio largo costa comunque 200 token invece di 150. Meglio sbagliare largo.

**Dove il testo aiuta l'attribuzione.** Il passo B può correggere il passo A: se un balloon dice
"GIÀ, PUOI DIRLO FORTE, MATT!", chi parla non è Matt. Una passata finale di coerenza sul copione
completo — testo, non immagini, costo trascurabile — può segnalare le attribuzioni sospette invece di
lasciarle passare.

**Le regole di pronuncia (`text_tts`) non sono lavoro da modello.** "RANGER" → "rènger", "CAFFE'" →
"Caffè", le maiuscole da abbassare, gli apostrofi tipografici: è un dizionario più qualche regola,
scritto una volta, deterministico e riusabile su tutte le storie. Il modello lo chiami solo per le
onomatopee nuove, che sono poche e vanno comunque riviste a orecchio.

### Alternativa da tenere sul tavolo: rilevamento dei balloon in locale

Al posto del passo A si possono trovare i balloon con OpenCV (componenti connesse chiare con contorno
chiuso scuro dentro ogni vignetta; le vignette con un taglio ricorsivo sui corridoi bianchi). Costo
zero, nessuna chiamata. Non risolve però la parte difficile — l'ordine e il parlante — e sul lettering
dentro il disegno (le onomatopee, che il PoC ha deciso di **leggere**, non saltare) non trova niente.

Vale la pena solo se il §5 dimostra che il passo A sbaglia i riquadri. **Non farlo per primo:** è il
pezzo con più codice e meno resa attesa.

---

## 4. Quanto costa, in soldi

Storia intera: 12 pagine, 131 balloon. Prezzi Claude API 2026-06 (Opus 5 $5/$25 per milione di token
in/out, Sonnet 5 $2/$10, Haiku 4.5 $1/$5). **Batch API: metà prezzo, in cambio dell'asincronia** —
risposta entro un'ora nella maggior parte dei casi, 24 h di tetto. Per "processa un albo" è la
modalità giusta.

| scenario | token in ingresso | storia | con Batch |
|---|---|---|---|
| **A+B: Sonnet 5 regia + Haiku 4.5 testo** | 58k + 24k | $0.24 | **$0.12** |
| **A+B: Opus 5 regia + Haiku 4.5 testo** | 58k + 24k | $0.52 | **$0.26** |
| un passo solo, pagina intera, Opus 5 | 58k | $0.59 | $0.30 |
| un passo solo, 3 strisce native, Opus 5 | 139k | $1.00 | $0.50 |

**Un albo da 50 pagine sta sotto i 2 dollari** nello scenario più caro. A questi numeri il modello non
è la voce di costo: lo era il *modo* in cui lo usavamo.

~~⚠️ **La voce che può sorprendere è il ragionamento.**~~ **Misurato nella fase 2: falso allarme.**
Temevo che il pensiero, che su Opus 5 è attivo di default e si paga come output a $25/Mtok, potesse
valere $0.90 a pagina e dominare tutto il resto. Sono fra **3 e 110 token a pagina** a seconda del
giro, cioè fra $0.0001 e $0.003. Questo compito non fa ragionare il modello: guardare una pagina e
trascriverla è lavoro percettivo, non deduttivo. La voce di costo in uscita è il **JSON stesso**
(~745 token), che non si può togliere perché è il prodotto. Vedi §5-bis per i numeri veri.

Altre due manopole, minori ma gratuite:

- **Cache del prompt** sulla parte fissa (regole di trascrizione, scheda dei personaggi, schema JSON):
  scritta una volta, riletta a un decimo del prezzo. Temevo che la parte fissa fosse troppo corta per
  superare il minimo sotto il quale la cache non scatta: **misurato, scatta** — sono 2098 token, non
  i ~760 che avevo stimato a occhio, e valgono il 17% del costo di pagina. L'immagine invece **non**
  si mette in cache: sta nel messaggio, dopo il blocco fisso, ed è giusto così perché cambia a ogni
  pagina.
- **Cache su disco come quella della sintesi.** Stessa idea già collaudata in
  `synthesize_chatterbox.py`: impronta SHA-256 di ciò che determina il risultato (immagine, prompt,
  modello, versione dello schema) e la pagina non si rifà. Rilanciare la pipeline dopo aver corretto
  una regola deve costare zero sulle pagine già buone.

---

## 5. Il metro — **fatto**

**C'è già una verità di riferimento e non ce ne accorgiamo:** `poc/script/p41.json` … `p52.json` sono
131 balloon letti, trascritti e verificati a mano, con ordine e parlante. È un materiale che di solito
costa caro costruire e qui esiste già.

Quindi il primo pezzo di codice non è l'estrattore: è **`poc/valuta_estrazione.py`**, che confronta un
copione generato con quello d'oro e stampa quattro numeri.

| misura | come | perché conta |
|---|---|---|
| **balloon trovati** | richiamo e precisione sugli `entries` | uno saltato è una battuta muta |
| **testo** | tasso d'errore per parola, normalizzato (maiuscole, accenti, punteggiatura) | è la parte che un OCR farebbe già |
| **parlante** | percentuale di attribuzioni esatte | è la parte difficile |
| **ordine di lettura** | tau di Kendall + numero di inversioni | sbagliarlo rovina il dialogo |

In più, perché cambiano l'audio senza vedersi nel testo: il **tipo** (`sfx` e `credits` hanno una
regia loro in `voices.json`) e i **flag** `radio`/`channel`.

Da qui ogni variante — un passo o due, Sonnet o Opus, pagina intera o strisce, con o senza
rilevamento OpenCV — si sceglie **su una tabella di numeri**, non a impressione.

È la lezione 1 del §8 di `TECNOLOGIE.md` («un difetto vago va localizzato con una misura prima di
inseguirlo») applicata prima di cominciare invece che dopo. E la lezione 4 («una misura che migliora
non è un motivo sufficiente») resta valida: se le strisce native portano il tasso d'errore dal 4% al
3% e raddoppiano il costo, si tengono le pagine intere.

### Com'è stato fatto

Il copione trascritto a mano è congelato in **`poc/script/oro/`** con `SHA256SUMS` e un `LEGGIMI.md`
che spiega perché ora ci sono tre copie in giro e a cosa serve ciascuna. La pipeline audio continua a
leggere `poc/script/`, che resta il copione *in uso*: è lì che l'estrattore automatico scriverà, ed è
quel momento che separerà le due cose. (La cartella è in `.gitignore` con tutto il resto del
materiale protetto: il metro resta in locale, lo script che lo usa no.)

    poc/valuta_estrazione.py CANDIDATO [--pagina N] [--dettagli] [--json] [--tutte]

Solo libreria standard, nessuna dipendenza: gira con `python3`, non serve il venv.

**Le battute si accoppiano per somiglianza del testo, dentro la stessa pagina, non per posizione.**
È la scelta che fa funzionare il resto: bastava un balloon saltato perché tutti i `seq` successivi si
sfasassero e il punteggio del testo crollasse per quello che è in realtà un errore d'ordine. Sotto
una soglia di somiglianza non è la stessa battuta, ed è una mancata più una di troppo.

Il testo si confronta normalizzato — minuscolo, senza accenti, apostrofo come separatore, senza
punteggiatura — perché il lettering è tutto maiuscolo con gli accenti resi da un apostrofo
(`CAFFE'`), e un candidato che scrive `Caffè` ha letto benissimo.

Di suo il confronto si limita alle pagine presenti da entrambe le parti, e lo dichiara in testa:
provare l'estrattore su **una** pagina è il caso normale della fase 2, e contare le altre undici come
mancanti darebbe un WER del 96% che non dice niente. Con `--tutte` si contano, ed è quello che serve
valutando la storia intera.

**Verificato così**, perché uno strumento di misura che nessuno ha misurato non è una rete di
sicurezza:

- copione d'oro contro se stesso → 100% su tutto, WER 0,0%. Se questo non fosse esatto, niente altro
  varrebbe;
- una copia **guastata apposta** con difetti noti — 3 battute tolte, 2 inventate, 2 coppie invertite,
  6 parlanti cambiati, 2 tipi, 1 flag, 4 testi corrotti, e **10 battute riscritte con grafia diversa
  ma contenuto identico**. Il metro ritrova esattamente ognuno dei guasti veri e non segnala nessuna
  delle 10 riscritture, che è la prova che la normalizzazione non conta come errori le differenze di
  grafia. Anche il totale del WER torna a mano: 4 sostituzioni più le 19 parole delle battute saltate
  fanno i 23 errori su 802 parole che stampa.

### Quello che il metro non sa fare

- **Una battuta trascritta così male da non somigliare più all'originale risulta mancante, non
  sbagliata.** Il punteggio delle battute e quello del testo non sono quindi del tutto indipendenti.
  L'alternativa — accoppiare per coordinate invece che per testo — richiederebbe i riquadri, che il
  copione d'oro non ha; se serviranno, arriveranno dal §6 e questo si potrà migliorare.
- **Non misura `text_tts`**: è una trasformazione deterministica a valle (fase 6), non un compito del
  modello.
- **Non dice se il copione è bello.** Come `check_clips.py` per l'audio: sa dire che una battuta è
  attribuita a un altro personaggio, non che l'ordine di lettura scelto, pur plausibile, rende la
  scena meno chiara. Quel giudizio resta umano, ed è il §6.
- **È tarato sulle stesse 12 pagine che deve giudicare.** Vale per scegliere fra varianti, non per
  dire quanto l'estrattore funzionerà su una storia nuova. Quella è la fase 8, e resta il vero esame.

---

## 5-bis. La linea di base — **fatta**

`poc/estrai_copione.py`: un passo solo, pagina intera, risposta vincolata a uno schema JSON (il
modello non può restituire qualcosa di non parsabile né inventare un nome di personaggio — il cast è
un elenco chiuso preso da `voices.json`). Ambiente a parte, `poc/.venv-estrazione`, 48 MB senza
torch, aggiunto a `setup.sh`.

Provato sulla **pagina 41**, 10 battute d'oro. Sei giri, **$0.31 in tutto**.

| giro | battute | ordine | parlante | testo |
|---|---|---|---|---|
| Opus 5, sforzo `high` | 10/10 | tau 0,64 | 100% | **WER 0,0%** |
| idem, pensiero spento | 10/10 | tau 0,64 | 100% | WER 0,0% |
| idem, sforzo `low` | 10/10 | tau 0,64 | 90% | WER 0,0% |
| **`high` + regola sui crediti** | 10/10 | **tau 1,00** | 90% | WER 0,0% |
| ripetizione | 10/10 | tau 1,00 | 100% | WER 0,0% |
| ripetizione | 10/10 | tau 1,00 | 90% | WER 0,0% |

### Il testo non è un problema

**WER 0,0% in tutti e sei i giri**: 66 parole su 66, comprese `CAFFE'` e `HRMPF!`. Il §11 di
`TECNOLOGIE.md` diceva «la parte difficile non è riconoscere le lettere — quella la farebbe un OCR».
Confermato, e in modo più netto del previsto: a ~190 dpi effettivi, la pagina intera basta.

**Conseguenza sulla fase 3:** il secondo passo sui ritagli nasceva per dare risoluzione nativa alla
trascrizione. Se la trascrizione è già perfetta, quel passo non ha più un problema da risolvere. Resta
utile per un motivo diverso — i ritagli servono comunque al §6 — ma non è più una questione di
qualità del testo. **La fase 3 va ridiscussa prima di essere fatta.**

### L'ordine era una convenzione, non un difetto

Le 8 inversioni dei primi tre giri venivano tutte da **un solo elemento**: i crediti. Sul foglio
stanno in fondo, sotto l'ultima striscia; il modello li metteva per ultimi, e geometricamente aveva
ragione lui. È l'oro a incorporare una convenzione presa durante il PoC — i crediti si leggono subito
dopo il titolo, come i titoli di testa di un film — e non gliel'avevo detta. Cinque righe nel prompt e
l'ordine va a **tau 1,00**, stabile su tre giri.

Due cose da tenere a mente:

- **il metro ha esagerato la gravità.** Un elemento fuori posto su dieci fa 8 coppie discordi su 45,
  e tau 0,64 *sembra* un ordine di lettura sfasciato. Se un giorno servirà, distinguere «un elemento
  spostato» da «ordine mescolato» è un'aggiunta a `valuta_estrazione.py`, non un problema del
  modello. Per ora la riga per pagina basta a vederlo.
- **non ogni divergenza dall'oro è un errore del candidato.** Questa era una regola non scritta. Il
  copione d'oro ne contiene probabilmente altre, e si scopriranno allo stesso modo: guardando la
  pagina invece di fidarsi del punteggio.

### L'attribuzione oscilla, e il resto no

Stessa configurazione, stessa pagina, tre giri: parlante **90%, 100%, 90%**. Sempre la stessa battuta,
`GIA', PUOI DIRLO FORTE, MATT!`, attribuita ora a Paperino (giusto) ora a Matt — benché chiami Matt
per nome, e benché il prompt dica già che chi viene chiamato per nome non è chi parla.

È **variabilità fra un giro e l'altro**, non una regola mancante: con la regola identica esce giusta
una volta su tre. Ordine e testo, nelle stesse tre ripetizioni, non si muovono di un millimetro.

Questo mette in discussione come si confrontano le varianti nelle fasi 3 e 4: **su una pagina sola, un
giro solo, una differenza del 10% sul parlante non significa niente.** Le varianti vanno confrontate
su più pagine, o su più ripetizioni, o tutt'e due. È la lezione 3 del §8 di `TECNOLOGIE.md` («se la
differenza è marginale, A/B alla cieca») nella sua versione numerica.

### Il conto, sulla sola pagina 41

Per pagina, Opus 5, sforzo `high`, cache calda: **$0.0437**, 12 secondi.

| voce | token | costo | quota |
|---|---|---|---|
| l'immagine | 4806 | $0.0240 | 55% |
| il JSON in uscita | 745 | $0.0186 | 43% |
| il prompt fisso, da cache | 2098 | $0.0010 | 2% |
| **il ragionamento** | **3** | **$0.0001** | **0,2%** |

⚠️ **Questa tabella vale per la pagina 41 e per nessun'altra.** Sulle 12 pagine il quadro cambia:
vedi §5-ter. La pagina 41 è la prima della storia, mezza occupata dal titolo, con 10 battute e
nessuna scena affollata — è la più facile delle dodici, e l'ho scambiata per rappresentativa.

### Due errori miei, utili da ricordare

Entrambi lo stesso errore, fatto due volte: **stimare i token contando i caratteri.**

1. La prima versione dello strumento stimava i token del JSON a 3,5 caratteri l'uno e dava 391 invece
   di 705, attribuendo così **354 token di ragionamento a un giro in cui il ragionamento era spento**.
   Un numero impossibile, e per fortuna visibilmente impossibile. Ora si usa `count_tokens`, che non
   si paga.
2. Avevo dichiarato che la cache non sarebbe scattata perché il prompt fisso era «~760 token». Sono
   1923. La cache scattava benissimo.

L'italiano tutto maiuscolo con gli apostrofi tokenizza molto peggio di quanto sembri. Regola:
`count_tokens` esiste ed è gratis, i caratteri non si contano a mano.

---

## 5-ter. Tutte e 12 le pagine — **fatto**

Stessa configurazione (Opus 5, sforzo `high`), le 12 pagine intere. **$0.91, 5 minuti e 45.**

| | |
|---|---|
| **testo** | **WER 0,1%** — 1 errore su 802 parole |
| **ordine** | **tau 0,997** — 11/12 pagine perfette, 1 sola inversione |
| battute | 130/131, nessuna inventata |
| **parlante** | **66,2%** |

### Il testo è chiuso

Un errore su 802 parole, su tutte e dodici le pagine, **comprese le didascalie in corsivo piccolo**
che al §2 temevo fossero al limite di quello che ~190 dpi effettivi permettono di leggere. Non lo
erano.

Questo **chiude la questione del §3**: il secondo passo sui ritagli è nato per dare risoluzione
nativa alla trascrizione, e la trascrizione non ha un problema di risoluzione. La fase 3 non va fatta
per quel motivo. Se i ritagli serviranno, sarà per i riquadri del §6, che è un altro discorso.

L'unica battuta mancante è `FINE`, in fondo all'ultima pagina: il modello l'ha presa per un elemento
grafico. Una riga nel prompt.

### Il ragionamento: avevo ragione a preoccuparmi, e torto a smettere

Al §5-bis, misurando **solo la pagina 41**, avevo concluso che il ragionamento è un falso allarme: 3
token, 0,2% del costo. Sulle 12 pagine è **il 66% dei token in uscita**.

| | ragionamento | costo pagina |
|---|---|---|
| p41, p46, p48 | 3 token | $0.037 – $0.046 |
| p50 | 578 | $0.056 |
| p45, p47 | ~1800 | $0.092 – $0.095 |
| **p42** | **6997** | **$0.221** |

La pagina 41 è la prima della storia: mezza occupata dal titolo, 10 battute, nessuna scena affollata.
È la più facile delle dodici, e l'ho presa per rappresentativa. **Una pagina non è un campione.**

Costo reale: **$0.91 la storia, ~$3.80 un albo da 50** — contro i $0.52 e $2.19 che avevo scritto. Il
piano al §4 aveva previsto $0.59; la cifra giusta è il doppio, e nessuna delle due previsioni era
giusta per il motivo giusto.

Resta comunque vero che a questi prezzi il modello non è la voce di costo del progetto. Ma la forma
della curva conta per la fase 4: **il costo è dominato da poche pagine difficili**, quindi lo sforzo
(`low`/`medium`) è una manopola che vale la pena provare proprio lì.

### L'attribuzione: mancava la scheda del cast, e l'avevo io

66,2% sulle 12 pagine, contro il 90-100% di p41. Le confusioni erano tutte fra `otis`, `susy`, `bob`
e `hilde`: i turisti e la ranger dell'altra stazione, cioè i personaggi che compaiono in gruppo.

Il motivo era nel mio prompt, non nel modello: **passavo l'elenco dei nomi e nient'altro.** Paperino
il modello lo riconosce, ovviamente. Matt, Hilde, Otis, Susy e Bob non li ha mai visti, e non gli
avevo detto chi sono — mentre `voices.json` li descrive già: «turista anziano e gioviale, il portavoce
del gruppo», «turista senza fiato: parla solo per chiedere ossigeno», «turista palestrato e
vanaglorioso». Erano appunti di regia per la voce, ma dicono anche *chi è* il personaggio.

Passandole (`scheda_cast()`, verbatim da `voices.json`), sulle **quattro pagine peggiori**:

| | solo i nomi | con la scheda |
|---|---|---|
| parlante | 50,0% (21/42) | **90,5% (38/42)** |
| ordine | tau 1,00 | tau 1,00 |
| testo | WER 0,0% | WER 0,0% |

Diciassette attribuzioni recuperate su 42, molto oltre la variabilità misurata al §5-bis (±1 battuta
su una pagina). Dei quattro errori rimasti, **due sono uno scambio fra Otis e Susy nella stessa
vignetta**: ha preso i balloon giusti e li ha incrociati. Non è più un problema di *chi è chi*, è la
coda del balloon.

⚠️ **Due riserve, dette prima che qualcuno le scopra:**

1. La descrizione di Hilde in `voices.json` contiene un appunto **specifico sulla pagina 42** («nella
   pagina 42 la scena cambia stazione e dalla radio arriva la voce di Paperino»). È un suggerimento
   scritto a mano su questa storia, ed è finito nel prompt. Il confronto 50→90% resta valido — riguarda
   quattro pagine, non solo la 42 — ma la scheda del cast **non è materiale neutro**: è lavoro umano
   per storia, e va contato nel costo della fase 8.
2. Il confronto è su 4 pagine, un giro per parte. Visto quanto oscilla l'attribuzione, la cifra vera
   sarà più bassa del 90,5%.

### La scheda del cast su tutte e 12, due volte

| | giro 1 | giro 2 |
|---|---|---|
| battute | **131/131** | **131/131** |
| testo | **WER 0,0%** | **WER 0,0%** |
| ordine | tau 0,997 | tau 0,997 |
| parlante | 89,3% | 90,8% |
| costo | $0.74 | $0.83 |

**Testo perfetto: 802 parole su 802, due volte.** Battute: 131 su 131, nessuna inventata — la riga sul
`FINE` ha chiuso l'unica mancante. L'attribuzione si assesta fra **89% e 91%**: a livello di storia lo
scarto fra i due giri è di un punto e mezzo, molto più stabile di quanto suggerisse la singola pagina
del §5-bis, dove oscillava del 10%. Su 131 battute il rumore si media; su 10 no.

Costo: **$0.74–$0.83 la storia**, sceso del 13% rispetto agli $0.91 senza la scheda. Dandogli chi sono
i personaggi il lavoro gli diventa più facile e ragiona di meno (dal 66% al 44-55% dei token in
uscita). Il costo resta la cifra più ballerina di tutte — stessa identica configurazione, 12% di
differenza fra un giro e l'altro — perché dipende da quanto il modello decide di pensare.

### Cosa resta sbagliato, e quanto è colpa del caso

Confrontando le stesse 131 battute nei due giri indipendenti:

| | |
|---|---|
| giuste in tutti e due i giri | **116** |
| **sbagliate in tutti e due, con i due giri d'accordo fra loro** | **10** — sistematiche |
| i due giri non concordano fra loro | 5 — incerte (in 4 casi su 5 uno dei due aveva ragione) |

Gli errori sistematici, tutti e dieci:

- **cinque sono scambi fra Otis e Susy nella stessa vignetta** (p51, p52 due volte): balloon giusti,
  attribuiti a rovescio. Sono *simmetrici* — sbagliarne uno significa sbagliare anche l'altro.
- **due confusioni fra i due ranger**, Paperino preso per Matt (p41, p46).
- **due didascalie** attribuite a un personaggio, o viceversa (p45, p47 — quest'ultima ha il testo
  fra virgolette nell'originale, il che probabilmente inganna).
- **una onomatopea**, `HRMPF!` di Matt data a Paperino.

**Conseguenza scomoda per il §6:** girare due volte e segnalare i disaccordi *non* è una rete di
sicurezza. Costerebbe il doppio e intercetterebbe **4 errori su 15**, perché i dieci sistematici sono
sbagliati con sicurezza in entrambi i giri. La revisione umana deve guardare tutte le attribuzioni,
non solo quelle segnalate. Quello che il doppio giro compra davvero è poco, e non vale il prezzo.

### Dove siamo

| | stato |
|---|---|
| **testo** | **chiuso** — WER 0,0%, 802/802 parole, due volte |
| **battute** | **chiuso** — 131/131, niente saltato, niente inventato |
| **ordine** | **chiuso** — tau 0,997, 11/12 pagine perfette |
| **attribuzione** | **89-91%**: ~12 battute su 131 restano da correggere a mano |

Il problema aperto del PoC («l'ordine dei balloon e l'attribuzione dei personaggi») è per metà
risolto. Quel che resta — una dozzina di attribuzioni a pagina-storia, di cui cinque sono due coppie
scambiate — è lavoro da **minuti** di revisione, non da ore di trascrizione. Che era l'obiettivo.

Speso in tutto: **$1.95**.

---

## 6-bis. La pagina di revisione — **fatta**

`poc/rivedi.py` genera un file HTML statico: nessun server, nessuna dipendenza oltre a quelle che
c'erano già, funziona da `file://`.

    poc/.venv-estrazione/bin/python poc/rivedi.py poc/estrazione/riquadri
    (si apre poc/revisione/index.html, si corregge, si preme "Scarica il copione")
    poc/.venv-estrazione/bin/python poc/rivedi.py --applica ~/Scaricati/copione-rivisto.json

A sinistra la pagina con i **riquadri numerati nell'ordine di lettura**; a destra le battute, con
testo modificabile, parlante e tipo a tendina, le bandierine `radio` e `sussurro`. Passando il mouse
su una riga si accende il riquadro corrispondente e viceversa; cliccando un riquadro si va alla riga.
Per spostare una battuta ci sono le frecce, oppure si scrive direttamente la posizione — i crediti
dal decimo posto al secondo sono una cifra, non otto clic. Poi unisci alla precedente, aggiungi,
elimina.

Il ritorno passa da un `copione-rivisto.json` scaricato dal browser e riportato nei `pNN.json` da
`--applica`, che mette da parte le versioni precedenti come `.json.prima`.

### I riquadri

Chiesti con `--riquadri` (`bbox` nello schema). Costano **$0.95 la storia** invece di $0.79, e non
peggiorano niente: 131/131 battute, WER 0,0%, tau 0,997, parlante 90,1% — in linea con i giri senza.

Su 25 battute controllate a occhio su due pagine, **25 riquadri su 25 cadono sul balloon giusto**.
Qualcuno taglia la prima riga di un balloon su più righe: irrilevante per indicare *dove guardare*,
da allargare se un giorno serviranno per ritagliare.

**Ricaduta gratuita:** sono le coordinate che il §11 di `TECNOLOGIE.md` elencava come mancanti per
un'applicazione che evidenzi il balloon in corso durante l'ascolto. Vengono da sé.

### I controlli, e perché sono pochi

Il §5-ter aveva già stabilito che **un punteggio di confidenza non serve**: su due giri indipendenti,
10 errori su 15 erano sbagliati identicamente in tutti e due. Quindi la pagina mostra sempre tutte le
battute, e i controlli colorano senza filtrare. Sono tre, e sono **fatti verificabili**, non stime:
una battuta che nomina il personaggio a cui è attribuita, due riquadri sovrapposti, una battuta senza
riquadro.

Il primo è costato tre giri di messa a punto, tutti e tre partiti da un collaudo:

1. **non scattava mai.** Cercava lo stesso separatore da entrambi i lati (`" MATT "`, `",MATT,"`),
   mentre il caso vero è `" MATT!"`. La versione JS nella pagina era giusta e quella Python no: erano
   divergenti, e nessuno se ne era accorto perché nessuna delle due era stata provata.
2. **gridava sulle chiamate radio.** `RANGER HILDE A PICCO FIOCCO!` è Hilde che si annuncia: un
   nominativo, non un vocativo. Eccezione sulle battute `radio`.
3. **gridava sulle presentazioni.** «IO SONO OTIS», «CHIAMATEMI SUSY», «IL MIO NOME È BOB»: quattro
   falsi allarmi per storia, tre nella sola pagina in cui i turisti si presentano uno dopo l'altro, e
   **zero errori veri pescati**. Un avviso che grida e non prende niente insegna solo a ignorarlo.

Sulle 12 pagine il controllo ora tace del tutto — e questo è il risultato onesto, non un fallimento:
i 13 errori di attribuzione che restano non sono di un tipo che un controllo deterministico possa
vedere. Sono scambi fra due personaggi nella stessa vignetta, e li vede solo un occhio sulla pagina.
È esattamente il motivo per cui questa pagina esiste.

### Il copione estratto è già sintetizzabile

`synthesize_chatterbox.py` legge `entry.get("text_tts") or entry["text"]`: senza `text_tts` ricade sul
testo stampato senza errori. La fase 6 migliora la pronuncia (`CAFFE'` letto alla lettera), **non è un
blocco**. La storia si può già rifare dal PDF senza sessione.

Speso in tutto fino a qui: **$3.11**.

---

## 6. La revisione umana, che è il vero risparmio di tempo

Anche a estrazione perfetta al 95%, qualcuno deve guardare. La differenza fra ore e minuti sta in
**come** guarda.

`poc/rivedi.py` genera una pagina HTML statica, una per pagina di fumetto:

- l'immagine della pagina, con i riquadri dei balloon sovrapposti e **numerati nell'ordine di
  lettura** — l'errore di ordine si vede a colpo d'occhio, senza leggere niente;
- accanto, la lista delle battute: testo modificabile, parlante da menu a tendina (il cast viene da
  `voices.json`), tipo (dialogo/didascalia/sfx/radio);
- trascinamento per riordinare, un pulsante per unire o dividere una battuta;
- **evidenziate le cose di cui il modello non è sicuro** — attribuzioni contraddette dal testo,
  balloon senza coda, sovrapposizioni — così lo sguardo va dove serve;
- salva lo stesso `pNN.json` di oggi.

Tutto lato browser, nessun server, nessuna dipendenza nuova.

**Ricaduta che non costa niente:** i riquadri sono le **coordinate** che il §11 elencava come mancanti
per un'applicazione che evidenzi il balloon in corso durante l'ascolto. Vengono gratis da questo
piano, basta scriverle nel JSON.

---

## 7. Il ramo filmato

Il filmato non ha lo stesso problema, ne ha uno suo: lo stack funziona
(`video/trascrizione-cieca.md` lo dimostra su materiale mai visto), ma **ogni pagina va indicata a
mano** con `--da` e `--a`. Su un albo intero è un lavoro noioso quanto la trascrizione.

**Segmentazione automatica delle voltate.** La differenza fra fotogrammi consecutivi è piatta mentre
la pagina sta ferma e ha un picco netto quando si volta. Gli intervalli fra i picchi sono le pagine.
È una decina di righe sopra quello che `stack_video.py` già fa, e toglie l'ultimo passaggio manuale
del ramo acquisizione.

Due dettagli dai numeri del §2:

- il video buono è 1920×1080 h264 (`video/Video 2026-09-16 11-54-45.mp4`): **un singolo fotogramma
  nitido passa intatto** sul modello ad alta risoluzione, 2691 token. Vale la pena misurare se, su
  una ripresa 1080p ravvicinata, lo stack serve ancora — potrebbe essere una complicazione che il
  formato h264 a piena risoluzione ha già reso inutile;
- se serve, **lo stack va ritagliato a strisce prima di mandarlo**, non spedito intero: ingrandire
  4× per poi farselo ridurre a 1650 px all'ingresso è lavoro sprecato.

---

## 8. Ordine di esecuzione

Ogni fase ha una condizione d'uscita misurabile. Se una fase non la raggiunge, si ferma lì e se ne
parla, invece di costruirci sopra.

| # | fase | esito atteso |
|---|---|---|
| ~~1~~ | ~~`valuta_estrazione.py` + copione d'oro in `poc/script/oro/`~~ | **fatto** — §5 |
| ~~2~~ | ~~passo unico, pagina intera, una sola pagina, misurato~~ | **fatto** — §5-bis |
| ~~3~~ | ~~passo A + passo B su ritagli~~ | **annullata** — il testo e' a WER 0,1% su 12 pagine, il passo B non ha piu' un problema da risolvere (§5-ter) |
| ~~4~~ | ~~scheda del cast su tutte e 12, con ripetizioni~~ | **fatto** — §5-ter. Resta da provare lo sforzo `low`/`medium` sulle pagine care |
| ~~5~~ | ~~`rivedi.py`~~ | **fatto** — §6-bis. Da misurare sul campo se una pagina si rivede in meno di 5 minuti |
| 6 | dizionario di pronuncia deterministico per `text_tts` — **il prossimo** | la pronuncia torna quella del PoC (senza, la sintesi ricade sul testo stampato e legge "CAFFE'" alla lettera) |
| 7 | segmentazione automatica delle voltate nel filmato | `stack_video.py` senza `--da`/`--a` a mano |
| 8 | prova su una storia mai vista — **cominciata** | il giro gira su *Le copie a ripetizione* (§8-bis). Per un numero servono poche pagine d'oro trascritte a mano su quella storia |

La fase 8 è la sola che conta davvero per la domanda «questo progetto va avanti?». Tutto ciò che sta
sopra è tarato sulle stesse 12 pagine che hanno prodotto il metro, e il §11 di `TECNOLOGIE.md` è già
esplicito su quanto poco valga una misura fatta sul materiale che l'ha generata.

---

## 8-bis. Il cast di una storia nuova — **fatto**, e la fase 8 è cominciata

Era «il primo pezzo da progettare» del §9. `poc/ricognizione_cast.py` guarda le pagine di una
storia e propone il cast: chi parla, come si riconosce, quante battute ha, chi merita una voce.
Scrive un `voices.json` di partenza ereditando dal file esistente tutto ciò che non dipende dal cast
(pulizia, canali, pause, EQ).

### Collaudato dove la risposta si sapeva

Fatto girare su Park Ranger **fingendo di non conoscere il cast**, e confrontato col `voices.json`
scritto a mano: ha ritrovato **6 principali su 6** — paperino, bob, otis, susy, hilde e il collega
ranger — e ha messo di sua iniziativa il procione e la capra fra le comparse al narratore, che è la
decisione che il PoC aveva preso a orecchio.

Sull'unico nome che ha sbagliato ha avuto ragione lui: ha chiamato Matt **«arch»**, segnalando nelle
note che «a p41 Paperino lo chiama Matt, a p45 lo chiama Arch». Il copione d'oro ha la stessa nota
nello stesso punto. Ha ritrovato da solo un'incoerenza vera del fumetto, non ne ha inventata una.

### La storia nuova

`pages/paperone-copie-ripetizione.pdf` — *Zio Paperone e le copie a ripetizione*, pagine 67-76.

**`poc/render_pagine.py`** sostituisce `render_pages.sh`, che funzionava solo per il primo PDF: i
ritagli delle pagine singole erano coordinate fisse trovate a occhio. Ora si misurano. La pagina si
trova dalla **cornice gialla cercata per tinta** — sul bordo che finisce nella piega il giallo è in
ombra e un test su R/G/B lo perde — e quando si vede un bordo solo la larghezza si deduce dal
rapporto noto di una pagina di Topolino. La piega resta la colonna più scura della fascia centrale,
come nel PoC. Dieci pagine, tutte sul rapporto giusto, nessun balloon tagliato.

Vanno ancora dette tre cose che nessuna euristica indovina: quali fogli sono doppi, di quanto è
ruotato ciascuno (0° e 180° sono identici, geometricamente) e il numero della prima pagina.

### Cosa si è visto sulla storia nuova

**Quindici personaggi che parlano**, contro i sette di Park Ranger — e nove hanno una o due battute.
Il tetto delle voci che il PoC aveva già incontrato non è un caso particolare: è la norma.

Due difetti trovati provando, tutti e due strutturali:

1. **La scelta di chi ha voce non va chiesta al modello.** Aveva dato voce a un personaggio da 3
   battute lasciandone fuori uno da 6. È ordinare e tagliare: ora lo fa il codice. Al modello si
   continua a chiedere di *contare* le battute, che è la parte che richiede di guardare.
2. **Una comparsa retrocessa non deve sparire dall'elenco.** Il venditore di posate, una battuta
   sola, era stato tolto dal cast — e la sua battuta è finita al cuoco, l'altro personaggio col muso
   da cane. Se il modello non può dire «il venditore» non tace: sceglie il meno sbagliato fra quelli
   che gli restano. Ora le comparse restano nominabili **con i parametri del narratore**: suonano
   come lui senza che la sintesi debba sapere niente.

### Il giro completo, su materiale mai visto

    PDF → render_pagine.py → ricognizione_cast.py → voices-paperone.json
        → estrai_copione.py --voices → rivedi.py

Provato su p67: titolo, crediti al posto giusto (la convenzione regge su una storia diversa), testo
corretto, e il venditore di posate attribuito a sé stesso. **Il giro si chiude su una storia che
nessuno ha mai trascritto.**

Quello che ancora **non** si può dire è quanto sia giusto: per questa storia non esiste un copione
d'oro, quindi il metro non può dare un numero. Sapere se il 90% di attribuzione regge fuori da Park
Ranger richiede di trascrivere a mano qualche pagina di confronto — poche, non tutte e dieci.

Speso in tutto: **$4.55**.

---

## 9. Cose decise e cose ancora aperte

**Decise dal PoC, non si rimettono in discussione qui:**
- il TTS resta locale — la voce di Mauro non lascia la macchina. Questo piano **non tocca la sintesi**:
  riguarda solo il testo, e le pagine passano già oggi per una sessione, quindi non cambia niente sul
  fronte della riservatezza.
- le onomatopee si leggono, non si saltano: il passo A deve trovarle anche se non stanno in un
  balloon, ed è la parte dove un rilevatore geometrico fallirebbe.
- resa a voce unica con regia sui personaggi: `voices.json` resta la fonte del cast.

**Decise dai numeri, dopo le fasi 2-5:**
- ~~un passo o due~~ → **un passo solo**: il testo è a WER 0,0%, il secondo passo non serviva;
- ~~pagina intera o strisce native~~ → **pagina intera**: il corsivo piccolo si legge lo stesso;
- ~~rilevamento OpenCV~~ → **non serve**: 25 riquadri su 25 dal modello cadono sul balloon giusto.

**Ancora aperte:**
- **Opus 5 o Sonnet 5**: mai provato. Costerebbe 2,5 volte meno, e il compito si è rivelato più
  facile del previsto — è il primo risparmio da misurare.
- **sforzo `low`/`medium` sulle pagine care**: il costo è concentrato su poche pagine difficili
  (p42 da sola vale $0.22 su $0.83). A `low`, su una pagina, l'attribuzione era peggiore — ma era
  una pagina e un giro, cioè niente.
- **le ultime 13 attribuzioni**: nessuno le ha ancora corrette davvero. Finché il copione corretto
  non viene sintetizzato e riascoltato, «minuti invece di ore» resta una previsione, non una misura.
- ~~da dove viene la scheda del cast per una storia nuova~~ → **fatto**, §8-bis. Resta da misurare
  se il cast proposto regge quanto quello scritto a mano.

**Il buco più grosso del piano, ed è nella fase 8.** Il salto dell'attribuzione dal 66% al 90% viene
tutto da `voices.json`, che è **scritto a mano per questa storia**: i sette nomi, e le descrizioni che
distinguono tre turisti fra loro. Per un fumetto mai visto non esiste, e non si può generare dal
nulla — servirebbe una passata di ricognizione sulle prime pagine che *proponga* il cast (chi ricorre,
come lo chiamano gli altri, che carattere ha) da far rivedere a mano prima di partire. Non è
pianificata, non è stimata, e senza di essa la fase 8 misurerebbe il caso peggiore invece di quello
vero. È il primo pezzo da progettare, non l'ultimo.

**Aperta, e non la risolve questo piano:** il copyright. Un albo intero processato in automatico
resta un'opera derivata da materiale protetto (`TECNOLOGIE.md` §10). Automatizzare abbassa il costo
di farlo, non cambia di una virgola cosa se ne può fare.
