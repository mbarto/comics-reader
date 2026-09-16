# ✅ POC CHIUSO — 2026-09-16

**`poc/out/storia.mp3`, 6 minuti e 35 secondi, 131 balloon, 12 pagine. Ascoltato e approvato da
Mauro.** Le pagine singole sono in `poc/out/pagine/`. `check_clips.py` non segnala nulla.

Il documento tecnico — tecnologie, architettura, licenze e **quello che il PoC non ha dimostrato** —
è in **`TECNOLOGIE.md`**. Questo file resta il diario: perché ogni scelta è stata fatta, e cosa è
stato provato e scartato lungo la strada.

**Chiusura, cosa è stato sistemato:**
- `poc/setup.sh` ricostruisce da zero i due ambienti e scarica i 3 GB di pesi, con dentro tutte le
  contromisure alle trappole di rete: prima non esisteva, e `synthesize_chatterbox.py` rimandava a
  uno script di download che non c'era più;
- `voice/README.md` documenta l'unica cosa non rigenerabile del progetto, con le impronte SHA-256 e
  la dipendenza nascosta di `REF_PITCH` da quella registrazione;
- licenze verificate: pesi Chatterbox **MIT** (uso commerciale permesso), ma ogni file generato porta
  un **watermark neurale**, e il fumetto è comunque protetto da copyright;
- tolti 45 MB di montaggi superati e archiviata la sintesi XTTS in `poc/archivio/`.

**Se si riprende**, il problema aperto più grosso è la **trascrizione manuale**: 131 balloon letti a
mano contro 11 minuti di GPU per sintetizzarli tutti. È lì che va il prossimo lavoro, e non è un
problema di OCR ma di ordine dei balloon e attribuzione dei personaggi.

---

# Comics Reader — Piano del Proof of Concept

**Obiettivo del PoC:** un file audio di ~1 minuto in cui la voce di Mauro legge la pagina 41 di
*Paperino Park Ranger* (Topolino), balloon dopo balloon, con inflessioni diverse per narratore e
personaggi.

Ultimo aggiornamento: 2026-09-16

---

## 1. Artefatti di partenza

### `pages/paperino-park-ranger.pdf`
- Scansione pura prodotta con gscan2pdf, 7 pagine PDF, JPEG 2550×3507 a 300 dpi.
- **Nessun livello di testo** (`pdftotext` restituisce 7 byte): tutto il testo va letto dalle immagini.
- Layout **non uniforme**:
  | Pagina PDF | Contenuto | Orientamento |
  |---|---|---|
  | 1 | pagina singola, Topolino p. 41, inizio storia "Uack!" | dritta, con accanto una pagina di altro articolo |
  | 2–6 | doppie pagine (p. 42-43 … p. 50-51) | **ruotate di 90°** |
  | 7 | pagina finale + pagina di altro articolo | dritta |
- ~12 pagine di storia in totale, stimati 250–350 balloon.
- Testo italiano tutto maiuscolo, ben leggibile. Tre tipi di contenuto: didascalie narrative
  (riquadri gialli), dialoghi, onomatopee disegnate ("SNORT!", "SBADABAM!", "SGLOOOP!").

### `voice/voce_mauro2.flac` — campione vocale di riferimento
Registrazione del 2026-09-15 che ha **sostituito** il primo campione da 11,6 s.

| Parametro | Valore | Giudizio |
|---|---|---|
| Durata | 62,4 s | ✅ ~54 s di parlato effettivo, 15 pause naturali da 0,35–0,9 s |
| Picco | −10,7 dB | ✅ nessun clipping (flat factor 0) |
| Livello medio | −32 dB RMS | ⚠️ basso: va normalizzato (headroom sufficiente) |
| Rumore di fondo | −55 dB nelle pause | ✅ SNR ~25 dB RMS / ~44 dB di picco |
| Canali | stereo vero (L≠R) | ℹ️ downmix in mono; il canale destro è ~1,4 dB più forte |
| Banda | nulla sopra 16 kHz | ℹ️ irrilevante, XTTS lavora a 22 kHz |
| DC offset | −0,00003 | ✅ trascurabile |

**Conseguenza sul piano:** con 54 s di parlato si usano **3 finestre di riferimento da ~10 s**
invece di un singolo spezzone; XTTS-v2 media il condizionamento su più campioni e il clone risulta
più fedele.

⚠️ *Correzione rispetto alla valutazione iniziale:* avevo scritto che il denoise non serviva,
guardando il rumore in valore assoluto (−55 dB). Sbagliato: quello che conta è il **rapporto** col
parlato, che la normalizzazione non cambia, e XTTS clona le condizioni di registrazione insieme al
timbro. Il denoise serve eccome — vedi il giro 1 della Fase 6.

---

## 2. Decisioni prese

| Componente | Scelta | Motivazione |
|---|---|---|
| Cloning + TTS | **XTTS-v2** (pacchetto `coqui-tts`), locale | Italiano nativo, zero-shot, gira su GPU locale, gratis, la voce non lascia la macchina. Licenza CPML: uso personale ok |
| Estrazione testo | **Lettura diretta delle pagine da parte di Claude** in sessione | Ordine dei balloon e attribuzione dei personaggi corretti al 100%. Non automatizzabile, ma per il PoC è la scelta migliore. (Alternativa futura: API Claude vision nella pipeline) |
| Resa audio | **Voce unica + regia sui personaggi** | Sempre la voce di Mauro, con pitch/velocità/effetti differenziati per narratore e personaggi |
| Perimetro PoC | **Solo pagina 41**, onomatopee **lette** | Pagina dritta e pulita, ~10 balloon, ~1 minuto di audio |

### Ambiente
- Hardware: RTX 4070 Laptop 8 GB (XTTS-v2 ne usa ~2,5 GB), 20 core, 62 GB RAM, 567 GB liberi.
- `python3-venv`/`ensurepip` **non sono installati** sul sistema: l'ambiente viene creato con **uv**
  (`~/.local/bin/uv`, installato con `pip3 install --user uv`) per evitare un `sudo apt install`.
  L'ambiente risultante è un venv standard, utilizzabile anche con pip normale.

---

## 3. Fasi

### Fase 0 — Ambiente ✅ fatta
- [x] `poc/.venv` creato con `uv venv --python 3.10`
- [x] PyTorch 2.5.1+cu121 + torchaudio — CUDA attiva sulla RTX 4070
- [x] `coqui-tts` 0.27.5
- [x] `transformers` bloccato a 4.57.6
- [x] Modello XTTS-v2 scaricato in `~/.local/share/tts` (1,9 GB)

**Trappole incontrate, da ricordare se si rifà l'ambiente:**
- `uv` va lanciato con `UV_HTTP_TIMEOUT=90` e `UV_CONCURRENT_DOWNLOADS=4`: con i valori di
  default multiplexa decine di download su un'unica connessione HTTP/2 verso il CDN di PyPI e
  quella connessione si pianta senza errore, restando appesa fino al timeout.
- `coqui-tts` dichiara `transformers>=4.57` **senza limite superiore**: uv installa la 5.x, che
  ha rimosso `isin_mps_friendly`, e l'import di `TTS` esplode. Va installato
  `transformers>=4.57,<5`.

Ingombro su disco stimato: ~6 GB.

### Fase 1 — Preparazione della voce di riferimento ✅ fatta
Script: `poc/prepare_voice.sh`. Da `voice/voce_mauro2.flac` a `poc/voice_ref/*.wav`:
- downmix in mono, `highpass=70` + `afftdn` (denoise **prima** della normalizzazione, altrimenti
  lavorerebbe su un segnale già amplificato), normalizzazione EBU R128 a −20 LUFS, 22,05 kHz
- taglio di 6 finestre candidate sui confini delle pause, così nessuna parola viene troncata
- misura dell'SNR di ognuna e selezione automatica delle **3 più pulite** (`KEEP=3`)

È il passaggio che più incide sulla somiglianza del clone.

Risultato: `ref_1..3.wav` (10,9 / 10,5 / 8,5 s, SNR 35,9 / 34,6 / 29,1 dB) + `ref_full.wav`.
Le tre finestre scartate stavano a 24,4 / 23,8 / 23,0 dB: tenerle avrebbe peggiorato anche le altre,
perché il condizionamento di XTTS è una media.

### Fase 2 — Script della pagina ✅ fatta
Render di pagina 1 a 300 dpi, poi `poc/script.json` con una voce per balloon:

```json
{ "seq": 3, "panel": 2, "type": "dialogue", "speaker": "ranger_matt",
  "text": "Caffè?", "fx": null }
```

- `type` ∈ `title` | `credits` | `caption` (didascalie gialle) | `dialogue` | `sfx`
- `text` è il testo come stampato, `text_tts` la resa fonetica passata a XTTS quando la grafia
  originale verrebbe pronunciata male ("UACK!" → "Uàc!", "HRMPF!" → "Hmmpf!")

Trascritti 10 elementi: titolo + crediti, 2 didascalie narrative, 4 battute di dialogo,
2 grugniti di Paperino, 1 voce dalla radio. Personaggi: `narratore`, `matt` (il ranger anziano),
`paperino`, `hilde_radio`.

### Fase 3 — Regia dei personaggi ✅ fatta (`poc/voices.json`)
Tutti i preset derivano dallo stesso timbro clonato:

