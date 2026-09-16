# Comics Reader

Leggere ad alta voce un fumetto scansionato, balloon dopo balloon, con una voce clonata — in locale,
senza che la voce lasci la macchina.

Proof of concept portato a termine: una storia intera di 12 pagine e 131 balloon, con sette
personaggi, resa in un unico file audio di sei minuti e mezzo.

## Cosa c'è in questo repository

Il **codice** e la **documentazione**. Non ci sono né il fumetto (protetto da copyright), né le
registrazioni della voce, né l'audio prodotto: vedi *Cosa manca* più sotto.

| | |
|---|---|
| [`TECNOLOGIE.md`](TECNOLOGIE.md) | il documento tecnico: stack, architettura, licenze, e **quello che il PoC non ha dimostrato** |
| [`poc/PIANO.md`](poc/PIANO.md) | il diario: perché ogni scelta è stata fatta, e cosa è stato provato e scartato |
| `poc/setup.sh` | ricostruisce i due ambienti Python e scarica i pesi del modello |
| `poc/render_pages.sh` | dal PDF scansionato alle pagine singole, dritte e tagliate sulla piega |
| `poc/prepare_voice.sh` | prepara le finestre di riferimento della voce |
| `poc/synthesize_chatterbox.py` | sintesi, con cache e ritentativo sulle prese difettose |
| `poc/assemble.py` | regia, pulizia delle clip, canali, pause e montaggio |
| `poc/check_clips.py` | controllo qualità automatico: trova i guasti tipici della sintesi |
| `poc/measure.py`, `poc/intonation.py` | misure oggettive: rumore, presenza, riverbero, intonazione |
| `poc/stack_video.py` | esperimento: leggere le pagine da un filmato invece che dallo scanner |
| `poc/voices.json` | la regia: personaggi, canali, pause |

## Come funziona, in breve

```
PDF scansionato ──> pagine dritte ──> trascrizione (a mano) ──> script/pNN.json
                                                                      │
                                              voices.json ────────────┤
                                          (regia dei personaggi)      │
                                                                      ▼
                                                   sintesi con Chatterbox (GPU)
                                                     cache + ritentativo
                                                                      ▼
                                                  regia e montaggio (solo ffmpeg)
                                                                      ▼
                                                            storia.mp3
```

Il principio che regge la pipeline: **separare ciò che costa GPU da ciò che costa secondi**. La
sintesi si tocca il meno possibile; filtri, pause e montaggio stanno a valle e si ritarano in pochi
secondi.

## Cosa manca per farlo girare

Servono, e non sono in questo repository:

- una **scansione** del fumetto in `pages/`;
- una **registrazione della voce** in `voice/` — l'unica cosa davvero non rigenerabile, vedi
  [`voice/README.md`](voice/README.md);
- le **trascrizioni** in `poc/script/`: sono fatte a mano, leggendo le pagine. È il costo principale
  del progetto e il problema aperto più grosso.

Poi: `./poc/setup.sh`, `./poc/render_pages.sh`, `./poc/prepare_voice.sh`, `./poc/run_poc.sh --story`.

## Licenze e avvertenze

Il codice di questo repository è rilasciato sotto licenza **MIT** (vedi [`LICENSE`](LICENSE)).

Le dipendenze e i modelli hanno licenze proprie, e ci sono due avvertenze che vale la pena leggere
prima di usarlo: il **watermark** neurale presente in ogni audio generato, e il **copyright** del
materiale di partenza — un fumetto non diventa libero perché il software che lo legge lo è. Entrambe
nella sezione *Licenze e uso* di [`TECNOLOGIE.md`](TECNOLOGIE.md#10-licenze-e-uso).
