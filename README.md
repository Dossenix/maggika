# Maggika Bot

Bot Discord in Python basato su slash command, pulsanti persistenti e database SQLite.

Funzioni principali:

- verifica membri con pulsante
- risposta automatica quando viene pingato il bot
- spam ping controllato per lo staff
- cartellino ore staff con log, reset e archivio
- richiami staff con ruolo temporaneo
- ticket multi-sezione con transcript
- reminder DISBOARD dopo un bump riuscito
- notifiche YouTube Castamaggic
- permessi staff configurabili tramite ruoli

## Come avviare

Installa le dipendenze:

```powershell
py -m pip install -r requirements.txt
```

Copia `.env.example` in `.env` e compila token, server ID e ID ruoli/canali:

```powershell
Copy-Item .env.example .env
```

Avvia il bot:

```powershell
py main.py
```

Nel Developer Portal abilita:

- Server Members Intent
- Message Content Intent

Quando inviti il bot nel server, usa gli scope:

- `bot`
- `applications.commands`

Il ruolo del bot deve stare sopra ai ruoli che deve assegnare o rimuovere, per esempio ruolo verifica, ruoli richiamo e ruoli temporanei.

## Come usare i comandi

Tutti i comandi sono slash command: in Discord scrivi `/`, scegli il comando dal menu, compila i parametri richiesti e invia.

Molte risposte sono `ephemeral`, quindi visibili solo a chi usa il comando. I canali, ruoli e utenti si selezionano direttamente dall'autocomplete di Discord.

I comandi di configurazione richiedono permessi staff, gestione server oppure ruoli manager previsti dal codice. Gli utenti normali usano soprattutto i pulsanti di verifica/ticket e i comandi personali come `/my_hours`.

## Comandi base

| Comando | Chi lo usa | Cosa fa | Come farlo |
| --- | --- | --- | --- |
| `/help_base` | Tutti | Mostra una lista veloce dei comandi principali. | Scrivi `/help_base`. |

## Verifica

| Comando | Chi lo usa | Cosa fa | Come farlo |
| --- | --- | --- | --- |
| `/setup_verification` | Staff | Imposta opzionalmente il ruolo e invia nel canale attuale un pannello con pulsante di verifica. | `/setup_verification ruolo:@Membro titolo:<titolo> testo:<testo>` oppure usa i valori default. |
| `/verification_set_role` | Staff | Imposta il ruolo assegnato dal pulsante verifica. | `/verification_set_role ruolo:@Membro`. |

Pulsante:

| Pulsante | Cosa fa |
| --- | --- |
| `Verificati!!` | Assegna all'utente il ruolo configurato in `VERIFIED_ROLE_ID`. |

Note:

- Il ruolo verifica deve esistere e puo essere impostato con `/setup_verification ruolo:@Ruolo` oppure `/verification_set_role`.
- Il ruolo del bot deve stare sopra al ruolo verifica.
- Il comando reale e' `/setup_verification`.

## Cartellino staff e ore

| Comando | Chi lo usa | Cosa fa | Come farlo |
| --- | --- | --- | --- |
| `/cartellino_panel` | Manager ore | Invia il pannello cartellino in un canale. | `/cartellino_panel canale:#staff logs:#log-cartellino`. `canale` e `logs` sono opzionali. |
| `/cartellino_set_logs` | Manager ore | Imposta il canale log per aperture, chiusure e annullamenti. | `/cartellino_set_logs canale:#log-cartellino`. |
| `/clock_in` | Staff | Apre il tuo cartellino. | Scrivi `/clock_in` quando inizi il turno. |
| `/clock_out` | Staff | Chiude il tuo cartellino e salva i minuti. | Scrivi `/clock_out` quando finisci il turno. |
| `/my_hours` | Staff | Mostra le tue ore totali e se hai un turno aperto. | Scrivi `/my_hours`. |
| `/hours` | Manager ore | Mostra le ore di un membro staff. | `/hours staff:@utente`. |
| `/hours_reset` | Manager ore | Azzera le ore di uno staff e archivia il totale precedente. | `/hours_reset staff:@utente motivo:<motivo>`. |
| `/cartellino_annulla` | Manager ore | Annulla un cartellino aperto o l'ultimo timbro. | `/cartellino_annulla staff:@utente tipo:<Cartellino aperto/Ultimo timbro> motivo:<motivo>`. |
| `/staff_archive` | Manager ore | Mostra archivio ore, reset, timbri annullati e richiami. | `/staff_archive staff:@utente`. |

