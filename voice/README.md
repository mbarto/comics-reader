# La voce di riferimento

**Questa cartella contiene l'unica cosa del progetto che non si può rigenerare.**

Tutto il resto — clip, montaggi, ambienti, pesi del modello — si ricostruisce con `poc/setup.sh` e
`poc/run_poc.sh`. Queste registrazioni no: sono la voce di Mauro, e senza di esse il progetto non ha
più il suo oggetto.

## I file

| file | durata | canali | SNR | uso |
|---|---|---|---|---|
| `voce_mauro4.flac` | 32,1 s | stereo | 51,8 dB | **è questa quella in uso** |
| `voce_mauro3.flac` | 30,6 s | mono | — | presa precedente, microfono diverso |
| `voce_mauro2.flac` | 62,4 s | stereo | ~25 dB | prima presa, rumorosa: superata |

Tutte a 44,1 kHz, 16 bit, registrate il 2026-09-15.

## Perché `voce_mauro4` e non le altre

La prima registrazione aveva 25 dB di SNR, e il modello **clona le condizioni di registrazione
insieme al timbro**: il fruscio finiva dentro ogni battuta. Con `voce_mauro4` si sale a 51,8 dB, e
la catena di pulizia a valle è diventata quasi inutile — è la ragione per cui la post-produzione
oggi è quasi vuota.

## La dipendenza nascosta

`REF_PITCH = 0,89` in `poc/synthesize_chatterbox.py` **è tarato su questa registrazione**: è il
fattore che porta l'altezza del riferimento dove serve perché il modello generi alla nota di Mauro.

Se si cambia registrazione va **rimisurato**, non ereditato: si generano tre frasi con il
riferimento trasposto a fattori diversi, si misura l'F0 dell'uscita con `poc/intonation.py` e si
sceglie il fattore che la porta a ~122 Hz (l'altezza della voce reale di Mauro). La procedura sta
nel giro 10 di `poc/PIANO.md`.

## Integrità

`SHA256SUMS` contiene le impronte dei tre file. Per verificarle:

    cd voice && sha256sum -c SHA256SUMS

Verificato il 2026-09-16: tutti e tre decodificano senza errori.

⚠️ *Dettaglio tecnico:* l'intestazione FLAC di questi file **non dichiara la durata totale**. Sono
validi e si decodificano correttamente, ma `soundfile.read()` ci si strozza ("array is too big"):
per leggerli da Python conviene passare da ffmpeg, come fa `poc/prepare_voice.sh`.

## Cosa manca, e tocca a Mauro

**Una copia fuori da questa macchina.** Sono 5 MB in tutto. Il progetto intero, pesi del modello
compresi, è ricostruibile da zero; questi tre file no. Un disco che si rompe li porta via, e con
loro l'unica cosa che rende il progetto quello che è.
