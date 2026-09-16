# Comics Reader — le tecnologie e come sono state usate

Documento tecnico del proof of concept: leggere ad alta voce un fumetto scansionato, balloon dopo
balloon, con la voce clonata di Mauro. Lo stato del lavoro e la cronologia delle decisioni stanno in
`poc/PIANO.md`; qui c'è **cosa** è stato usato e **perché è stato usato così**.

Risultato di riferimento: `poc/out/storia.mp3`, 6 minuti e 35 secondi, 131 balloon su 12 pagine.

---

## 1. Macchina e ambiente

| | |
|---|---|
| GPU | NVIDIA RTX 4070 Laptop, 8 GB — il modello ne usa ~2,5 |
| CPU / RAM | 20 core, 62 GB |
| Sistema | Ubuntu 22.04.5, CUDA 12.4 |
| Python | 3.10.12 in due virtualenv separati |

**Due ambienti, non uno.** I due modelli TTS provati hanno dipendenze incompatibili fra loro:

| | `poc/.venv` (XTTS) | `poc/.venv-chatterbox` (in uso) |
|---|---|---|
| modello | `coqui-tts` 0.27.5 | `chatterbox-tts` 0.1.7 |
| torch | 2.5.1+cu121 | 2.6.0 |
| transformers | 4.57.6 | 5.2.0 |
| numpy | 2.2.6 | 1.26.4 |

Il venv XTTS sopravvive perché ci girano gli strumenti di misura e il montaggio, che hanno bisogno
solo di numpy, soundfile e ffmpeg.

Gli ambienti e i pesi si ricostruiscono da zero con **`poc/setup.sh`**, che ha dentro tutte le
contromisure elencate qui sotto. Non è un di più: senza, rifare l'ambiente significa ripercorrere a
mano il giro più doloroso del progetto.

**Trappole dell'ambiente**, tutte incontrate sul campo:
- `python3-venv`/`ensurepip` non sono installati e non si voleva un `sudo apt install`: gli ambienti
  sono creati con **uv**, che produce comunque un venv standard;
- `uv` va lanciato con `UV_HTTP_TIMEOUT=90` e `UV_CONCURRENT_DOWNLOADS=4`: con i valori di default
  multiplexa decine di download su un'unica connessione HTTP/2 verso il CDN di PyPI, e quella
  connessione si pianta senza errore restando appesa fino al timeout;
- `coqui-tts` dichiara `transformers>=4.57` **senza limite superiore**: uv installa la 5.x, che ha
  rimosso `isin_mps_friendly`, e l'import esplode. Va vincolato a `<5`;
- `uv venv` non installa `setuptools`, che serve a `resemble-perth` (il watermarker di Chatterbox)
  per `pkg_resources`; e va tenuto a **`setuptools<81`**, perché dalla 81 `pkg_resources` non c'è più.

**La rete è stata il collo di bottiglia del progetto.** Né uv, né pip, né `huggingface_hub` sanno
*riprendere* un trasferimento interrotto, e su questa connessione i trasferimenti si piantano a
metà: ogni stallo costava l'intero file. I 3 GB di pesi del modello sono stati scaricati con
`curl -C -` (ripresa dal byte esatto), `--speed-limit`/`--speed-time` per abbandonare le connessioni
morte, e **IPv4 + HTTP/1.1 forzati** — con HTTP/2 arrivavano `Connection reset by peer` a metà file.

---

## 2. Sintesi vocale e clonazione

### Il modello: Chatterbox Multilingual (Resemble AI, 2025)

Cloning zero-shot da un singolo campione di riferimento, italiano nativo, gira in locale — requisito
non negoziabile del progetto: **la voce non deve lasciare la macchina**.

Due manopole, che sono diventate lo strumento principale di regia:
- **`exaggeration`** — intensità espressiva;
- **`cfg_weight`** — quanto il modello aderisce al riferimento invece di prendersi libertà.

