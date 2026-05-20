# Maggika Bot Ready

Bot Discord in Python con funzioni base:

- verifica membri con pulsante
- risposta ai ping del bot
- ping / spam ping limitato
- contaore
- report / moduli base
- ticket
- reminder DISBOARD che pinga chi ha usato `/bump`
- permessi staff tramite ruoli nel file `.env`

## Come avviare

Installa le dipendenze:

```powershell
py -m pip install -r requirements.txt
```

Copia `.env.example` in `.env` e compila token, server ID e canali mancanti:

```powershell
Copy-Item .env.example .env
```

Avvia il bot:

```powershell
py main.py
```

## Importante

Nel Developer Portal del bot abilita:

- Server Members Intent
- Message Content Intent

Nel server il ruolo del bot deve stare sopra al ruolo verifica, altrimenti non puo assegnarlo.

Per creare il pannello verifica usa:

```txt
/setup_verify
```