| Speaker | Trattamento |
|---|---|
| `narratore` | speed 0,94, `highpass=100` + presenza +2,5 dB a 3 kHz |
| `paperino` | speed 1,02, pitch +6%, `highpass=110` + presenza +4 dB a 3 kHz |
| `matt` | speed 0,97, pitch −3%, `highpass=100` + presenza +3,5 dB a 3 kHz |
| `hilde_radio` | pitch +12% **+ filtro radio** (passa-banda 300–3000 Hz, compressore, saturazione `tanh` a 1,5 — ridotta da 2,2 perché alzava troppo il fondo) |
| `sfx` (override di tipo) | +1,5 dB e compressione: grugniti più energici |

XTTS espone solo `speed`: il pitch si ottiene in post con `rubberband=formant=preserved`, che
sposta l'altezza senza alterare la durata né far suonare la voce "da cartone animato".

**Divisione dei compiti tra i due script:** `synthesize.py` applica solo `speed` (è un parametro
della sintesi), mentre pitch, filtri e volume li applica `assemble.py`. Così ritarare la regia
costa pochi secondi di ffmpeg invece di una rigenerazione sulla GPU.

### Fase 4 — Sintesi (`poc/synthesize.py`) ✅ fatta
- Usa l'API di basso livello `Xtts` invece di `TTS.api`: i latenti del parlante si calcolano una
  volta sola sui 3 riferimenti e si riusano per tutte le clip — più veloce e timbro più costante.
- Una clip WAV per balloon in `poc/clips/` (`--only SEQ` rigenera solo quella venuta male).
- Seed fisso (1234) per risultati riproducibili.

**Due difetti di XTTS emersi alla prima generazione, e come sono stati risolti:**
1. *Ripetizioni sui testi brevi* — "Hmmpf!" è uscito ripetuto quattro volte, 8,5 s invece di 1.
   Ora `speech_duration()` misura il parlato al netto dei silenzi e lo confronta con la lunghezza
   del testo; se eccede, la clip viene rigenerata con un altro seed (fino a `MAX_ATTEMPTS`=4) e si
   tiene la più breve.
2. *Vuoti interni* — sulle frasi con puntini di sospensione il modello inseriva silenzi di 3-5 s in
   mezzo alla battuta. `collapse_gaps()` accorcia a 260 ms ogni silenzio interno oltre i 350 ms,
   e `trim_silence()` toglie le code iniziali e finali, che falsavano il ritmo del montaggio.

### Fase 5 — Montaggio (`poc/assemble.py`) ✅ fatta
Regia clip per clip, poi concatenazione con pause calibrate:
- 900 ms dopo il titolo, 1,2 s dopo i crediti
- 350 ms tra balloon della stessa vignetta
- 700 ms tra vignette
- 1,2 s a fine pagina

Normalizzazione finale a −16 LUFS. Output: `poc/out/paperino_p41.wav` + `.mp3`.

### Fase 6 — Ascolto e taratura ✅ chiusa il 2026-09-16
Ascolto di Mauro e iterazione su somiglianza, velocità, pause, filtro radio.
Solo dopo ha senso estendere alle doppie pagine ruotate e al fumetto intero.

**Giro 1 — "l'audio ha molto rumore di fondo" (risolto).** SNR medio delle clip montate
passato da ~25 dB a **43,6 dB**. Tre cause, tutte corrette:
1. *Il riferimento*: XTTS clona le condizioni di registrazione insieme al timbro, quindi si
   porta dietro il fruscio. `prepare_voice.sh` ora fa `highpass=70` + `afftdn` **prima** della
   normalizzazione, e soprattutto genera 6 finestre candidate tenendo solo le 3 con SNR
   migliore: il condizionamento di XTTS è una media, quindi una finestra rumorosa peggiora
   anche le altre (la peggiore stava 13 dB sotto la migliore).
2. *La regia*: la saturazione `tanh` del filtro radio toglieva da sola 9,1 dB di SNR e i
   compressori delle onomatopee altri 4. Aggiunto uno stadio `cleanup` in `voices.json`
   (`highpass` + `afftdn` + expander) applicato **prima** dei filtri di carattere, e
   saturazione ridotta da 2,2 a 1,5.
3. *Prese rumorose occasionali*: con lo stesso riferimento e lo stesso testo XTTS ogni tanto
   genera una clip molto più sporca (la seq 9 stava a 22 dB contro i 35-45 delle altre).
   `synthesize.py` ora misura l'SNR di ogni presa e la rifà sotto i 30 dB (`MIN_SNR_DB`),
   scegliendo poi la meno rumorosa tra quelle senza loop.

**Giro 2 — "la voce di Paperino è poco chiara, meglio quella di Hilde" (risolto).**
Misurata la distribuzione spettrale per personaggio: nella banda 2-4 kHz, dove stanno le
consonanti e quindi l'intelligibilità, Hilde stava a −22,4 dB e Paperino a −28,5. Hilde suonava
più chiara *grazie* al suo filtro radio: il passa-banda 300-3000 Hz e il compressore le spostano
energia proprio lì. Applicato a Paperino lo stesso meccanismo senza l'effetto radio
(`highpass=110` per togliere i bassi che impastano, +4 dB a 3 kHz, compressore dolce) e abbassato
`speed` da 1,08 a 1,02, perché sopra 1,05 XTTS mangia le consonanti. Ora Paperino sta a −24,0 dB,
a 1,6 dB da Hilde.

**Giro 3 — stesso trattamento esteso a `matt` e `narratore`.** Presenza più moderata di
Paperino (+3,5 e +2,5 dB invece di +4), per non togliere a Matt il tono posato e per tenere
naturale il narratore, che è il filo conduttore del racconto. Le battute parlate ora stanno tra
−15 e −27 dB nella banda di presenza, contro −21/−34 di prima: la resa è molto più uniforme.

*Cautela sulla misura:* l'energia nella banda 2-4 kHz varia parecchio anche tra battute dello
stesso personaggio (il narratore andava da −21,4 a −32,3), perché dipende da quali suoni contiene
la frase. Il trattamento è quindi uniforme per personaggio, non tarato per centrare un numero.

Compressori ed EQ rialzano il fondo di 3-4 dB, quindi l'**expander è stato spostato in fondo alla
catena** (`cleanup.post_filters` invece di `cleanup.filters`): così abbassa anche il rumore che
loro hanno appena tirato su. SNR medio recuperato da 37,9 a **40,5 dB**, peggiore 30,6 dB.

**Giro 4 — dereverberazione: TENTATA E ANNULLATA.**
Diagnosi corretta, esito peggiore. Il rimbombo era davvero il riverbero della stanza, che XTTS
clona insieme al timbro e anzi accentua (registrazione originale: −20 dB in 220 ms; clip generate:
285-340 ms). Sono stati fatti due interventi:
1. dereverberazione WPE del riferimento (`poc/dereverb.py`, `nara-wpe`, `taps=20`);
2. rimozione dei compressori dai personaggi, che rilasciando risollevavano le code.

Tutte le misure sono migliorate — SNR 40,5 → 44,7 dB, presenza −25,0 → −19,3 dB, decadimento
248 → 188 ms — **ma all'ascolto il risultato era peggiore** ("era decisamente meglio prima").
A 20 tap il WPE toglie riverbero ma anche corpo: la voce si assottiglia e suona più artificiale,
e i compressori davano una consistenza che le misure non registrano.

**Lezione, valida per i prossimi giri:** SNR, banda di presenza e decadimento sono utili per
*diagnosticare* un difetto che l'ascolto ha già segnalato, e per verificare che un intervento
faccia quello che dice. Non sono un criterio di qualità: su naturalezza e corpo della voce
decide solo l'orecchio di Mauro.

**Stato ripristinato** (identico al giro 3, verificato: stessi riferimenti, SNR medio 40,5 dB,
uscita di 40,6 s). La dereverberazione non è stata cancellata ma resa opzionale e spenta di
default, perché tornerà utile se la registrazione verrà rifatta:

    DEREVERB=1 ./poc/prepare_voice.sh

**Se il rimbombo dà ancora fastidio**, la strada efficace non è software: rifare il minuto di
registrazione in un ambiente più sordo (dentro un armadio di vestiti, o con una coperta spessa
alle spalle e ai lati). Con una sorgente asciutta si parte già puliti e non serve togliere nulla.

**Misure attuali:** SNR medio 40,5 dB · presenza −25,0 dB · decadimento 248 ms.

**Giro 5 — l'ascolto di `_dereverb.wav` rimette in discussione il giro 4.**
Mauro ha ascoltato il file intermedio `voice_ref/_dereverb.wav` e ha notato "riverbero migliore ma
molto rumore di fondo". Quel file è l'uscita grezza di WPE, **prima** del denoise che la pipeline
gli applica comunque: misurato dopo `highpass` + `afftdn` + `loudnorm` il suo SNR sale da 38,6 a
**45,6 dB**, meglio dei 40,6 della sorgente non dereverberata, mantenendo il decadimento a 120 ms
invece di 240. (WPE alza davvero il fondo, perché sottrae la componente riverberante correlata e
lascia il rumore non correlato: per questo va sempre seguito dal denoise.)

**Errore di metodo da non ripetere:** nel giro 4 erano state cambiate *due* cose insieme —
dereverberazione e rimozione dei compressori. Alla bocciatura all'ascolto sono state annullate
entrambe, senza sapere quale delle due fosse responsabile. Un intervento per giro.