Si carica con `from_local()` e non `from_pretrained()`, perché i pesi sono stati scaricati a parte
con curl: `huggingface_hub` su questa rete resta appeso a metà file **senza sollevare eccezioni**,
quindi nessun meccanismo di ritentativo può intervenire.

### Il modello scartato: XTTS-v2 (Coqui, 2023)

Provato per primo, abbandonato dopo nove giri di taratura: produce un timbro **metallico** che non
si toglie in nessun modo, perché sta nel vocoder HiFi-GAN e non nella catena di post-produzione (la
prova decisiva: l'uscita grezza del modello, senza alcun trattamento, era già metallica). Confronto
sulle stesse frasi:

| | Chatterbox | XTTS-v2 |
|---|---|---|
| SNR della clip grezza | 46-54 dB | 30,5 dB |
| escursione d'intonazione | 4,2-4,7 semitoni | 3,14 |
| timbro | pulito | metallico |

Per riferimento, la voce reale di Mauro ha 4,30 semitoni di escursione: XTTS appiattiva, Chatterbox no.

### Il riferimento vocale

`poc/prepare_voice.sh` prepara le finestre di riferimento: `highpass` + denoise **prima** della
normalizzazione, e soprattutto genera 6 finestre candidate tenendo **solo le 3 con l'SNR migliore**.
Il motivo: il modello clona le condizioni di registrazione insieme al timbro, quindi una finestra
rumorosa peggiora il risultato.

### L'altezza si corregge a monte, non a valle

Il modello genera sistematicamente più acuto della voce reale. La correzione ovvia — trasporre
l'uscita con `rubberband` — è stata **misurata e scartata**: un phase vocoder che sposta di sei
semitoni lascia artefatti che l'orecchio riconosce subito.

La soluzione è intonare il **riferimento** prima della generazione (`REF_PITCH = 0,89`): il modello
genera già alla nota giusta e il vocoder sintetizza da zero, quindi l'uscita resta pulita. Lo stesso
meccanismo dà l'altezza dei personaggi, `REF_PITCH × pitch` del personaggio.

⚠️ Limite noto: la risposta del modello è stata misurata solo fra x0,86 e x1,00 del riferimento;
oltre è estrapolazione. E la variabilità fra una battuta e l'altra (6-8 semitoni) resta più grande
degli scostamenti voluti fra personaggi, quindi **l'altezza da sola non li distingue**: a farlo sono
`exaggeration`/`cfg_weight` e il testo.

---

## 3. Elaborazione audio: ffmpeg

ffmpeg 4.4.2 fa tutto il resto. Filtri usati, e a cosa servono:

| filtro | uso nel progetto |
|---|---|
| `highpass` | pulizia di base, e taglio dei bassi che impastano per personaggio |
| `equalizer` | banda di presenza a 3 kHz (poi rimossa, vedi sotto) |
| `acompressor` | onomatopee più energiche, e il filtro radio |
| `alimiter` | **paracadute a −1 dB**: alcune clip escono dal modello già a fondo scala e la catena le spingeva oltre. Va messo `level=false`, altrimenti alimiter rialza il volume da solo |
| `aeval=tanh(...)` | saturazione morbida, per la voce dalla ricetrasmittente |
| `highpass`+`lowpass` 300-3000 | il passa-banda che *fa* l'effetto radio |
| `rubberband` | trasposizione con `formant=preserved` — usato solo sul riferimento, mai sull'uscita |
| `loudnorm` | normalizzazione finale, `I=-16:TP=-1.5:LRA=11`, **una volta sola** |
| `anullsrc` | generazione dei silenzi fra un balloon e l'altro |
| demuxer `concat` | montaggio senza ricodifica |

**La catena di post-produzione è stata svuotata, non arricchita.** Era nata per compensare un
microfono scuro e il vocoder di XTTS; con una registrazione pulita e un modello che genera bene,
quegli stadi non correggevano più niente. Un **A/B alla cieca** a quattro giri, con i file rimescolati
e normalizzati allo stesso volume, ha dato "pari" tutte e quattro le volte: si è tenuta la catena
ridotta perché a parità di risultato ha meno stadi da ritarare.

Quel che resta è solo ciò che è un **effetto voluto**: il filtro radio, il compressore delle
onomatopee, il limiter di sicurezza.

---

## 4. L'architettura della pipeline

```
pages/*.pdf ──[pdftoppm + ImageMagick]──> pages/render/pNN.png
                                                  │
                                          (lettura in sessione)
                                                  ▼
                                          poc/script/pNN.json
                                                  │
        poc/voices.json ──────────────────────────┤
     (regia: personaggi, canali, pause)           │
                                                  ▼
                              [synthesize_chatterbox.py]  GPU
                                  cache + ritentativo
                                                  ▼
                                        poc/clips/pNN/*.wav
                                                  │
                                     [assemble.py]  solo ffmpeg
                              pulizia clip → carattere → canale → pause
                                                  ▼
                     poc/out/pagine/pNN.mp3   e   poc/out/storia.mp3
```

**Il principio che regge tutto: separare ciò che costa GPU da ciò che costa secondi.** La sintesi è
la parte lenta e si tocca il meno possibile; regia, filtri, pause e montaggio stanno a valle e si
ritarano in pochi secondi con `--assemble`.

### La cache della sintesi

Ogni clip è marcata con l'impronta SHA-256 di **ciò che la determina**: testo, personaggio,
`exaggeration`, `cfg_weight`, `pitch`, `REF_PITCH`, seed, lingua, e il canale se c'è. Se l'impronta
non cambia, la clip non si rifà; se la cache copre tutto, il modello non viene nemmeno caricato
(sono ~30 s e 2,5 GB di VRAM per non generare niente). La cache si scrive **dopo ogni clip**, così
un'interruzione a metà pagina non costringe a rifare quelle già buone.

Chiavi facoltative (`canale`, `scelta_altezza`) entrano nell'impronta **solo quando sono attive**,
così una funzione nuova non invalida il lavoro già fatto.

### Il ritentativo sulle prese difettose

Il modello sbaglia spesso: su una pagina appena sintetizzata il ritentativo interviene su **circa una
battuta su tre**. La regola è netta:

- i difetti che il montaggio sa togliere — vuoti interni, code di silenzio, code spurie — **non**
  fanno rifare la presa: sarebbe GPU spesa per un problema già risolto a valle;
- quelli che restano nel file generato — parola troncata, clipping, clip muta, ripetizione, battuta
  incompleta o spezzata — fanno rigenerare con un altro seed, fino a 5 tentativi. Si tiene la prima
  presa pulita, o la meno compromessa se nessuna lo è.

### I canali: `radio` e `sussurro`

Un canale è **come** la voce arriva a chi ascolta, non chi la produce. La distinzione è nata da una
pagina in cui la scena cambia stazione a metà: fino a metà pagina dalla ricetrasmittente esce la voce
di Hilde, poi esce quella di Paperino. Modellare la radio come un *personaggio* avrebbe richiesto di
duplicare tutto il cast.

Quindi il canale sta sulla battuta (`"radio": true`, `"channel": "sussurro"`) e si somma a qualunque
personaggio. Il `sussurro` agisce **anche sulla generazione** — `exaggeration` 0,35 invece di 0,7-0,9
— perché una battuta detta a mezza voce non è solo più bassa: è meno enfatica.

---

## 5. Gli strumenti di misura scritti per il progetto

Sono la parte che ha fatto la differenza, più di qualunque scelta di modello.

### `poc/measure.py`
SNR (parlato al 90° percentile contro la finestra più silenziosa), energia nella banda 2-4 kHz
(l'indice di intelligibilità: lì stanno le consonanti), tempo di decadimento a −20 dB (l'indice di
riverbero).

### `poc/intonation.py`
F0 per autocorrelazione su finestre da 40 ms, escursione in semitoni. Serve a una cosa che nessuna
misura spettrale vede: **se la voce "canta" mentre parla**. Riferimenti: sotto 2 semitoni suona
monotono, 3-5 è parlato espressivo.

### `poc/check_clips.py`
Il controllo qualità automatico sulle 131 clip. Non giudica la qualità — quella resta all'orecchio —
ma trasforma un "c'è qualche artefatto qua e là" in un elenco di minuti e secondi. Difetti cercati:

| difetto | come si riconosce |
|---|---|
| `muta` | nessun tratto sonoro |
| `incompleta` | oltre 45 caratteri al secondo di parlato: il testo non è stato detto |
| `spezzata` | vuoto > 0,9 s dentro un testo di una o due parole |
| `ripetizione` | l'inviluppo di energia somiglia a se stesso a un certo ritardo |
| `troncata` | la clip finisce con segnale sopra −20 dBFS |
| `clipping` | campioni a fondo scala |
| `coda`, `vuoto` | silenzi in fondo o in mezzo (riparabili dal montaggio) |
| `lenta`, `veloce` | ritmo fuori dalla distribuzione misurata |

**Due lezioni di metodo dentro questo file.**

*La misura va fatta dove il difetto vive.* Ripetizione e battuta spezzata si misurano sulla clip
**grezza**, non su quella lavorata: il montaggio accorcia i vuoti e così facendo cancella proprio le
tracce che li rivelano — "Beeeeeh! Beeeeeh!" scende da 0,86 a 0,55 di autosomiglianza e passerebbe
liscio, pur restando due belati all'ascolto.

*Le soglie vanno tarate sui dati, non stimate.* Le prime soglie di ritmo venivano da dieci clip di
una pagina sola e da una misura che includeva le pause: una battuta con i puntini di sospensione
risultava "lenta" solo per via della pausa. Ritarate sulla distribuzione reale delle 131 clip
(mediana 20,3 car/s, percentili 12,0-32,9) e misurando il **solo parlato**, hanno subito trovato una
clip incompleta che nessuno aveva segnalato.

---

## 6. Dalle scansioni alle pagine

`poc/render_pages.sh`, con `pdftoppm` (poppler 22.02) e ImageMagick 6.9.11.

Il PDF è una scansione pura senza livello di testo: `pdftotext` restituisce 7 byte. Le pagine 2-6 del
PDF sono **doppie e ruotate di 90°**, le pagine 1 e 7 contengono anche articoli estranei.

Tre cose imparate, tutte finite nello script:
- la rotazione è **oraria** (così la pagina pari finisce a sinistra e la dispari a destra);
- **la piega non sta a metà del foglio**: sta a x≈1900-1960 su 3508. Tagliare a metà, che sembrava
  ovvio, mangiava l'ultima striscia della pagina di sinistra. Si trova cercando la **colonna più
  scura** nella fascia centrale, e si ricalcola per ogni foglio;
- il taglio lascia 30 px di sovrapposizione: un filo della pagina accanto è meno grave di un balloon
  tagliato.

---

## 7. Dal filmato alle pagine (esperimento)

`poc/stack_video.py`: leggere il fumetto da un video invece che dallo scanner.

**Il problema.** Un singolo fotogramma di un video 704x576 non basta: il testo dei balloon sta su 5-6
pixel di altezza.

**Il metodo.** Il libro è tenuto a mano, quindi ogni fotogramma è spostato di una frazione di pixel
rispetto agli altri. Si estraggono i fotogrammi dell'intervallo, si tengono i più nitidi (varianza
del laplaciano), si allineano per **correlazione di fase** e si mediano a risoluzione moltiplicata,
chiudendo con una maschera di contrasto. L'allineamento si calcola sulla luminanza ma la media si fa
sui tre canali, perché il colore dei balloon dice chi parla.

