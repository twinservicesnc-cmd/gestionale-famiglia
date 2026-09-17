GESTIONALE FAMIGLIA - VERSIONE 7

NOVITA VERSIONE 7
- Importazione semiautomatica di foto e filmati tramite Google Photos Picker.
- Selezione multipla su Google Foto e copia automatica nell'archivio Drive.
- Controllo anti-duplicato basato sull'identificativo Google Foto.
- Download temporaneo protetto e rimozione automatica dei file locali.

NOVITA VERSIONE 6
- Salvataggio automatico del database su Google Drive dopo ogni modifica.
- Recupero automatico dei dati live da Google Drive all'avvio.
- Backup giornaliero automatico nella cartella BACKUP/AUTOMATICI.
- Archivio organizzato in ARCHIVIO/ANNO/EVENTO/Foto e Video o Documenti.
- Filtri archivio per anno ed evento.
- Budget mensile, stato delle scadenze e delle faccende.

L'interfaccia e responsive ed e utilizzabile da computer, smartphone e tablet.
Su telefono o tablet aprire l'indirizzo dell'app nel browser e scegliere
"Aggiungi alla schermata Home" per avere un'icona simile a un'app installata.

Avvio locale:
  pip install -r requirements.txt
  streamlit run app.py

Primo accesso:
  utente: admin
  password: admin123

Cambiare subito le password dalla sezione Amministrazione.

Google Drive, in .streamlit/secrets.toml:

[gcp_service_account]
content = """
{ JSON DEL SERVICE ACCOUNT }
"""

[gcp_famiglia]
folder_id = "ID_CARTELLA_PRINCIPALE_GOOGLE_DRIVE"

Condividere la cartella Drive con l'indirizzo e-mail del service account.

Versione 2: normalizzazione automatica della chiave privata PEM nei Secrets
Streamlit, compatibile con a-capo reali e sequenze \\n.

Versione 3: lettura compatibile con JSON che contiene caratteri di controllo
generati dalla conversione TOML della chiave privata.

Versione 4: accesso Google Drive tramite OAuth personale, con service account
come alternativa. OAuth usa lo spazio del proprietario Gmail.