**A/B costruito** per isolare la variabile (`poc/out/paperino_p41_dereverb.mp3` = la versione
approvata + sola dereverberazione, compressori mantenuti):

| | `paperino_p41` (predefinita) | `paperino_p41_dereverb` |
|---|---|---|
| SNR medio per clip | **40,5 dB** | 34,4 dB |
| Presenza 2-4 kHz | −25,0 dB | **−18,5 dB** |
| Decadimento (file montato) | 250 ms | **150 ms** |

Dereverberazione e compressori lavorano l'uno contro l'altro: il compressore, rilasciando,
rialza sia il rumore che WPE ha amplificato sia le code che WPE aveva tolto. Se la versione
dereverberata convince all'ascolto ma il fruscio dà fastidio, il passo successivo è accorciare le
release dei compressori (a 80-90 ms l'SNR risale a ~40 dB tenendo il decadimento a ~230 ms).

⚠️ *Nota sulla misura:* `measure.py` va usato sulle singole clip, non sul file montato: le pause
sono silenzio digitale e fanno risultare un SNR assurdo (200+ dB). Sul file montato ha senso solo
il decadimento.

---

## Giro 6 — nuovo microfono (`voice/voce_mauro3.flac`)

Mauro ha rifatto la registrazione con un altro microfono. **Risolve alla radice i due problemi dei
giri 1-5**, che erano proprio quelli non recuperabili in post:

| sulla sorgente grezza | `voce_mauro2` | `voce_mauro3` |
|---|---|---|
| SNR | 33,7 dB | **47,2 dB** (+13,5) |
| Decadimento (riverbero) | 190 ms | **100 ms** (dimezzato) |
| Picco | −11,1 dB | −5,5 dB, 0 campioni in clipping |
| Parlato utile | ~54 s | ~27 s (bastano: XTTS usa max 30 s) |

I 100 ms di decadimento sono già meglio di quanto WPE otteneva sulla registrazione vecchia, ma
senza assottigliare la voce, perché non c'è niente da sottrarre. **La dereverberazione non serve
più.**

**Il contro: il microfono nuovo è molto più scuro.**

```
banda         50-120  120-300  300-800  800-2k   2k-4k   4k-8k
delta mic3     -3,7     +0,8     +2,9    -3,3    -9,0   -14,7  dB
```

L'energia si concentra tra 120 e 800 Hz. Sulle clip generate la differenza arriva a −12,5 dB.
Compensato con uno stadio nuovo **`source_eq`** in `voices.json` (shelf `treble=g=12:f=900`),
applicato dopo la pulizia e prima della regia, perché corregge il *microfono*, non il personaggio.
Con una sorgente dal timbro equilibrato va semplicemente svuotato.

**Esito dopo compensazione** (clip montate):

| | mic2 (approvata) | mic3 + compensazione |
|---|---|---|
| SNR medio per clip | 40,5 dB | 36,8 dB |
| Presenza 2-4 kHz | −25,0 dB | **−21,8 dB** |
| Decadimento (file montato) | 250 ms | **120 ms** |

I 3,7 dB di SNR persi sono il prezzo dello shelf da +12 dB, che alza anche il fruscio. Restano
comunque 13 dB di margine guadagnati col microfono.

**Da decidere all'ascolto:** `poc/out/paperino_p41_mic2.mp3` contro `paperino_p41_mic3.mp3`.
La pipeline è già configurata per il microfono nuovo; per tornare al vecchio basta
`VOICE=voice/voce_mauro2.flac ./poc/prepare_voice.sh` e svuotare `source_eq.filters`.

**Se si potesse rifare una terza registrazione**, la cosa da cambiare è solo la posizione del
microfono nuovo (puntato verso la bocca, senza nulla davanti, e verificando che non abbia un
filtro "voce" o un taglio degli alti attivo): pulizia e assenza di riverbero sono già ottime, e
senza il buco sugli alti non servirebbe nemmeno lo shelf da +12 dB.

### Altri miglioramenti di questo giro
- `prepare_voice.sh` **non ha più le finestre cablate**: le ricava dalle pause vere con
  `silencedetect`, con soglia di durata adattiva (scende da 7 s finché non trova abbastanza
  finestre). Cambiare registrazione ora non richiede di ritarare niente.
- La sorgente si sceglie con `VOICE=...`; il default è `voce_mauro3.flac`.
- Trappola incontrata: `python - <<'PY'` legge il **programma** da stdin, quindi lo script non può
  ricevere anche i dati in pipe — vanno passati come file.

---

## Giro 7 — `voice/voce_mauro4.flac`: la registrazione buona

Terza registrazione, stesso microfono nuovo ma posizionato meglio. **È la migliore delle tre** e
diventa la sorgente predefinita della pipeline.

| sulla sorgente grezza | `mauro2` | `mauro3` | `mauro4` |
|---|---|---|---|
| SNR | 33,7 dB | 47,2 dB | **51,8 dB** |
| Decadimento (riverbero) | 190 ms | 100 ms | **100 ms** |
| Presenza 2-4 kHz | −24,8 dB | −33,8 dB | −28,7 dB |
| Parlato utile | ~54 s | ~27 s | ~25 s |

Rispetto a `mauro3` guadagna **+5 dB su tutta la gamma sopra gli 800 Hz** e perde 7,4 dB sotto i
120 (meno effetto prossimità). Le finestre di riferimento selezionate hanno SNR **64,2 / 56,9 /
50,4 dB**, contro 35,9 / 34,6 / 29,1 di `mauro2`.

`source_eq` ritarato di conseguenza: da `treble=g=12:f=900` a **`treble=g=6:f=1800`**, metà del
guadagno. Tarato confrontando il profilo spettrale con quello di `mauro2` su tre bande e scegliendo
lo scarto minimo; scartato `g=8`, che centrava meglio i 4-8 kHz ma sparava +4 dB sui 2-4 kHz con
rischio di durezza.

**Risultato sul file montato:** presenza **−18,1 dB**, identica a quella della versione approvata,
con decadimento **135 ms invece di 250**. Cioè lo stesso equilibrio timbrico che era piaciuto, con
metà del riverbero.

⚠️ **Un dato in controtendenza da verificare all'ascolto:** l'SNR medio delle clip *dopo la regia*
è 34,2 dB, sotto i 40,5 della versione `mic2`, nonostante la sorgente sia 18 dB più pulita. Le
prese grezze sono tutte a 32-48 dB, quindi il calo arriva dalla catena di regia (shelf + EQ di
presenza), non dalla sintesi. Se all'ascolto il fruscio non si sente, il numero è ininfluente;
se si sente, si abbassa `source_eq` a `g=4` e si recupera.

**File di confronto** in `poc/out/`: `paperino_p41_mic2.mp3` (la vecchia approvata) e `_mic4.mp3`.
`paperino_p41.mp3` = uscita corrente della pipeline = mic4.

**Esito:** *"molto molto meglio l'ultima versione"*. `voce_mauro4` confermata come sorgente.

---

## Giro 8 — "la voce sembra un po' robotica, in tutte le registrazioni" (in corso)

Il fatto che riguardi *tutte* le voci scarta subito `rubberband`: il narratore ha `pitch` 1.0 e
quindi non ci passa nemmeno. Restano gli stadi comuni a tutti i personaggi. Tre sospettati, e per
ognuno una variante che cambia **solo quello** — la lezione del giro 4 è di non muovere due cose
insieme:

| variante | cosa cambia | perché è sospettata |
|---|---|---|
| **B** `_B_senza_denoise` | `cleanup` ridotto al solo `highpass`: via `afftdn` e l'expander | `afftdn` produce il tipico "musical noise" metallico. Era stato messo quando la sorgente aveva 33 dB di SNR: ora ne ha 51,8, quindi lavora su un problema che non esiste più e lascia solo artefatti |
| **C** `_C_velocita_naturale` | `speed` = 1.0 per tutti (era 0,94-1,02) | il parametro `speed` di XTTS agisce sui latenti: rallentare il narratore a 0,94 gli stira le vocali |
| **D** `_D_senza_giunte` | disattivato `collapse_gaps` in `synthesize.py` | taglia i silenzi interni oltre 350 ms, quindi fa una giunta netta a ogni pausa dentro la battuta. Serviva contro i vuoti di 3-5 s del giro 1, che con la sorgente pulita non si presentano più (D dura 46,2 s contro 41,8: i vuoti che rimette sono tutti brevi) |

Le misure oggettive non distinguono le quattro versioni (presenza −18,1 / −18,1 / −18,8 / −18,3;
decadimento 135 / 130 / 120 / 125 ms): il difetto è di naturalezza, e lì i numeri non arrivano.
Decide l'ascolto.

**Esito: nessuna delle tre cambia niente all'ascolto.** Il difetto non è nella catena di
post-produzione ma nella generazione. Le tre varianti restano in `poc/out/` come `_B_`, `_C_`,
`_D_`; si possono cancellare.

### Diagnosi: XTTS genera la voce troppo acuta

Nuovo strumento `poc/intonation.py` (F0 per autocorrelazione, escursione in semitoni). Ha scartato
subito l'ipotesi della prosodia piatta — le clip generate hanno escursione 4-5 semitoni, pari o
superiore al riferimento — ma ha rivelato altro:

| | F0 mediana |
|---|---|
| Voce di Mauro (`voce_mauro4`) | **122 Hz** |
| Finestre di riferimento | 117-146 Hz |
| Clip generate da XTTS | **145-176 Hz** |

Il clone parla **4-6 semitoni sopra la voce reale**. Il narratore, che nella regia ha `pitch` 1.0 e
quindi non passa nemmeno da `rubberband`, esce a 176 Hz. Confermato da due metodi indipendenti
(autocorrelazione e cepstrum). È una combinazione innaturale — formanti di una voce bassa, altezza
di una più acuta — ed è un candidato forte per l'effetto "robotico".

Cambiare riferimento sposta poco: con `ref_full` intera o con la finestra più grave si scende solo
da 176 a 162 Hz. XTTS alza per conto suo, quindi la correzione va fatta a valle.

### Correzione automatica dell'intonazione

`voices.json` ha ora **`pitch_target_hz: 122`** e `assemble.py` misura l'F0 di ogni clip e la
riporta a quel valore con `rubberband`. Due conseguenze:
- il `pitch` di ogni personaggio diventa uno scostamento **dalla voce reale di Mauro** (paperino
  1,06 = 6% sopra la sua voce), non un fattore applicato a quello che ha generato XTTS;
- la correzione è per clip, quindi assorbe anche la variabilità tra una presa e l'altra.

C'è un limite di sicurezza tra 0,6 e 1,6: su una clip corta la stima dell'F0 può sbagliare di
un'ottava, e senza limite produrrebbe una trasposizione assurda.

Verificato che la trasposizione non appiattisca l'intonazione: il range 10-90% resta stabile
(11,99 → 10,90 semitoni scendendo fino a −6,3 semitoni). Sale solo la deviazione standard, che è
un artefatto della stima sull'audio trasposto, non un cambiamento del contorno.

**Risultato:** `poc/out/paperino_p41_E_intonazione.mp3`, F0 mediana **134 Hz** contro i 161 di
prima, con i 122 di Mauro come bersaglio. Da giudicare all'ascolto.

**Esito:** *"il timbro è migliorato, ma il robotico resta"*. La correzione di intonazione si tiene.

### Il difetto è **metallico**, non robotico

Precisazione di Mauro che cambia la diagnosi: metallico indica artefatti spettrali, non prosodia.
Fa notare una correlazione finora ignorata — la lamentela nasce con `mic4`, cioè quando è stato
introdotto `source_eq`. Lo shelf da +6 dB sopra 1,8 kHz **si somma** all'EQ di presenza (+2,5 dB a
3 kHz): quasi +9 dB proprio nella banda dove vivono gli artefatti del vocoder HiFi-GAN di XTTS e il
"musical noise" di `afftdn`.