**Cosa conta davvero.** Tre riprese a confronto hanno mostrato che la risoluzione dichiarata dice
poco:

| | codec | risoluzione | esito |
|---|---|---|---|
| 1ª | h263 | 704x576 | stack leggibile su una pagina, no sulla doppia |
| 2ª | h263 | 704x576 a 2 fps | inutilizzabile: pochi fotogrammi da impilare |
| 3ª | **h264** | 640x480 | leggibile su entrambe, pur avendo **meno** pixel |
| 4ª | h264 | **1920x1080** | leggibile anche il corsivo piccolo delle didascalie |

h263 è un formato del 1996 che sui dettagli fini fa piazza pulita; h264 li conserva. **Conta quanti
pixel sopravvivono alla compressione, non quanti ne dichiara il contenitore.**

**Verifica onesta.** Le prime riprese mostravano pagine già trascritte dallo scanner, quindi la
lettura non provava niente. La prova è stata fatta due volte su materiale mai visto: un articolo di
giornale nella pagina accanto (confrontato poi con la scansione a 300 dpi) e infine due pagine di
un'altra storia, trascritte alla cieca in `video/trascrizione-cieca.md`.

---

## 8. Quello che il progetto ha insegnato sul metodo

Non è software, ma è la parte più riutilizzabile.

