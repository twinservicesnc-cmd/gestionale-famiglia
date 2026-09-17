GESTIONALE FAMIGLIA - VERSIONE 1

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