Pulsanti del pannello cartellino:

| Pulsante | Cosa fa |
| --- | --- |
| `Apri cartellino` | Equivale a `/clock_in`. |
| `Chiudi cartellino` | Equivale a `/clock_out`. |
| `Aperti ora` | Mostra chi ha un cartellino aperto in quel momento. |

Note:

- Il bot impedisce di aprire due cartellini contemporaneamente.
- I minuti vengono arrotondati almeno a 1 minuto se il turno ha durata positiva.
- I log vengono inviati solo se hai configurato il canale log.

## Richiami staff

| Comando | Chi lo usa | Cosa fa | Come farlo |
| --- | --- | --- | --- |
| `/staff_richiamo_roles` | Manager ore | Decide quali ruoli possono dare richiami staff. | `/staff_richiamo_roles ruolo_1:@Admin ruolo_2:@Manager ruolo_3:@Tecnico`. |
| `/staff_richiamo` | Ruoli autorizzati | Assegna un ruolo temporaneo a uno staff e salva il richiamo. | `/staff_richiamo staff:@utente ruolo:@Richiamo durata:2h motivo:<motivo>`. |

Formati durata supportati:

- `30m`
- `2h`
- `1d`
- `3d`
- `1d2h`

Il bot prova a rimuovere automaticamente il ruolo allo scadere della durata. Se il bot si riavvia, ripristina i richiami ancora pendenti dal database.

## Ticket

Tipi ticket disponibili:

| Valore | Nome visibile | Uso |
| --- | --- | --- |
| `reports_utenti` | Reports Utenti | Segnalazioni verso altri utenti che violano il regolamento o i tos di discord. |
| `reports_staff` | Reports Staff | Supporto verso i membri dello staff che violano il regolamento o la buona disciplina. |
| `supporto_generale` | Supporto Generale | Posto dove chiedere o chiarire dubbi, domande, perplessita e riscuotere vantaggi tratti da abbonamenti. |
| `partnership` | Partnership | Posto dove inviare richieste di Partnership tra il server di proprieta/gestione e il Server dei "kings di CastaMaggic". |

| Comando | Chi lo usa | Cosa fa | Come farlo |
| --- | --- | --- | --- |
| `/ticket_panel` | Manager ticket | Invia il pannello ticket. | `/ticket_panel canale:#ticket titolo:<titolo> descrizione:<testo>`. I parametri sono opzionali. |
| `/ticket_set_roles` | Manager ticket | Imposta i ruoli supporto per un tipo ticket. | `/ticket_set_roles tipo:supporto_generale ruolo_1:@Staff ruolo_2:@Admin`. |
| `/ticket_set_category` | Manager ticket | Imposta la categoria dove creare i canali ticket. | `/ticket_set_category tipo:reports_utenti categoria:<categoria>`. |
| `/ticket_set_transcript` | Manager ticket | Imposta il canale dove inviare i transcript. | `/ticket_set_transcript tipo:reports_utenti canale:#transcript`. |
| `/ticket_set_open_message` | Manager ticket | Personalizza titolo e messaggio del ticket appena aperto. | `/ticket_set_open_message tipo:supporto_generale titolo:<titolo> messaggio:<messaggio>`. |
| `/ticket_reset_open_message` | Manager ticket | Ripristina il messaggio apertura default. | `/ticket_reset_open_message tipo:supporto_generale`. |
| `/ticket_settings` | Manager ticket | Mostra configurazione ticket attuale. | Scrivi `/ticket_settings`. |
| `/close_ticket` | Owner ticket, supporto o staff | Chiude il ticket corrente, salva transcript e cancella il canale. | Dentro al canale ticket: `/close_ticket motivo:<motivo>`. |

Pulsanti:

| Pulsante | Cosa fa |
| --- | --- |
| `Reports Utenti` | Apre un modulo per creare un ticket report utenti. |
| `Reports Staff` | Apre un modulo per creare un ticket report staff. |
| `Supporto Generale` | Apre un modulo per un ticket supporto. |
| `Partnership` | Apre un modulo per partnership. |
| `Chiudi ticket` | Chiude il ticket come `/close_ticket` con motivo standard. |

Placeholder per `/ticket_set_open_message`:

