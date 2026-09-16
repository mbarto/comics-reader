# Archivio

`synthesize_xtts.py` è la sintesi con **XTTS-v2**, sostituita da Chatterbox nel giro 10 perché
produceva un timbro metallico che nessuna taratura toglieva (il confronto è in `TECNOLOGIE.md`).

**Non gira più com'è:** legge il vecchio layout a pagina singola (`poc/script.json`,
`poc/clips/*.wav`) che non esiste più. Sta qui come riferimento di come era fatta quella pipeline —
in particolare per `collapse_gaps` e per il ritentativo sulle prese rumorose, due idee che sono poi
tornate, in forma diversa, in `assemble.py` e `synthesize_chatterbox.py`.