Tutti stadi di post-produzione, quindi isolabili sulla stessa clip senza risintetizzare. Otto
versioni della didascalia d'apertura in `poc/out/prova_metallico/`:

| | cosa prova |
|---|---|
| `A_catena_attuale` | il riferimento da cui partire |
| `B_senza_shelf` | se il colpevole è `source_eq` |
| `C_shelf_dimezzato` | se +3 dB bastano (compromesso) |
| `D_senza_denoise` | se è il musical noise di `afftdn` |
| `E_senza_shelf_ne_denoise` | i due insieme |
| `F_solo_intonazione` | catena minima: solo highpass e trasposizione |
| `G_grezza_xtts` | **uscita cruda del modello, nessun trattamento** |
| `H_intonazione_altro_metodo` | trasposizione con `asetrate` invece di `rubberband` |

**Esito: `G_grezza_xtts` è la migliore.** L'uscita cruda del modello è pulita — **il metallico lo
introduceva la catena di post-produzione**, e il colpevole principale è `rubberband`: un phase
vocoder che trasporta di −6 semitoni lascia artefatti che l'orecchio riconosce subito. Restava però
il problema che l'aveva richiesto: il tono troppo alto.

### Giro 9 — la correzione dell'intonazione si sposta sul riferimento

Idea: invece di trasporre l'**uscita**, trasporre il **riferimento**. L'audio finale lo sintetizza
comunque il vocoder da zero, quindi resta pulito. Verificato che il trasferimento funzioni:

| riferimento trasposto | F0 riferimento | F0 uscita |
|---|---|---|
| x1,00 | 117 Hz | 176 Hz |
| x0,88 | 103 Hz | 160 Hz |
| x0,80 |  93 Hz | 133 Hz |
| **x0,79** | — | **mediana 123 Hz su 4 frasi** (113/132/141/115) |
| x0,78 |  91 Hz | 110 Hz |

La risposta **non è lineare** — tra 0,80 e 0,78 l'uscita salta di 23 Hz, XTTS sembra avere registri
discreti — quindi `REF_PITCH` in `prepare_voice.sh` va ritarato con `poc/intonation.py` se si cambia
registrazione.

**Catena ridotta al minimo**, ora che la sorgente è pulita e il grosso della correzione è a monte:
- `cleanup`: solo `highpass=70`. Via `afftdn` (con 51,8 dB di SNR non ha più rumore da togliere e
  lascia solo musical noise) e via l'expander.
- `source_eq`: da +6 a **+3 dB**. Sommato all'EQ di presenza faceva quasi +9 dB proprio dove vivono
  gli artefatti del vocoder.
- `pitch_target_hz`: resta solo come ritocco fine, con **zona morta di mezzo semitono e limite a
  ±2 semitoni**. Le correzioni effettive vanno ora da 0 a 2 semitoni, contro i −6,3 di prima.

**Risultato** (`paperino_p41_F_catena_minima.mp3`): F0 mediana **124 Hz** contro i 122 di Mauro,
escursione **4,44 semitoni** contro i suoi 4,30. Cioè la sua altezza e la sua espressività.

Generata anche `paperino_p41_G_zero_trasposizioni.mp3` (`pitch_target_hz: 0`), senza **nessuna**
trasposizione a valle: F0 115 Hz, massima pulizia possibile, al prezzo di 4 semitoni di variabilità
fra una battuta e l'altra.

### Da decidere all'ascolto
`_F_catena_minima` contro `_G_zero_trasposizioni`: se `G` suona più pulita e la variabilità di
altezza non dà fastidio, si mette `pitch_target_hz: 0` e la catena a valle resta praticamente vuota.

**Esito: il metallico resta anche in `G`.** Era il vocoder di XTTS-v2, non la catena.

---

## Giro 10 — cambio di modello: Chatterbox Multilingual ✅

**Chatterbox Multilingual** (Resemble AI, 2025) al posto di XTTS-v2 (2023). Stesso contratto:
`poc/synthesize_chatterbox.py` scrive le clip con gli stessi nomi, quindi regia e montaggio
restano invariati. Gira nel venv separato `poc/.venv-chatterbox` (pretende torch 2.6 e
transformers 5.x, incompatibili con coqui-tts).

**Esito all'ascolto: il metallico è sparito.** Provate tre impostazioni sulla stessa frase;
scelta la **B** (`exaggeration` 0,7 · `cfg_weight` 0,4).

| | Chatterbox | XTTS-v2 |
|---|---|---|
| SNR clip grezza | 46-54 dB | 30,5 dB |
| Escursione intonazione | 4,2-4,7 st | 3,14 st |
| Timbro | pulito | metallico |

L'escursione coincide con quella di Mauro (4,30 st), mentre XTTS appiattiva a 3,14.

### Intonazione e personaggi spostati dentro il modello
Chatterbox genera a 140 Hz contro i 122 di Mauro: deriva molto più contenuta di XTTS (che stava a
176) e **quasi lineare**, senza i salti a scalino. Misurata su tre frasi: rif x1,00 → 140 Hz,
x0,92 → 126, x0,86 → 118. Scelto **`REF_PITCH = 0,89`**.

Visto quanto imparato nei giri 8-9, la differenziazione dei personaggi è stata portata **dentro la
generazione** invece che nella post-produzione:
- ogni personaggio riceve un **riferimento intonato alla sua altezza** (`REF_PITCH × pitch`);
- il carattere lo danno i parametri del modello: `narratore` 0,7/0,4 · `matt` 0,55/0,5 (posato) ·
  `paperino` 0,85/0,35 (scattante) · `hilde_radio` 0,7/0,4 più il filtro radio;
- `voices.json` ha ora `pitch_handled_upstream: true`, che fa saltare ad `assemble.py` sia il
  `pitch` sia la correzione su `pitch_target_hz`. **A valle non si traspone più nulla.**

⚠️ **Limite emerso:** la variabilità di Chatterbox da una battuta all'altra (±2-3 semitoni) è
maggiore degli scostamenti voluti fra personaggi (±1 semitono), quindi le altezze si sovrappongono
— in alcune clip Paperino esce più grave di Matt. La distinzione fra personaggi ora poggia
soprattutto su `exaggeration`/`cfg_weight`, non sull'altezza. Se serve più stacco, la strada è
allargare gli scostamenti di `pitch` oltre il ±6% attuale.

**Risultato:** `poc/out/paperino_p41_chatterbox.mp3` (39,3 s), F0 mediana **132 Hz** contro i 161
della versione XTTS, con Mauro a 122.

### Nota sull'ambiente: la rete
Il collo di bottiglia dell'intero giro è stato il download. Né uv, né pip, né `huggingface_hub`
sanno **riprendere** un trasferimento interrotto, e su questa connessione i trasferimenti si
impiantano regolarmente a metà: ogni stallo costava l'intero file e si ripartiva da zero.