| Placeholder | Significato |
| --- | --- |
| `{ticket_id}` | ID interno del ticket. |
| `{type}` | Tipo ticket leggibile. |
| `{user}` | Menzione dell'utente che apre il ticket. |
| `{user_name}` | Nome utente. |
| `{subject}` | Oggetto inserito nel modulo. |
| `{description}` | Descrizione inserita nel modulo. |
| `{support}` | Menzioni dei ruoli supporto. |

Note:

- Ogni utente puo avere un solo ticket aperto per lo stesso tipo.
- Alla chiusura viene generato un transcript `.txt` degli ultimi messaggi letti dal canale.
- Il bot deve poter creare canali, gestire canali, leggere cronologia e inviare file.

## DISBOARD

| Comando | Chi lo usa | Cosa fa | Come farlo |
| --- | --- | --- | --- |
| `/disboard_set_timer` | Staff o gestione server | Imposta dopo quanti minuti ricordare il bump. | `/disboard_set_timer minuti:120`. Range: 1-1440. |
| `/disboard_status` | Tutti | Mostra il prossimo reminder DISBOARD pendente. | Scrivi `/disboard_status`. |
| `/disboard_cancel` | Staff o gestione server | Cancella i reminder pendenti di un canale. | `/disboard_cancel canale:#bump`. Se non metti il canale usa quello attuale. |

Comportamento automatico:

- Il bot ascolta i messaggi del bot DISBOARD.
- Quando rileva un bump riuscito, salva un reminder.
- Allo scadere del timer pinga chi ha fatto bump, se riesce a riconoscerlo.
- Se non riconosce l'utente, manda un reminder senza ping personale.

## Castamaggic YouTube

| Comando | Chi lo usa | Cosa fa | Come farlo |
| --- | --- | --- | --- |
| `/castamaggic_setup` | Staff | Configura notifiche nuovo video. | `/castamaggic_setup youtube_channel_id:UC... canale:#video ruolo:@YouTube intervallo_minuti:30 annuncia_ultimo:false messaggio:<testo>`. |
| `/castamaggic_check` | Staff | Controlla subito se c'e' un nuovo video. | `/castamaggic_check annuncia_anche_se_gia_visto:false`. |
| `/castamaggic_status` | Tutti | Mostra configurazione Castamaggic. | Scrivi `/castamaggic_status`. |
| `/castamaggic_set_channel` | Staff | Cambia canale notifiche video. | `/castamaggic_set_channel canale:#video`. |
| `/castamaggic_set_role` | Staff | Cambia ruolo da pingare. | `/castamaggic_set_role ruolo:@YouTube`. |
| `/castamaggic_clear_role` | Staff | Rimuove il ping ruolo. | Scrivi `/castamaggic_clear_role`. |
| `/castamaggic_set_youtube` | Staff | Cambia ID canale YouTube. | `/castamaggic_set_youtube youtube_channel_id:UC...`. |
| `/castamaggic_set_interval` | Staff | Cambia intervallo controllo video. | `/castamaggic_set_interval minuti:30`. Range: 5-1440. |
| `/castamaggic_set_message` | Staff | Personalizza il testo dell'annuncio. | `/castamaggic_set_message messaggio:Nuovo video: {title} {url}`. |
| `/castamaggic_toggle` | Staff | Attiva o disattiva le notifiche. | `/castamaggic_toggle attivo:true` oppure `false`. |

Placeholder per il messaggio Castamaggic:

| Placeholder | Significato |
| --- | --- |
| `{title}` | Titolo del video. |
| `{url}` | Link del video. |
| `{published}` | Data pubblicazione presa dal feed. |

Note:

- L'ID canale YouTube di solito inizia con `UC`.
- Il controllo automatico usa il feed XML di YouTube.
- Il messaggio inviato contiene sempre anche il link YouTube, cosi Discord puo' mostrare l'anteprima del video.
- Se il video e' gia stato visto, non viene annunciato di nuovo, salvo forzatura con `/castamaggic_check annuncia_anche_se_gia_visto:true`.
- Se il bot era spento e nel feed ci sono piu' video nuovi, li annuncia dal piu' vecchio al piu' recente.

## Spam ping controllato

| Comando | Chi lo usa | Cosa fa | Come farlo |
| --- | --- | --- | --- |
| `/spam_ping` | Staff | Pinga un utente o un ruolo da 1 a 5 volte con pausa di 1 secondo. | `/spam_ping membro:@utente volte:3 messaggio:ti stanno cercando` oppure `/spam_ping ruolo:@Ruolo volte:3 messaggio:ti stanno cercando`. |