1. **Un difetto vago va localizzato con una misura prima di inseguirlo.** "C'è qualche artefatto qua
   e là" è diventato trattabile solo dopo aver scritto un controllo che stampasse il minuto e il
   secondo.
2. **Un giudizio all'ascolto va riconfermato a mente fresca.** Un difetto segnalato la sera è sparito
   al riascolto del mattino — dopo due giri di diagnosi costruiti sopra.
3. **Se la differenza è marginale, A/B alla cieca.** Due catene che sembravano diverse sono risultate
   indistinguibili in quattro confronti su quattro.
4. **Una misura che migliora non è un motivo sufficiente.** La selezione delle prese per altezza
   portava lo scarto dal bersaglio da 2,03 a 1,33 semitoni e raddoppiava il tempo di sintesi:
   all'ascolto non cambiava nulla, ed è stata scartata.
5. **Ogni difetto che sfugge è prima di tutto un buco nei controlli.** Ognuna delle segnalazioni di
   Mauro sul montaggio finale ha rivelato una misura assente, o fatta nel posto sbagliato.

---

## 9. Costi, in tempo macchina

| | |
|---|---|
| sintesi di una pagina (~11 balloon) | ~50 s, con i ritentativi |
| sintesi dell'intera storia (131 clip) | ~11 minuti |
| montaggio di una pagina | pochi secondi, solo CPU |
| rendering delle 12 pagine dal PDF | ~20 s |
| stack di una pagina da video (50 fotogrammi) | ~15 s |
| pesi del modello su disco | 3,0 GB |