Soluzione: scaricare con `curl -C -` (ripresa dal byte esatto) più `--speed-limit`/`--speed-time`
per abbandonare le connessioni morte, forzando **IPv4 e HTTP/1.1** (con HTTP/2 arrivavano
`Connection reset by peer` a metà file). Così sono passati 3,2 GB di pacchetti e 3,1 GB di pesi
**senza una sola ripresa necessaria**. Gli script sono in scratchpad e vanno rifatti se si
reinstalla altrove.

Altre due trappole: `uv venv` non installa `setuptools`, che serve a `resemble-perth` (il
watermarker di Chatterbox) per `pkg_resources`; e va pinnato a **`setuptools<81`**, perché dalla 81
`pkg_resources` è stato rimosso.

---

## Giro 11 — la colpa era della catena di post-produzione ✅ (2026-09-16)

**Esperimento 1: catena ridotta al solo `highpass`** → `poc/out/paperino_p41_H_senza_eq.mp3`.
Svuotati `source_eq.filters` e, per narratore/matt/paperino, tutto tranne l'`highpass`: via l'EQ di
presenza a 3 kHz e i compressori. Intatti il filtro radio di Hilde, il compressore `sfx` e le pause.

**Esito all'ascolto: il metallico è sparito.** Quindi non era Chatterbox: con un modello che genera
già pulito, la catena ereditata da XTTS e dal microfono scuro non correggeva più niente e aggiungeva
solo artefatti. `poc/voices.json` resta su questa catena.

### Quale stadio lo produceva
Tre varianti, ognuna con **un solo stadio rimesso** sulla catena pulita (mai due insieme — la
lezione del giro 4):

| file | stadio rimesso | 2-4 kHz | decad. |
|---|---|---|---|
| `_H_senza_eq` | catena pulita, riferimento | −29,1 dB | 90 ms |
| `_I_con_source_eq` | shelf +3 dB @1800 | −25,8 dB (+3,3) | 90 ms |
| `_J_con_eq_presenza` | EQ di presenza @3k (+2,5/+3,5/+4 dB) | −27,3 dB (+1,8) | 90 ms |
| `_K_con_compressori` | compressori dei personaggi | −28,2 dB (+0,9) | 100 ms |
| `_chatterbox` | catena completa, il file che suonava metallico | −21,9 dB (+7,2) | 100 ms |

`source_eq` è quello che alza di più la banda incriminata, ed era il primo sospettato.

**Esito: la caccia si ferma qui.** Prima che le tre varianti venissero ascoltate, il riascolto
mattutino ha giudicato buono anche l'originale con la catena completa: il difetto non si riproduce,
quindi non c'è un colpevole da isolare. `_I_`, `_J_`, `_K_` restano in `poc/out/` come materiale
per un eventuale A/B alla cieca; si possono cancellare.

Quello che il giro lascia comunque: la catena ridotta suona come quella completa, e i suoi stadi
non hanno più una ragione d'essere (compensavano microfono e vocoder che non ci sono più).

---

## Giro 12 — A/B alla cieca: le due catene sono indistinguibili ✅ (2026-09-16)

Dopo che il difetto non si è riprodotto a mente fresca, la domanda "ridotta o completa?" non si
poteva più decidere a nomi scoperti. Quattro giri di confronto in `poc/out/ab/`, stessi due
montaggi, **ordine rimescolato a ogni giro** (chiave fuori dal progetto, non consultata prima delle
risposte), entrambi normalizzati a −16 LUFS perché il più forte non sembrasse il migliore.

**Esito: "pari" in tutti e quattro i giri.** Le due catene non sono distinguibili all'ascolto.

**Decisione: si congela la catena ridotta**, non perché suoni meglio, ma perché a parità di
risultato ha meno stadi da ritarare sulle 12 pagine, e nessuno di quelli tolti ha più una ragione
tecnica (compensavano il microfono scuro e il vocoder di XTTS, entrambi fuori dai giochi).

Stato finale della catena, in `poc/voices.json`:

    cleanup      highpass=70
    source_eq    (vuoto)
    narratore    highpass=100
    matt         highpass=100
    paperino     highpass=110
    hilde_radio  passa-banda 300-3000, compressore, saturazione tanh   <- effetto voluto
    sfx          compressore                                           <- effetto voluto

Il carattere dei personaggi lo danno ora `exaggeration`/`cfg_weight` di Chatterbox e il riferimento
intonato (`REF_PITCH × pitch`), non la post-produzione. Materiale di scarto cancellabile:
`paperino_p41_{B,C,D,E,F,G,H,I,J,K}_*`, `mic2`, `mic4`, `prova_metallico/`, `ab/`.

---

## Fase 7 — Dalla pagina alla storia intera ✅ fatta

**Perimetro:** le ~12 pagine della storia (Topolino p. 41-51+), 250-350 balloon, stimati 20-25
minuti di audio. La pagina 41 è già fatta e fa da riferimento.

### 7.1 — Rendering e raddrizzamento delle pagine ✅ fatta
`./poc/render_pages.sh` → `pages/render/p41.png` … `p52.png` a 300 dpi. **La storia è di 12 pagine,
41-52.**

Tre cose imparate, tutte dentro lo script:
- le pagine PDF 2-6 vanno ruotate in senso **orario** (così la pari finisce a sinistra e la dispari
  a destra);
- **la piega non sta a metà del foglio**: sta a x≈1900-1960 su 3508. Tagliare a metà, come sembrava
  ovvio, mangiava l'ultima striscia della pagina di sinistra. La piega si trova cercando la colonna
  più scura nella fascia centrale, e si ricalcola per ogni foglio; il taglio lascia 30 px di
  sovrapposizione, perché un filo della pagina accanto è meno grave di un balloon tagliato;
- le pagine PDF 1 e 7 contengono anche altri articoli e si ritagliano a coordinate fisse, trovate a
  occhio e verificate guardando il risultato.

Le 12 pagine sono state controllate una per una: numerazione giusta, nessun pannello tagliato.