Note:

- Non puo pingare altri bot.
- Ha cooldown: 1 uso ogni 90 secondi.
- Permette ping a ruoli, ma non a `@everyone` o ruoli gestiti automaticamente.

## Risposte automatiche

Il bot risponde automaticamente quando viene menzionato direttamente in un messaggio.

Esempio:

```txt
@MaggikaBot
```

Risponde con una frase casuale e una GIF. Non risponde ai bot e ignora `@everyone`.

## Permessi e ruoli

Ci sono tre concetti importanti:

| Concetto | Come funziona |
| --- | --- |
| Staff generale | Admin oppure ruoli indicati in `STAFF_ROLE_IDS`. |
| Manager ore | Admin, `manage_guild` oppure ruoli manager hardcoded nel modulo ore. |
| Manager ticket | Admin, `manage_guild` oppure ruoli manager hardcoded nel modulo ticket. |

Per configurare bene il bot:

- Metti in `.env` gli ID principali del server.
- Controlla che il bot abbia i permessi necessari nei canali.
- Tieni il ruolo del bot sopra ai ruoli che deve assegnare.
- Dopo modifiche ai comandi slash, riavvia il bot e aspetta la sincronizzazione.

## Variabili `.env`

| Variabile | Uso |
| --- | --- |
| `DISCORD_TOKEN` | Token del bot. |
| `GUILD_ID` | ID del server dove sincronizzare subito gli slash command. |
| `VERIFIED_ROLE_ID` | Ruolo assegnato dal pulsante verifica. |
| `STAFF_ROLE_IDS` | Ruoli considerati staff generale, separati da virgola. |
| `DISBOARD_BOT_ID` | ID del bot DISBOARD, default `302050872383242240`. |
| `DISBOARD_REMINDER_MINUTES` | Timer default del reminder bump. |
| `CASTAMAGIC_CHANNEL_ID` | Canale notifiche Castamaggic usato come fallback automatico se manca una configurazione nel database. |
| `CASTAMAGIC_ROLE_ID` | Ruolo da pingare per Castamaggic nel fallback automatico. |
| `DB_PATH` | Percorso database SQLite, default `maggika.sqlite3`. |

Le configurazioni operative restano salvate soprattutto tramite comandi slash nel database. Se pero' `CASTAMAGIC_CHANNEL_ID` e' valorizzata e non esiste ancora una riga Castamaggic nel database, il bot crea automaticamente una configurazione base usando il canale YouTube predefinito.

Alcune variabili storiche come `REPORT_CHANNEL_ID` e `TICKET_CATEGORY_ID` sono presenti nell'esempio, ma non sostituiscono la configurazione tramite comandi.

## Database

Il bot usa SQLite. Il file default e':

```txt
maggika.sqlite3
```

Tabelle principali:

- `time_entries`: timbri cartellino.
- `hours_settings`: pannello/log ore e ruoli autorizzati ai richiami.
- `hours_resets`: reset ore archiviati.
- `hours_voids`: timbri annullati.
- `staff_warnings`: richiami staff temporanei.
- `tickets`: ticket aperti/chiusi.
- `ticket_settings`: ruoli, categorie e transcript per tipo ticket.
- `ticket_messages`: messaggi apertura personalizzati.
- `disboard_reminders`: reminder bump.
- `disboard_settings`: timer DISBOARD.
- `castamaggic_settings`: configurazione notifiche YouTube.
- `verification_settings`: ruolo assegnato dal pulsante verifica.

## Flusso consigliato prima configurazione

1. Compila `.env`.
2. Avvia il bot con `py main.py`.
3. Usa `/setup_verification ruolo:@Membro` nel canale verifica.
4. Se devi solo cambiare ruolo dopo, usa `/verification_set_role`.
5. Usa `/cartellino_panel` nel canale staff e imposta i log.
6. Usa `/ticket_settings` per vedere i default ticket.
7. Configura ticket con `/ticket_set_roles`, `/ticket_set_category` e `/ticket_set_transcript`.
8. Invia il pannello con `/ticket_panel`.
9. Imposta DISBOARD con `/disboard_set_timer minuti:120`.
10. Configura YouTube con `/castamaggic_setup`.