---

## 10. Licenze e uso

Verificate il 2026-09-16. **Distinzione che conta: il codice e i pesi di un modello hanno licenze
diverse**, e quella dei pesi è l'unica che decide cosa puoi farci.

| componente | licenza | conseguenza |
|---|---|---|
| `chatterbox-tts` (codice) | MIT, Resemble AI 2025 | libero, anche commerciale |
| **pesi Chatterbox Multilingual** | **MIT** | uso commerciale permesso, nessun obbligo di attribuzione |
| `resemble-perth` (watermarker) | MIT | — |
| `coqui-tts` (libreria) | MPL-2.0 | libera |
| **pesi XTTS-v2** | **CPML** | *solo uso non commerciale* — motivo in più per cui va bene averlo abbandonato |
| PyTorch | BSD-3-Clause | — |
| ffmpeg, ImageMagick, poppler | LGPL/GPL, ImageMagick, GPL | usati come strumenti esterni, non incorporati |

⚠️ **Ogni file audio generato contiene un watermark.** Chatterbox incorpora *Perth*, un watermarker
neurale di Resemble AI: impercettibile, ma progettato per sopravvivere alla compressione MP3,
all'editing e alle manipolazioni comuni. Non è un difetto — è una scelta del modello — ma va saputo:
l'audio prodotto è **riconoscibile come sintetico** da chi sa cercarlo.