### 7.2 — Pipeline multi-pagina ✅ fatta
Nuovo layout, una pagina per volta invece di tutto cablato sulla 41:

    poc/script/pNN.json      lo script della pagina (prima: poc/script.json)
    poc/clips/pNN/           le clip grezze     (prima: poc/clips/*.wav)
    poc/clips/pNN/.cache.json
    poc/out/pagine/pNN.mp3   una pagina montata
    poc/out/storia.mp3       la storia intera

Comandi:

    ./poc/run_poc.sh --page 42              sintesi + montaggio di una pagina
    ./poc/run_poc.sh --all                  tutte, un file per pagina
    ./poc/run_poc.sh --story                tutte in un file unico
    ./poc/run_poc.sh --assemble --page 42   solo regia e montaggio, niente GPU
    ...synthesize_chatterbox.py --all --dry-run    cosa verrebbe risintetizzato

**Cache della sintesi:** ogni clip è marcata con l'impronta di ciò che la determina (testo,
personaggio, `exaggeration`, `cfg_weight`, `pitch`, `REF_PITCH`, seed, lingua). Se l'impronta non
cambia, la clip non si rifà, e se la cache copre tutto il modello non viene nemmeno caricato (sono
~30 s e 2,5 GB di VRAM per non generare niente). La cache si scrive dopo **ogni** clip, così
un'interruzione a metà pagina non costringe a rifare quelle già buone. `--force` rifà tutto.
Verificato: cambiando una sola battuta, ne risintetizza una sola.

**La storia intera non è la concatenazione degli mp3 delle pagine**: quelli sono già normalizzati
uno per uno e rimetterli in fila farebbe saltare il volume a ogni pagina. `--story` concatena i
pezzi lavorati e normalizza una volta sola.

**Verifica di non-regressione:** `--page 41` produce un file **byte per byte identico** al montaggio
congelato, quindi la ristrutturazione non ha toccato l'audio.

*Corretto un baco latente:* `speaker_reference` metteva in cache il riferimento intonato col solo
nome del personaggio, quindi cambiando il `pitch` in `voices.json` avrebbe riusato quello vecchio
senza dirlo — proprio la manopola che servirà nel 7.4. Ora il rapporto è nel nome del file.

*`poc/synthesize.py` (XTTS) è superato* e legge ancora il vecchio layout: sta lì come riferimento
storico, non gira più.

### 7.3 — Trascrizione, una pagina per volta ✅ fatta
Tutte e 12 le pagine trascritte a mano leggendo le immagini in sessione: **131 balloon**, da 7
(pagina 46, quasi tutta azione) a 15 (pagina 52).

**La radio è un attributo della battuta, non del personaggio.** Nella pagina 42 la scena cambia
stazione a metà: fino al pannello 3 siamo alla baita di Paperino e dalla ricetrasmittente esce la
voce di Hilde, dal 4 siamo da Hilde e dalla radio esce quella di Paperino. Con `hilde_radio` come
personaggio sarebbe servito anche `paperino_radio`, e poi `matt_radio`. Quindi `voices.json` ha lo
speaker `hilde` e un blocco `channels` con `radio`, che si somma a qualunque personaggio; nello
script la battuta porta `"radio": true`. Nel fumetto si riconosce dal balloon seghettato e dal
corsivo.

**Come si riconosce chi parla**, in ordine di affidabilità:
1. la coda del balloon — quasi sempre basta, ma va guardata a piena risoluzione, non sul
   ridimensionamento della pagina;
2. **il colore del balloon**: dalla pagina 49 i turisti hanno un colore fisso — rosa Otis,
   giallo/grigio Bob, lilla Susy. Ha sciolto tre attribuzioni ambigue nella 51;
3. il registro del personaggio (Bob dice sempre "uao", Susy parla di vibrazioni, Otis conta e cita
   gadget) — usato solo come conferma.

Le poche attribuzioni dedotte sono marcate con `nota_tts` nello script: la voce fuori campo della
43, il sospiro della 48, "ho creduto in te fin dall'inizio" della 52.

*Trappola della cache:* il nome del personaggio entra nell'impronta ma non negli ingressi del
modello, quindi una rinomina invalida la cache pur non cambiando l'audio. Nel caso della 41 è stata
riallineata a mano invece di risintetizzare.

### 7.4 — Cast completo ✅ fatto (sette voci)
Cast a oggi, con l'altezza voluta (`pitch`, cioè lo scostamento dalla voce reale di Mauro):

| | pitch | rif | carattere |
|---|---|---|---|
| `bob` | 0,90 | x0,801 | turista palestrato e vanaglorioso |
| `matt` | 0,97 | x0,863 | ranger anziano, posato |
| `narratore` | 1,00 | x0,890 | didascalie |
| `otis` | 1,04 | x0,926 | turista anziano e gioviale, portavoce |
| `paperino` | 1,06 | x0,943 | brontolone, scattante |
| `hilde` | 1,12 | x0,997 | la ranger dell'altra stazione |
| `susy` | 1,18 | x1,050 | turista senza fiato, frasi spezzate |

⚠️ **L'altezza non separa i personaggi, e allargare l'arco non è bastato.** Misura dell'F0 su tutte
le clip delle pagine 41-43:

| personaggio | F0 misurata |
|---|---|
| paperino | 105-146 Hz (6 semitoni di variabilità su 9 battute) |
| hilde | 119-169 Hz |
| otis | 130-143 Hz |
| bob (il più grave) | **127-130 Hz** |
| susy (la più acuta) | 159-161 Hz |

Bob esce sopra a metà delle battute di Paperino. Il modello decide l'altezza battuta per battuta e
il riferimento intonato lo sposta poco: è lo stesso limite visto nel giro 10, ma con sette
personaggi non è più tollerabile.

**Proposta (da fare):** usare il ritentativo del 7.6 anche per questo. Si generano già fino a tre
prese per battuta; fra quelle senza difetti si può tenere **quella con l'F0 più vicina al bersaglio
del personaggio** invece della prima. Costa nulla in più (le prese ci sono già) e agisce dove il
difetto nasce, senza trasporre a valle — che è la strada scartata nei giri 8-9 perché suona
metallica.

### 7.5 — Montaggio della storia ✅ fatto
`./poc/run_poc.sh --story` → **`poc/out/storia.mp3`, 389 s (6'29")**. Non è la concatenazione degli
mp3 delle pagine: quelli sono normalizzati uno per uno, e rimetterli in fila farebbe saltare il
volume a ogni pagina. Si concatenano i pezzi lavorati e si normalizza una volta sola. Fra una pagina
e l'altra c'è la pausa di fine pagina, 1,2 s.

Il controllo di qualità non è più "a campione" come previsto: `check_clips.py` passa tutte e 131 le
clip a ogni montaggio e non segnala nulla. Non sostituisce l'ascolto, ma garantisce che non ci siano
clip mute, troncate, in clipping o con vuoti di secondi.

---

## Giro 13 — i vuoti dentro le battute ✅ (2026-09-16)

"A parte qualche artefatto strano qua e là mi sembra buono", detto della pagina 42. Invece di
partire a caccia, un passaggio automatico per localizzare i punti: **`poc/check_clips.py`**, che
non giudica la qualità — quella resta all'orecchio — ma segnala i guasti tipici della sintesi
(clip troncata, coda di silenzio, vuoto interno, ritmo anomalo, clipping) con il minuto nel
montaggio della pagina. Con 300 balloon è l'unico modo per non riascoltare tutto.

Ha trovato **vuoti di 2,3 s in mezzo alle frasi**: "Qui parla il ranger... [2,3 s] ...Paperino!".
Presenti già nella clip grezza, quindi generati dal modello, e tipici dei testi con puntini di
sospensione.

**Causa:** la pipeline di XTTS li correggeva (`collapse_gaps` in `synthesize.py`) e la cosa è
rimasta indietro nel passaggio a Chatterbox, che non ha nessuna delle sue protezioni (né il taglio
dei vuoti, né il ritentativo sulle prese difettose).

**Rimedio:** `clip_cleanup` in `voices.json`, applicato da `assemble.py` **prima** della catena di
carattere. Sta in post e non nella sintesi, così si ritara in pochi secondi e vale sulle clip già
generate. Dei vuoti oltre 450 ms se ne tiene 260 ms — un pezzo del silenzio vero, non una giunta
digitale, che in mezzo a una frase si sentirebbe. Ai bordi restano 120 ms, perché le pause del
racconto le decide il montaggio.

Verificato che tolga solo silenzio: la durata del **parlato** è invariata al centesimo (3,27 → 3,30 s
su una clip da cui sono stati tolti 1,2 s), cambia solo quella totale. Segnalazioni da 8 a 4.
Pagina 41 da 39,3 a 35,0 s, pagina 42 da 46,3 a 38,5 s.

⚠️ **La pagina 41 approvata aveva lo stesso difetto** e nessuno l'aveva sentito: 2,2 s di vuoti in
due battute. Il montaggio di riferimento non è più byte-identico, e la nuova versione va
riascoltata prima di sostituirlo.

### 7.6 — Prese difettose ✅ fatto (vedi giro 15)
Le quattro segnalazioni rimaste sono difetti **nel file generato**, che la post-produzione non può
togliere:
- **clipping**: `05_matt` e `06_paperino` escono dal modello con tratti piatti fino a 0,33 ms a
  fondo scala; su `09_paperino` invece è la nostra catena ad arrivarci (3 campioni), e basterebbe
  un limiter a −1 dB in coda per non peggiorare quello che il modello consegna;
- **parola troncata**: `05_matt` ("Caffè?") e `03_paperino` ("Uff... sono Paolino!") finiscono
  mentre c'è ancora segnale.

La strada è quella che XTTS aveva già: **ritentare la presa** quando la clip esce difettosa,
cambiando seed, e tenere la migliore. Va portata in `synthesize_chatterbox.py` usando i controlli
di `check_clips.py` come criterio.

---

## Giro 14 — pause interne e code spurie ✅ (2026-09-16)

Due segnalazioni precise di Mauro sulla pagina 42, entrambe risolte in post, senza GPU.

**"Il primo balloon separa troppo le tre parti: qui parla / il ranger / Paperino."** Il giro 13
accorciava i vuoti oltre 450 ms tenendone 260, ma dentro quella frase restavano due pause da
0,40-0,42 s — sotto la soglia, quindi mai toccate, e comunque troppo lunghe. Ritarato:
`max_gap_ms` 450 → **300**, `keep_gap_ms` 260 → **120**. La battuta passa da 3,63 a 2,88 s e le
pause interne da 0,40 s a 0,10-0,15 s, cioè la distanza normale fra parole.

**"Un artefatto strano tra 'Uff... sono Paolino' e 'Ah, ciao...'."** Misurato il profilo della
giunzione: la battuta finisce, scende a −72 dB, e negli ultimi 75 ms **risale a −8 dB e viene
tagliata di netto** a fine file. È il *long tail* per cui Chatterbox forza l'EOS (compare nei
warning della sintesi): all'ascolto è un colpo secco fra due battute.

`clip_cleanup` ora toglie la coda spuria, con tre condizioni insieme perché non mangi una parola
vera: più corta di 150 ms, isolata da almeno 250 ms di silenzio, e attaccata alla fine del file.
Verificata sul caso opposto: "Caffè?" della pagina 41 finisce anch'essa tagliata, ma il suo ultimo
segmento dura 325 ms — è la parola, e infatti resta intatta.

Segnalazioni di `check_clips.py` da 8 a 3 (tutte clipping). Pagina 42 a 35,9 s, pagina 41 a 33,3 s.

---

## Giro 15 — 7.6: ritentare le prese difettose ✅ (2026-09-16)

XTTS ritentava la presa quando la clip usciva sporca o in loop; nel passaggio a Chatterbox la cosa
si era persa. Rimessa, con i controlli di `check_clips.py` come criterio condiviso fra i due script.

**Divisione netta fra i due rimedi**, che è il punto del giro:
- i difetti che il montaggio sa togliere — vuoti interni, code di silenzio, code spurie — **non**
  fanno ritentare: risintetizzare costerebbe GPU per un problema già risolto in post;
- quelli che restano nel file generato — parola troncata, clipping, clip muta, ritmo da loop —
  fanno rifare la presa con un altro seed, fino a tre tentativi. Si tiene la prima presa pulita, o
  la meno compromessa se nessuna lo è (`gravita()` pesa muta 10, troncata 3, clipping 1).

Il seed scelto e i difetti residui finiscono nella cache, così si sa sempre da cosa viene una clip.

**Aggiunto anche un limiter** a −1 dB in coda alla catena (`cleanup.post_filters`,
`alimiter=limit=0.891:level=false` — senza `level=false` alimiter rialza il volume da solo). Non è
un effetto ma un paracadute: alcune clip escono dal modello già a fondo scala e la catena di
carattere le spingeva oltre, aggiungendo clipping che nella grezza non c'era. Agisce solo sulle
punte: la clip incriminata scende a −1,00 dBFS, le altre non si muovono.

**Esito:** `check_clips.py` non segnala più nulla sulle pagine 41, 42 e 43. Sulla 43, appena
sintetizzata, il ritentativo è intervenuto su 6 battute su 12 e le ha risolte tutte — il che dice
anche quanto spesso Chatterbox sbaglia una presa, e quanto sarebbe costato scoprirlo a orecchio su
300 balloon.

---

## Giro 16 — scegliere la presa per altezza: provata e scartata ✅

Il 7.6 genera già fino a tre prese per battuta e tiene la prima pulita. Con `--scegli-altezza` le
genera comunque tutte e fra quelle pulite tiene **la più vicina al bersaglio del personaggio**
(`pitch_target_hz` × il `pitch` del personaggio), fermandosi prima se una presa è già entro un
semitono. Agisce dove il difetto nasce, senza trasporre a valle — la strada scartata nei giri 8-9
perché suona metallica.

| | scarto medio dal bersaglio | massimo |
|---|---|---|
| A, prima presa pulita | 2,03 semitoni | 4,3 |
| B, presa scelta per altezza | **1,33 semitoni** | **2,5** |

L'ordine dei personaggi in B diventa coerente — bob 120-127, matt 126-128, otis 130-136, paperino
132-146, susy 153-161 — mentre in A Matt passava da 100 a 152 Hz fra due grugniti. Le fasce però
si toccano ancora.

Costo: **da ~50 s a ~1 min 54 s a pagina**, perché quasi ogni battuta consuma tutte e tre le prese.

*Dettaglio della cache:* la chiave `scelta_altezza` entra nell'impronta **solo quando il modo è
attivo**, così le pagine già sintetizzate senza non vengono invalidate da una prova.

**Osservazione che vale per il prossimo giro:** in B tutte le battute restano **sopra** il
bersaglio, in media di 1,3 semitoni — nessuna sotto. È una deriva sistematica, non rumore: il
modello non scende dove gli si chiede. Si corregge abbassando `REF_PITCH` (0,89 → ~0,82), con la
cautela che la risposta di Chatterbox è stata misurata solo fra x0,86 e x1,00 e più in basso è
terra incognita.

**Esito: all'ascolto va bene anche A**, quindi si tiene la prima presa pulita e `--scegli-altezza`
resta un'opzione inutilizzata. La pagina 43 è stata riportata alla versione A;
`p43_B_altezza_scelta.mp3` resta in `poc/out/pagine/` come termine di paragone e si può cancellare.

La misura migliorava davvero — e non è bastato. Vale come promemoria simmetrico rispetto ai giri
8-12: lì l'orecchio segnalava difetti che le misure non vedevano, qui una misura migliore non
corrisponde a niente di udibile. In entrambi i casi decide l'ascolto, e i numeri servono a capire
*cosa* si sta cambiando, non *se* vale la pena.

---

## Giro 17 — le dieci pagine restanti ✅ (2026-09-16)

Dalla 44 alla 52 di fila, senza fermarsi fra una e l'altra. Due interventi nati strada facendo,
entrambi in post e quindi applicati anche alle pagine già fatte:

**Dissolvenza ai bordi della clip.** Nella pagina 46 una battuta usciva troncata in tutte e tre le
prese: il modello tagliava la coda dell'ultima parola mentre ancora sfumava, e attaccata alla
battuta dopo si sentiva come uno scatto. Ora le clip chiudono con 15 ms di dissolvenza, **ma solo se
la fine è già quasi spenta** (sotto −20 dBFS): se la clip finisce forte è una parola tagliata sul
serio, e deve restare evidente perché `check_clips` la segnali e la sintesi la rifaccia.

**Soglie allineate.** `TRONCATA_DBFS` in `check_clips.py` è passata da −30 a −20 dBFS, cioè
esattamente la soglia della dissolvenza. Prima i due meccanismi si contraddicevano: il montaggio
sfumava una coda e il controllo continuava a segnalarla. Ora dicono la stessa cosa — sotto quel
livello la parola sta finendo e va chiusa dolcemente, sopra è troncata e nessuna post-produzione la
recupera.

**Il ritentativo lavora parecchio:** su queste pagine è intervenuto su circa una battuta su tre,
quasi sempre per clipping. Senza, sarebbero difetti da scovare a orecchio su 131 clip.

---

## Giro 18 — il riascolto della storia intera ⏳ (2026-09-16)

Quattro segnalazioni dall'ascolto dei sei minuti di fila. Tutte e quattro hanno trovato **buchi nei
controlli**, non solo difetti nelle clip: è la prima volta che il PoC gira abbastanza a lungo da
farli emergere.

### "A pagina 48 e 49 ci sono un po' di ripetizioni"
Il modello ridice lo stesso pezzo: "Beeeeeh!" della 49 sono **due belati** (0,70 s + 0,75 s), e
"...scarica!" della 48 esce spezzettato in cinque tratti. Nessun controllo lo vedeva, perché su un
testo corto una ripetizione resta dentro i tempi plausibili.

Nuovo controllo `ripetizione`: si confronta l'inviluppo di energia della clip con se stesso a vari
ritardi, e se una frase è stata ridetta l'inviluppo si somiglia a quel ritardo. Le clip pulite
stanno a 0,80 o meno, i casi veri fra 0,84 e 0,95; soglia a 0,83. Le ripetizioni **volute** non
scattano: si contano prima le parole ripetute nel testo, così "Slap! Slap!" e "Ih, ih, ih!" restano
fuori.

⚠️ **Va misurata sulla clip grezza, non su quella lavorata.** Il montaggio accorcia i vuoti e così
facendo cancella proprio la periodicità che tradisce la ripetizione: sulla lavorata "Beeeeeh!"
scende da 0,86 a 0,55 e passerebbe liscia, pur restando due belati all'ascolto.

Trovate 5 ripetizioni su 131 clip.

### "A pagina 52 manca una frase dopo «eh, eh...» e prima di «HRMPF»"
Due difetti sovrapposti, e il secondo è il più serio.

**L'ordine.** Nel pannello i due balloon stanno uno in alto a destra e uno in basso a sinistra, e li
avevo letti dall'alto: "Hrmpf!" e poi "Caffè?". È il contrario — il grugnito è la *risposta*
all'offerta del caffè, come nella pagina 41. Letti nell'ordine sbagliato, il grugnito non risponde
a nulla e si sente che manca qualcosa.

**La clip incompleta.** Manca anche il testo: la clip dura **0,60 s di parlato per 49 caratteri**,
cioè 82 caratteri al secondo. Il modello aveva detto "Eh, eh!" e si era fermato. Il controllo del
ritmo non era scattato perché lo avevo sospeso sulle clip sotto il secondo di parlato — cioè
esattamente il caso peggiore, quello in cui la clip è troppo corta per contenere il testo. Tolta la
sospensione e aggiunto il difetto **`incompleta`** (oltre il doppio della velocità massima
plausibile), che pesa quasi quanto una clip muta. Su 131 clip ne è emersa una sola: quella.

### "Alcune parole hanno l'accento sbagliato"
Due famiglie, trattate diversamente:
- **sdrucciole** — `bùssola`, `ossìgeno`, `sollètico`, `lìtio`: l'accento esplicito coincide con la
  pronuncia italiana corretta, quindi o corregge o conferma, e si può mettere senza chiedere;
- **inglesismi** — `rèingiar`, `scèf`, `tutòrial`, `spèscial`: qui la resa giusta è una scelta, non
  un fatto, e l'ha decisa Mauro. `ranger` da solo tocca 8 battute, titolo compreso.

### Altezze più marcate e canale sussurro
- **Altezze** allargate una seconda volta: da 0,90-1,18 a **0,85-1,26**, cioè da 5 a 7 semitoni di
  arco. Bob porta il riferimento a x0,757 e Susy a x1,121, oltre l'intervallo x0,86-1,00 in cui la
  risposta del modello è stata misurata: da verificare all'ascolto che il timbro non si sfaldi.
- **Canale `sussurro`** per i balloon tratteggiati (pagina 45, i turisti che sparlano di Paperino).
  A differenza della radio non è solo un filtro: un sussurro è anche *meno enfatico*, quindi il
  canale abbassa `exaggeration` a 0,35 e alza `cfg_weight` a 0,6 **in generazione**, e in post
  toglie 7 dB e taglia gli estremi. I canali possono quindi cambiare anche i parametri del modello,
  e il nome del canale entra nell'impronta della cache — ma solo quando c'è, così le clip senza
  canale non vengono invalidate.

### Esito del giro 18

**Il ritmo si misura sul solo parlato.** Contare anche le pause interne confondeva "parla piano"
con "fa una pausa a effetto" — e soprattutto nascondeva le clip incomplete. Ritarate le soglie
sulla distribuzione reale delle 131 clip (mediana 20,3 car/s, percentili 12,0-32,9): `lenta` sotto
10, `veloce` sopra 34, **`incompleta` sopra 45**. Le soglie precedenti erano stimate su dieci clip
di una pagina sola.

Il cambio ha subito trovato una **seconda clip incompleta** che nessuno aveva segnalato: "Tsk!
Faremo con la mia!" della pagina 47, 23 caratteri in **0,35 secondi** di parlato. Con la misura
vecchia risultava solo "veloce".

**Risintesi:** 106 clip rifatte, più 4 forzate (le due ripetizioni del narratore, che la cache
considerava a posto perché testo e altezza non erano cambiati, e le due della pagina 47). Il
ritentativo è intervenuto su circa un terzo delle prese, quasi sempre per clipping.

**Altezze, misurate su tutte le clip:**

| | bersaglio | mediana | intervallo |
|---|---|---|---|
| bob | 104 Hz | 121 Hz | 88-148 |
| matt | 113 | 132 | 111-160 |
| narratore | 122 | 134 | 92-192 |
| otis | 128 | 140 | 98-167 |
| paperino | 134 | 145 | 105-229 |
| hilde | 144 | 148 | 130-163 |
| susy | 154 | 154 | 141-175 |

Le mediane sono **nell'ordine giusto** e seguono i bersagli, cosa che prima non succedeva (Bob
usciva sopra metà delle battute di Paperino). Ma gli intervalli si sovrappongono ancora: fra
personaggi vicini le mediane distano 0,2-1,6 semitoni, mentre dentro lo stesso personaggio il
modello varia di 6-8. E tutte le voci restano ~2 semitoni **sopra** il bersaglio: deriva
sistematica, non rumore.

---

## Giro 19 — battute spezzate, accenti, inglesismi ✅ (2026-09-16)

### "I balloon «Siamo...» «...tornati...» «...a Picco Fiocco!» sono corrotti"
Le misure non vedevano niente: spettro normale, nessun clipping, ritmo plausibile. Il segnale era
altrove — **tre tratti di suono separati da 1,18 s di silenzio per una parola sola**.

Due cause, entrambe legate ai testi cortissimi:
- **i puntini iniziali.** Nel fumetto "...tornati..." segnala che la frase continua dal balloon
  precedente, ma il modello ci si perde: escono frammenti, vuoti e ripetizioni. I puntini iniziali
  ora si tolgono dal `text_tts` (restano nel `text`, che è la trascrizione di quel che è stampato),
  perché la pausa fra un balloon e l'altro la mette già il montaggio. I puntini finali restano:
  quelli una pausa la vogliono davvero;
- **le battute di una o due parole** in generale. "Fine.", "Siamo...", "Beeeeeh!", "Così...": il
  modello dice la parola e poi divaga.

Nuovo difetto **`spezzata`**: un vuoto oltre 0,9 s dentro un testo di al massimo due parole non è
una pausa a effetto, è il modello che si perde — e accorciare il silenzio, come fa il montaggio,
non rimette insieme la parola. Va misurato sulla **grezza**, come la ripetizione: sulla lavorata il
vuoto è già stato accorciato e il difetto sparisce dalla misura pur restando all'ascolto.

`TENTATIVI` da 3 a **5**: su queste battute corte capitava di non trovare una presa pulita in tre.
Sulle battute normali il ciclo si ferma comunque alla prima.

### Accenti
- **`cèdile` e `spòstati`**, segnalati da Mauro, sono imperativo + pronome attaccato: una famiglia
  intera in cui il modello sposta l'accento sull'ultima sillaba. Corretti tutti quelli presenti —
  `dàtemi`, `chiamàtemi`, `seguìtemi`, `aiutàtemi`, `guardàtemi`, `sentìtemi` — perché sono lo
  stesso errore, e l'accento esplicito coincide con la pronuncia italiana corretta;
- **`rènger`** al posto di `rèingiar`: scelta di Mauro all'ascolto. Tocca 8 battute, titolo compreso.

### Riorganizzazione dei controlli
I difetti sono ora divisi per **dove si vedono**, non per tipo:
- `difetti()` — sulla clip lavorata: coda, vuoto, troncata, clipping, ritmo, muta;
- `difetti_grezza()` — solo sulla grezza: **ripetizione** e **spezzata**, perché il montaggio,
  accorciando i vuoti, cancella proprio le tracce che le rivelano.

`synthesize_chatterbox.py` usa entrambi sulla presa appena generata; `check_clips.py` usa i primi
sulla lavorata e i secondi sulla grezza della stessa clip.

Restano 10 clip su 131 con un vuoto interno oltre 0,9 secondi, tutte con testo lungo: sono pause
dentro frasi vere, e il montaggio le accorcia senza doverle rifare.

---

## Esperimento — leggere il fumetto da un filmato invece che dallo scanner (2026-09-16)

`video/Video 2026-09-16 09-44-05.3g2`: 30 secondi, **704x576**, h263, che inquadrano prima la
pagina 41 e poi la doppia 42-43 tenute in mano davanti alla telecamera.

**Un fotogramma singolo non basta.** Il testo dei balloon sta su 5-6 pixel di altezza: si riconosce
la pagina, non le parole. Ma il libro e' tenuto a mano, quindi ogni fotogramma e' spostato di una
frazione di pixel rispetto agli altri — allineandone qualche decina e mediandoli si abbatte il
rumore di compressione e si recupera dettaglio vero.

**`poc/stack_video.py`** fa questo: estrae i fotogrammi di un intervallo, tiene i piu' nitidi
(varianza del laplaciano), li allinea per correlazione di fase, li media a risoluzione moltiplicata
e chiude con una maschera di contrasto. L'allineamento si calcola sulla luminanza ma la media si fa
sui tre canali, perche' **il colore dei balloon dice chi parla** (rosa Otis, giallo Bob, lilla
Susy) e in bianco e nero quell'informazione si perderebbe.

    poc/.venv/bin/python poc/stack_video.py FILMATO --da 1 --a 9 \
        --zona 375,140,310,340 --uscita pagina.png --frames 50

**Esito: sulla pagina 41 funziona.** Con 50 fotogrammi impilati si leggono didascalie, balloon e
perfino la riga dei crediti in corpo minuscolo.

⚠️ **Verifica onesta.** Le pagine del filmato le avevo gia' trascritte dallo scanner, quindi la mia
lettura non prova nulla: so gia' cosa c'e' scritto. La prova e' stata fatta sull'**articolo nella
pagina accanto**, che non ho mai trascritto — "Prima della diffusione del telegrafo e della
ferrovia, la velocita' di un giornale dipendeva dalla resistenza e dalla rapidita' dei cavalli" —
e poi confrontata con la scansione a 300 dpi, che la conferma. Quel testo e' anche **piu' piccolo**
del lettering dei balloon.

**Sulla doppia pagina 42-43 non funziona.** Misurato il perche': non e' il movimento (spostamento
mediano fra fotogrammi consecutivi 1,0 px in entrambi i tratti) ma la **nitidezza**, che passa da
370 a 212 di varianza del laplaciano — due pagine nello stesso fotogramma significano meta' pixel
per lettera, e la messa a fuoco tiene meno.

**Regole per un filmato utilizzabile**, se si vuole usare questa strada su un fumetto non scansionato:
- **una pagina per volta**, che riempia l'inquadratura: serve almeno ~300 px di larghezza di pagina;
- **ferma 5-8 secondi**, cioe' 150-240 fotogrammi, di cui i 40-50 piu' nitidi finiscono nello stack;
- **niente rotazione**: l'allineamento corregge solo la traslazione;
- meglio ancora, girare a risoluzione maggiore: a 1080p un fotogramma singolo sarebbe gia'
  leggibile e lo stack diventerebbe un di piu'.

**Resta comunque peggio della scansione**: la pagina 41 dal filmato rende ~1240x1360 utili contro i
1680x2330 dello scanner a 300 dpi, con i colori slavati e la pagina incurvata. E' una strada di
ripiego valida, non un sostituto.

### Secondo giro di riprese: conta il codec, non la risoluzione dichiarata

Tre file a confronto, le stesse pagine:

| file | codec | risoluzione | fps | larghezza della pagina nel fotogramma | esito |
|---|---|---|---|---|---|
| `...09-44-05.3g2` (1ª versione) | h263 | 704x576 | 30 | ~310 px | stack leggibile sulla 41, **no** sulla doppia |
| `...09-44-05.3g2` (rigirato) | h263 | 704x576 | **2** | ~128 px | inutilizzabile: pochi fotogrammi e pagina lontana |
| `...11-54-45.mp4` | **h264** | 640x480 | 30 | ~200 px | **leggibile su entrambe, a colori** |

Il terzo file ha **meno pixel** del primo, sia come fotogramma (640x480 contro 704x576) sia come
pagina inquadrata (~200 px di larghezza contro ~310), eppure il risultato è nettamente migliore. Il
motivo è il codec: h263 è un formato del 1996 che sui dettagli fini fa piazza pulita, h264 a
1,9 Mbit/s li conserva. **La risoluzione dichiarata dice poco: quello che conta è quanti pixel
sopravvivono alla compressione.**

Nel secondo file il tentativo di "alzare la risoluzione" ha invece prodotto un video a 2 fotogrammi
al secondo: ogni fotogramma è meno compresso (44 KB contro 7,4), ma con 10 fotogrammi utili in una
finestra di 5 secondi lo stack non ha materiale su cui lavorare, e la pagina era anche più lontana.

**Per la prossima ripresa:** tenere il formato mp4/h264, e inquadrare **una pagina sola che riempia
il fotogramma** invece della doppia. Rispetto a ora raddoppierebbe i pixel per lettera.

**Prova ancora da fare:** finora i filmati mostrano pagine che avevo già trascritto dalla scansione,
quindi la lettura non prova niente — l'unica verifica valida è stata quella sull'articolo accanto,
mai trascritto. Per misurare davvero questa strada serve una **pagina mai vista**.