⚠️ **Il fumetto è protetto da copyright** (Disney / Panini). `storia.mp3` è un'opera derivata da una
pubblicazione protetta: per un uso personale è un conto, distribuirla è tutt'altro. Il fatto che i
modelli permettano l'uso commerciale **non dice niente** sui diritti del materiale di partenza.

E la voce clonata è quella di una persona reale, che ha dato il suo consenso perché è la stessa che
ha costruito il progetto. Su una voce altrui servirebbe il suo.

---

## 11. Quello che il PoC non ha dimostrato

Un PoC dichiarato chiuso senza questo elenco è un PoC che si racconta meglio di com'è.

### La trascrizione è tutta manuale, ed è la voce di costo principale
I 131 balloon delle 12 pagine sono stati letti e trascritti a mano, uno per uno, in sessione. La
sintesi dell'intera storia sono **undici minuti di GPU**; la trascrizione sono state **ore**. Per un
secondo fumetto il conto ricomincia da zero.

È il problema aperto più grosso, e il PoC lo lascia intatto: l'esperimento col video ha riguardato
l'*acquisizione* delle pagine, non l'automazione della lettura. E la parte difficile non è
riconoscere le lettere — quella la farebbe un OCR — ma **l'ordine dei balloon e l'attribuzione dei
personaggi**, che dipendono dalla coda del balloon, dal colore, dalla posizione nella vignetta e da
chi è inquadrato.

### Una sola voce, una sola lingua, un solo fumetto
Tutto è tarato su `voce_mauro4.flac` e sull'italiano. `REF_PITCH` è misurato su quella
registrazione; le soglie di `check_clips.py` sulla distribuzione di queste 131 clip; i preset dei
personaggi su questo cast. Quanto di questo regge su un'altra voce o un'altra storia **non è stato
provato**.

### Il cast non scala per altezza
Sette personaggi sono già oltre quello che il modello sa distinguere: la variabilità di Chatterbox
fra una battuta e l'altra (6-8 semitoni) è più grande degli scostamenti voluti. Oggi li distinguono
`exaggeration`/`cfg_weight` e il testo. Con dodici personaggi non si sa cosa succede.

### Il controllo qualità automatico non giudica la qualità
`check_clips.py` trova clip mute, troncate, ripetute, in clipping. **Non sa dire se una lettura è
bella**, se l'intonazione è giusta per la battuta, se un personaggio è riconoscibile. Ogni volta che
il montaggio è stato giudicato, a giudicarlo è stato un orecchio umano — ed è così che sono emersi i
difetti che le misure non vedevano.

### Nessuna sincronizzazione con la pagina
L'uscita è un file audio. Un'applicazione che segua la lettura evidenziando il balloon in corso
avrebbe bisogno delle **coordinate** di ogni balloon, che oggi non vengono registrate: lo script
tiene il numero di vignetta, non la posizione.

### Nessuna prova di robustezza
Un fumetto con lettering diverso, pagine a colori invertiti, vignette senza bordi, testo dentro il
disegno, o una storia con voce narrante fuori campo continua: niente di tutto questo è stato provato.

---

## 12. Stato al momento della chiusura

- **`poc/out/storia.mp3`** — 6 minuti e 35 secondi, 131 balloon, 12 pagine. Ascoltato e approvato.
- `poc/out/pagine/pNN.mp3` — le 12 pagine singole.
- `check_clips.py` non segnala nulla su nessuna clip.
- L'ambiente si ricostruisce con `poc/setup.sh`; la pipeline si rilancia con `poc/run_poc.sh`.
- L'unica cosa non rigenerabile è in `voice/`, e ha il suo README.
