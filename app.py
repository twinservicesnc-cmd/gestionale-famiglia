import streamlit as st
import json, os, io, hashlib, secrets, uuid, tempfile, mimetypes, re
from pathlib import Path
from datetime import date, datetime

st.set_page_config(page_title="Gestionale Famiglia", page_icon="🏠", layout="wide")
st.markdown("""
<style>
.stButton>button, .stDownloadButton>button {min-height:44px;width:100%}
[data-testid="stDataFrame"] {overflow-x:auto}
@media (max-width: 768px) {
  .block-container {padding:1rem .65rem 4rem .65rem!important}
  h1 {font-size:1.65rem!important} h2 {font-size:1.3rem!important}
  [data-testid="stHorizontalBlock"] {flex-wrap:wrap!important;gap:.4rem!important}
  [data-testid="column"] {min-width:100%!important;flex:1 1 100%!important}
  [data-testid="stSidebar"] {min-width:82vw!important;max-width:82vw!important}
  input, textarea, select, button {font-size:16px!important}
}
</style>
""", unsafe_allow_html=True)
DATA = Path("famiglia_data.json")

SEZIONI = {
    "📊 Dashboard": "dashboard", "📅 Calendario": "calendario", "💶 Finanze": "finanze",
    "🛒 Lista della spesa": "spesa", "⏰ Scadenze": "scadenze", "📷 Foto e video": "media",
    "📁 Documenti": "documenti", "🎓 Scuola e sport": "attivita", "🩺 Salute": "salute",
    "🧹 Faccende": "faccende", "⚙️ Amministrazione": "admin", "💾 Backup": "backup"
}
COLLEZIONI = ["calendario", "movimenti", "spesa", "scadenze", "media", "documenti", "attivita", "salute", "faccende"]

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180000).hex()
    return salt + ":" + digest

def password_ok(password, encoded):
    try:
        salt, expected = encoded.split(":", 1)
        return secrets.compare_digest(password_hash(password, salt).split(":", 1)[1], expected)
    except Exception:
        return False

def nuovo_db():
    utenti = [
        ("admin", "Papà", "amministratore", "admin123"),
        ("mamma", "Mamma", "amministratore", "mamma123"),
        ("figlia24", "Figlia 24 anni", "adulto", "figlia24123"),
        ("figlia17", "Figlia 17 anni", "figlio", "figlia17123"),
        ("figlia10", "Figlia 10 anni", "figlio", "figlia10123"),
    ]
    db = {"versione": 2, "famiglia": "La nostra famiglia", "utenti": {}, "config": {"drive_folder_id": "", "budget_mensile": 0.0, "ultimo_backup_giornaliero": ""}}
    for username, nome, ruolo, pwd in utenti:
        db["utenti"][username] = {"nome": nome, "ruolo": ruolo, "password": password_hash(pwd), "attivo": True}
    for c in COLLEZIONI: db[c] = []
    return db

def carica():
    if not DATA.exists():
        salva(nuovo_db(), sincronizza=False)
    try:
        db = json.loads(DATA.read_text(encoding="utf-8"))
    except Exception:
        db = nuovo_db(); salva(db, sincronizza=False)
    try:
        remoto = drive_carica_db(db)
        if remoto:
            db = remoto
            salva(db, sincronizza=False)
            st.session_state["drive_sync_status"] = "Dati aggiornati da Google Drive"
    except Exception as exc:
        st.session_state["drive_sync_error"] = str(exc)
    for c in COLLEZIONI: db.setdefault(c, [])
    db.setdefault("utenti", {})
    db.setdefault("config", {})
    db["config"].setdefault("drive_folder_id", "")
    db["config"].setdefault("budget_mensile", 0.0)
    db["config"].setdefault("ultimo_backup_giornaliero", "")
    return db

def salva(db, sincronizza=True):
    tmp = DATA.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, DATA)
    if sincronizza:
        try:
            drive_salva_db(db)
            st.session_state["drive_sync_status"] = f"Salvato su Google Drive alle {datetime.now().strftime('%H:%M:%S')}"
            st.session_state.pop("drive_sync_error", None)
        except Exception as exc:
            st.session_state["drive_sync_error"] = str(exc)

def oggi(): return date.today().isoformat()
def nuovo_id(): return uuid.uuid4().hex
def admin(): return st.session_state.get("ruolo") == "amministratore"
def utente(): return st.session_state.get("username", "")

def data_ora_da_nome_file(nome_file):
    """Ricava data e ora dai nomi creati dal telefono."""
    testo = Path(str(nome_file or "")).stem
    trovato = re.search(r"(\d{4}-\d{2}-\d{2})[ _-]+(\d{2})[.:_-](\d{2})[.:_-](\d{2})", testo)
    if trovato:
        return f"{trovato.group(1)} {trovato.group(2)}:{trovato.group(3)}:{trovato.group(4)}"
    trovato = re.search(r"(\d{4}-\d{2}-\d{2})", testo)
    return trovato.group(1) if trovato else ""

def visibili(righe):
    if admin(): return righe
    u = utente()
    return [r for r in righe if r.get("condiviso", True) or r.get("proprietario") == u or u in r.get("visibile_a", [])]

def registra(db, raccolta, dati, condiviso=True):
    dati.update({"id": nuovo_id(), "proprietario": utente(), "condiviso": bool(condiviso), "creato_il": datetime.now().isoformat(timespec="seconds")})
    db[raccolta].append(dati); salva(db)

def elimina(db, raccolta, item_id):
    db[raccolta] = [x for x in db[raccolta] if x.get("id") != item_id]
    salva(db)

def tabella_con_elimina(db, raccolta, righe, colonne):
    if not righe:
        st.info("Nessun elemento presente."); return
    st.dataframe([{k:r.get(k, "") for k in colonne} for r in righe], use_container_width=True, hide_index=True)
    opzioni = {f"{r.get(colonne[0], '')} · {r.get(colonne[1], '') if len(colonne)>1 else ''} · {r.get('id','')[:6]}": r for r in righe if admin() or r.get("proprietario") == utente()}
    if opzioni:
        scelta = st.selectbox("Elemento da eliminare", [""] + list(opzioni), key="del_"+raccolta)
        if st.button("🗑️ Elimina selezionato", disabled=not scelta, key="btn_del_"+raccolta):
            elimina(db, raccolta, opzioni[scelta]["id"]); st.rerun()

def drive_service():
    oauth_error = None
    oauth_configured = False
    try:
        oauth_section = st.secrets.get("gcp_drive_oauth")
        if oauth_section:
            oauth_configured = True
            oauth = dict(oauth_section)
            content = oauth.get("content", "")
            if content:
                parsed = json.loads(content, strict=False) if isinstance(content, str) else dict(content)
                oauth = {**parsed, **{k:v for k,v in oauth.items() if k != "content"}}
            client_id = str(oauth.get("client_id", "") or "").strip()
            client_secret = str(oauth.get("client_secret", "") or "").strip()
            refresh_token = str(oauth.get("refresh_token", "") or "").strip()
            token_uri = str(oauth.get("token_uri", "https://oauth2.googleapis.com/token") or "https://oauth2.googleapis.com/token").strip()
            if client_id and client_secret and refresh_token:
                from google.oauth2.credentials import Credentials
                from google.auth.transport.requests import Request
                from googleapiclient.discovery import build
                cred = Credentials(token=None, refresh_token=refresh_token, token_uri=token_uri,
                                   client_id=client_id, client_secret=client_secret)
                cred.refresh(Request())
                st.session_state["drive_auth_mode"] = "OAuth personale"
                return build("drive", "v3", credentials=cred, cache_discovery=False)
            oauth_error = "mancano client_id, client_secret o refresh_token"
    except Exception as exc:
        oauth_error = f"{type(exc).__name__}: {exc}"
    if oauth_configured:
        raise RuntimeError(f"OAuth Google Drive non valido: {oauth_error or 'configurazione incompleta'}")
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        raw = st.secrets.get("gcp_service_account", {})
        raw = raw.get("content", raw) if hasattr(raw, "get") else raw
        if isinstance(raw, str):
            raw = raw.lstrip("\ufeff").strip()
            try:
                info = json.loads(raw)
            except json.JSONDecodeError as exc:
                # Alcuni editor/TOML trasformano i \\n della chiave PEM in
                # veri a-capo dentro la stringa JSON. strict=False consente di
                # acquisirli; subito sotto la chiave viene normalizzata.
                if "Invalid control character" not in str(exc):
                    raise
                info = json.loads(raw, strict=False)
        else:
            info = dict(raw)
        # Streamlit/TOML puo conservare gli a-capo della chiave come sequenze
        # letterali. Normalizziamo entrambi i formati prima di creare le credenziali.
        private_key = str(info.get("private_key", ""))
        private_key = private_key.replace("\\\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").strip()
        if private_key:
            info["private_key"] = private_key + "\n"
        cred = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
        st.session_state["drive_auth_mode"] = "Service account"
        return build("drive", "v3", credentials=cred, cache_discovery=False)
    except Exception as e:
        dettaglio = f" OAuth: {oauth_error}." if oauth_error else ""
        raise RuntimeError(f"Google Drive non configurato:{dettaglio} Service account: {e}")

def drive_root(db):
    try: return str(st.secrets.get("gcp_famiglia", {}).get("folder_id", "")).strip() or db["config"].get("drive_folder_id", "")
    except Exception: return db["config"].get("drive_folder_id", "")

def drive_cartella(service, nome, parent):
    q = f"name='{nome.replace(chr(39), '')}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent: q += f" and '{parent}' in parents"
    found = service.files().list(q=q, fields="files(id,name)", pageSize=1).execute().get("files", [])
    if found: return found[0]["id"]
    body = {"name": nome, "mimeType": "application/vnd.google-apps.folder"}
    if parent: body["parents"] = [parent]
    return service.files().create(body=body, fields="id").execute()["id"]

def drive_file(service, nome, parent):
    nome_pulito = nome.replace("'", "")
    q = f"name='{nome_pulito}' and trashed=false and '{parent}' in parents"
    files = service.files().list(q=q, fields="files(id,name,webViewLink,modifiedTime)", pageSize=1).execute().get("files", [])
    return files[0] if files else None

def drive_figli(service, parent, solo_cartelle=False):
    """Elenca tutti i figli non cestinati di una cartella Drive."""
    query = f"'{parent}' in parents and trashed=false"
    if solo_cartelle:
        query += " and mimeType='application/vnd.google-apps.folder'"
    risultati = []
    page_token = None
    while True:
        risposta = service.files().list(
            q=query,
            spaces="drive",
            fields=(
                "nextPageToken,files("
                "id,name,mimeType,size,webViewLink,createdTime,modifiedTime,appProperties)"
            ),
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        risultati.extend(risposta.get("files", []))
        page_token = risposta.get("nextPageToken")
        if not page_token:
            return risultati

def drive_trova_cartella(service, nome, parent):
    nome_pulito = str(nome).replace("'", "")
    query = (
        f"name='{nome_pulito}' and "
        "mimeType='application/vnd.google-apps.folder' and "
        f"trashed=false and '{parent}' in parents"
    )
    trovate = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id,name)",
        pageSize=1,
    ).execute().get("files", [])
    return trovate[0]["id"] if trovate else None

def sincronizza_archivio_dropbox(db, persona="Papà"):
    """Registra nel gestionale i file archiviati dal worker Dropbox."""
    service = drive_service()
    root = drive_root(db)
    if not root:
        raise RuntimeError("Manca [gcp_famiglia] folder_id nei Secrets.")

    archivio_id = drive_trova_cartella(service, "ARCHIVIO", root)
    if not archivio_id:
        return 0, 0
    persona_id = drive_trova_cartella(service, persona, archivio_id)
    if not persona_id:
        return 0, 0

    drive_ids_presenti = {
        str(r.get("drive_id", "")) for r in db.get("media", []) if r.get("drive_id")
    }
    aggiunti = gia_presenti = 0

    for cartella_anno in drive_figli(service, persona_id, solo_cartelle=True):
        anno_nome = str(cartella_anno.get("name", "")).strip()
        anno = int(anno_nome) if anno_nome.isdigit() else anno_nome

        for cartella_evento in drive_figli(
            service, cartella_anno["id"], solo_cartelle=True
        ):
            evento = str(cartella_evento.get("name", "")).strip()
            media_id = drive_trova_cartella(
                service, "Foto e Video", cartella_evento["id"]
            )
            if not media_id:
                continue

            for file_drive in drive_figli(service, media_id):
                if file_drive.get("mimeType") == "application/vnd.google-apps.folder":
                    continue
                drive_id = str(file_drive.get("id", ""))
                if not drive_id:
                    continue
                if drive_id in drive_ids_presenti:
                    gia_presenti += 1
                    continue

                db.setdefault("media", []).append({
                    "anno": anno,
                    "evento": evento,
                    "data_scatto": data_ora_da_nome_file(file_drive.get("name", "")),
                    "descrizione": f"Archivio automatico Dropbox · {persona}",
                    "nome_file": file_drive.get("name", ""),
                    "drive_id": drive_id,
                    "link": file_drive.get("webViewLink", ""),
                    "origine": "Dropbox",
                    "persona": persona,
                    "id": nuovo_id(),
                    "proprietario": utente(),
                    "condiviso": True,
                    "creato_il": datetime.now().isoformat(timespec="seconds"),
                })
                drive_ids_presenti.add(drive_id)
                aggiunti += 1

    if aggiunti:
        salva(db)
    return aggiunti, gia_presenti

@st.cache_data(ttl=300, show_spinner=False)
def drive_leggi_anteprima(file_id):
    """Scarica da Drive un singolo file scelto per mostrarne l'anteprima."""
    from googleapiclient.http import MediaIoBaseDownload
    service = drive_service()
    info = service.files().get(
        fileId=file_id,
        fields="id,name,mimeType,size,webViewLink",
    ).execute()
    dimensione = int(info.get("size", 0) or 0)
    if dimensione > 200 * 1024 * 1024:
        raise RuntimeError("Il file supera 200 MB: aprilo direttamente su Google Drive.")
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, service.files().get_media(fileId=file_id))
    completato = False
    while not completato:
        _, completato = downloader.next_chunk()
    return info, buffer.getvalue()

def drive_rinomina_file(file_id, nuovo_nome):
    """Rinomina il file su Google Drive conservando il collegamento esistente."""
    nome = str(nuovo_nome or "").strip().replace("/", "-").replace("\\", "-")
    if not nome:
        raise ValueError("Inserisci un nome valido.")
    return drive_service().files().update(
        fileId=file_id,
        body={"name": nome},
        fields="id,name,webViewLink",
    ).execute()

def drive_scrivi_bytes(db, contenuto, nome, percorso, mimetype="application/json", sovrascrivi=True):
    from googleapiclient.http import MediaIoBaseUpload
    srv, parent = drive_service(), drive_root(db)
    if not parent: raise RuntimeError("Manca [gcp_famiglia] folder_id nei Secrets.")
    for cartella in percorso: parent = drive_cartella(srv, cartella, parent)
    media = MediaIoBaseUpload(io.BytesIO(contenuto), mimetype=mimetype, resumable=False)
    esistente = drive_file(srv, nome, parent) if sovrascrivi else None
    if esistente:
        return srv.files().update(fileId=esistente["id"], media_body=media, fields="id,webViewLink,name,modifiedTime").execute()
    return srv.files().create(body={"name": nome, "parents": [parent]}, media_body=media, fields="id,webViewLink,name,modifiedTime").execute()

def drive_salva_db(db):
    payload = json.dumps(db, ensure_ascii=False, indent=2).encode("utf-8")
    return drive_scrivi_bytes(db, payload, "gestionale_famiglia_live.json", ["DATI"], sovrascrivi=True)

def drive_carica_db(db_locale):
    from googleapiclient.http import MediaIoBaseDownload
    srv, parent = drive_service(), drive_root(db_locale)
    if not parent: return None
    dati = drive_cartella(srv, "DATI", parent)
    trovato = drive_file(srv, "gestionale_famiglia_live.json", dati)
    if not trovato: return None
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, srv.files().get_media(fileId=trovato["id"]))
    fine = False
    while not fine:
        _, fine = downloader.next_chunk()
    remoto = json.loads(buffer.getvalue().decode("utf-8"))
    return remoto if isinstance(remoto, dict) and isinstance(remoto.get("utenti"), dict) else None

def backup_giornaliero(db):
    giorno = oggi()
    if db["config"].get("ultimo_backup_giornaliero") == giorno: return
    payload = json.dumps(db, ensure_ascii=False, indent=2).encode("utf-8")
    nome = f"gestionale_famiglia_{giorno.replace('-', '')}.json"
    drive_scrivi_bytes(db, payload, nome, ["BACKUP", "AUTOMATICI"], sovrascrivi=True)
    db["config"]["ultimo_backup_giornaliero"] = giorno
    salva(db)

def drive_upload(db, file, percorso):
    from googleapiclient.http import MediaIoBaseUpload
    srv, parent = drive_service(), drive_root(db)
    if not parent: raise RuntimeError("Manca [gcp_famiglia] folder_id nei Secrets.")
    for nome in percorso: parent = drive_cartella(srv, nome, parent)
    media = MediaIoBaseUpload(io.BytesIO(file.getvalue()), mimetype=file.type or "application/octet-stream", resumable=True)
    meta = {"name": file.name, "parents": [parent]}
    out = srv.files().create(body=meta, media_body=media, fields="id,webViewLink,name").execute()
    return out

def drive_upload_path(db, percorso_file, nome_file, mimetype, percorso):
    from googleapiclient.http import MediaFileUpload
    srv, parent = drive_service(), drive_root(db)
    if not parent: raise RuntimeError("Manca [gcp_famiglia] folder_id nei Secrets.")
    for nome in percorso: parent = drive_cartella(srv, nome, parent)
    media = MediaFileUpload(percorso_file, mimetype=mimetype or "application/octet-stream", resumable=True)
    meta = {"name": nome_file, "parents": [parent]}
    return srv.files().create(body=meta, media_body=media, fields="id,webViewLink,name").execute()

def photos_credentials():
    try:
        raw = dict(st.secrets["gcp_photos_oauth"])
        client_id = str(raw.get("client_id", "")).strip()
        client_secret = str(raw.get("client_secret", "")).strip()
        refresh_token = str(raw.get("refresh_token", "")).strip()
        token_uri = str(raw.get("token_uri", "https://oauth2.googleapis.com/token")).strip()
        if not client_id or not client_secret or not refresh_token:
            raise RuntimeError("mancano client_id, client_secret o refresh_token")
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        cred = Credentials(token=None, refresh_token=refresh_token, token_uri=token_uri,
                           client_id=client_id, client_secret=client_secret,
                           scopes=["https://www.googleapis.com/auth/photospicker.mediaitems.readonly"])
        cred.refresh(Request())
        return cred
    except Exception as exc:
        raise RuntimeError(f"Google Foto non configurato: {exc}")

def photos_api(method, endpoint, cred, **kwargs):
    import requests
    headers = dict(kwargs.pop("headers", {}))
    headers["Authorization"] = f"Bearer {cred.token}"
    response = requests.request(method, f"https://photospicker.googleapis.com/v1/{endpoint}", headers=headers, timeout=60, **kwargs)
    if not response.ok:
        try: dettaglio = response.json().get("error", {}).get("message", response.text)
        except Exception: dettaglio = response.text
        raise RuntimeError(f"Google Foto: {response.status_code} {dettaglio}")
    return response.json() if response.content else {}

def photos_crea_sessione():
    cred = photos_credentials()
    sessione = photos_api("POST", "sessions", cred, json={})
    if not sessione.get("id") or not sessione.get("pickerUri"):
        raise RuntimeError("Google Foto non ha restituito una sessione valida.")
    return sessione

def photos_lista_selezionati(session_id, cred):
    elementi, token = [], None
    while True:
        params = {"sessionId": session_id, "pageSize": 100}
        if token: params["pageToken"] = token
        risposta = photos_api("GET", "mediaItems", cred, params=params)
        elementi.extend(risposta.get("mediaItems", []))
        token = risposta.get("nextPageToken")
        if not token: return elementi

def photos_importa_selezione(db, session_id, anno, evento, descrizione, condiviso):
    import requests
    cred = photos_credentials()
    sessione = photos_api("GET", f"sessions/{session_id}", cred)
    if not sessione.get("mediaItemsSet"):
        return 0, 0, False
    elementi = photos_lista_selezionati(session_id, cred)
    gia_presenti = {str(x.get("photos_picker_id")) for x in db["media"] if x.get("photos_picker_id")}
    importati = saltati = 0
    for item in elementi:
        picker_id = str(item.get("id", ""))
        if picker_id and picker_id in gia_presenti:
            saltati += 1; continue
        media_file = item.get("mediaFile", {})
        base_url = str(media_file.get("baseUrl", ""))
        mime = str(media_file.get("mimeType", "application/octet-stream"))
        nome = Path(str(media_file.get("filename") or f"google_foto_{picker_id}{mimetypes.guess_extension(mime) or ''}")).name
        if not base_url: continue
        url = base_url + ("=dv" if mime.startswith("video/") else "=d")
        temp_path = None
        try:
            with requests.get(url, headers={"Authorization": f"Bearer {cred.token}"}, stream=True, timeout=180) as risposta:
                risposta.raise_for_status()
                with tempfile.NamedTemporaryFile(delete=False, suffix=Path(nome).suffix) as temp:
                    temp_path = temp.name
                    totale = 0
                    for blocco in risposta.iter_content(chunk_size=1024*1024):
                        if not blocco: continue
                        totale += len(blocco)
                        if totale > 1024*1024*1024:
                            raise RuntimeError(f"{nome}: file superiore a 1 GB")
                        temp.write(blocco)
            out = drive_upload_path(db, temp_path, nome, mime, ["ARCHIVIO",str(anno),evento,"Foto e Video"])
            dati = {"anno":anno,"evento":evento,"descrizione":descrizione,"nome_file":out["name"],"drive_id":out["id"],"link":out.get("webViewLink",""),"photos_picker_id":picker_id,"origine":"Google Foto"}
            registra(db,"media",dati,condiviso); importati += 1
        finally:
            if temp_path and os.path.exists(temp_path): os.unlink(temp_path)
    try: photos_api("DELETE", f"sessions/{session_id}", cred)
    except Exception: pass
    return importati, saltati, True

def login(db):
    st.title("🏠 Gestionale Famiglia")
    st.caption("Accesso riservato ai componenti della famiglia")
    with st.form("login"):
        user = st.text_input("Utente").strip().lower()
        pwd = st.text_input("Password", type="password")
        entra = st.form_submit_button("Accedi", use_container_width=True)
    if entra:
        info = db["utenti"].get(user)
        if info and info.get("attivo", True) and password_ok(pwd, info.get("password", "")):
            st.session_state.update(username=user, ruolo=info["ruolo"], autenticato=True); st.rerun()
        st.error("Credenziali non valide.")
    st.warning("Primo accesso: admin / admin123. Cambia subito la password da Amministrazione.")

def dashboard(db):
    st.title("📊 Dashboard familiare")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Impegni", len(visibili(db["calendario"])))
    c2.metric("Scadenze aperte", len([x for x in visibili(db["scadenze"]) if not x.get("completata")]))
    saldo = sum(float(x.get("importo",0)) * (1 if x.get("tipo")=="Entrata" else -1) for x in visibili(db["movimenti"]))
    c3.metric("Saldo", f"€ {saldo:,.2f}")
    c4.metric("Spesa da comprare", len([x for x in visibili(db["spesa"]) if not x.get("acquistato")]))
    st.subheader("Prossimi impegni")
    prossimi = sorted([x for x in visibili(db["calendario"]) if x.get("data","") >= oggi()], key=lambda x:x.get("data",""))[:10]
    st.dataframe(prossimi, use_container_width=True, hide_index=True)
    st.subheader("Prossime scadenze")
    prossime_scadenze = sorted([x for x in visibili(db["scadenze"]) if not x.get("completata") and x.get("data", "") >= oggi()], key=lambda x:x.get("data", ""))[:10]
    st.dataframe(prossime_scadenze, use_container_width=True, hide_index=True)

def calendario(db):
    st.title("📅 Calendario e impegni")
    with st.form("f_cal"):
        c1,c2,c3=st.columns(3); titolo=c1.text_input("Impegno"); data=c2.date_input("Data"); ora=c3.time_input("Ora")
        persona=st.selectbox("Persona", ["Tutta la famiglia"]+[x["nome"] for x in db["utenti"].values()]); note=st.text_area("Note"); condiviso=st.checkbox("Condiviso", True)
        if st.form_submit_button("Salva impegno") and titolo:
            registra(db,"calendario",{"titolo":titolo,"data":str(data),"ora":str(ora)[:5],"persona":persona,"note":note},condiviso); st.rerun()
    tabella_con_elimina(db,"calendario",visibili(db["calendario"]),["data","ora","titolo","persona","note"])

def finanze(db):
    st.title("💶 Entrate, spese e budget")
    with st.form("f_fin"):
        c1,c2,c3=st.columns(3); tipo=c1.selectbox("Tipo",["Spesa","Entrata"]); data=c2.date_input("Data"); importo=c3.number_input("Importo €",min_value=0.0,step=1.0)
        c4,c5=st.columns(2); categoria=c4.text_input("Categoria"); descrizione=c5.text_input("Descrizione"); condiviso=st.checkbox("Visibile alla famiglia",False)
        if st.form_submit_button("Registra movimento") and importo>0:
            registra(db,"movimenti",{"tipo":tipo,"data":str(data),"importo":importo,"categoria":categoria,"descrizione":descrizione},condiviso); st.rerun()
    righe=visibili(db["movimenti"]); entrate=sum(float(x.get("importo",0)) for x in righe if x.get("tipo")=="Entrata"); spese=sum(float(x.get("importo",0)) for x in righe if x.get("tipo")=="Spesa")
    mese=oggi()[:7]; spese_mese=sum(float(x.get("importo",0)) for x in righe if x.get("tipo")=="Spesa" and str(x.get("data","")).startswith(mese)); budget=float(db["config"].get("budget_mensile",0) or 0)
    a,b,c,d=st.columns(4); a.metric("Entrate",f"€ {entrate:,.2f}"); b.metric("Spese",f"€ {spese:,.2f}"); c.metric("Saldo",f"€ {entrate-spese:,.2f}"); d.metric("Budget residuo mese",f"€ {budget-spese_mese:,.2f}" if budget else "Non impostato")
    if budget:
        st.progress(min(spese_mese/budget,1.0),text=f"Spese del mese: € {spese_mese:,.2f} su € {budget:,.2f}")
        if spese_mese>budget: st.warning(f"Budget mensile superato di € {spese_mese-budget:,.2f}.")
    tabella_con_elimina(db,"movimenti",righe,["data","tipo","categoria","descrizione","importo"])

def spesa(db):
    st.title("🛒 Lista della spesa")
    with st.form("f_spesa"):
        c1,c2,c3=st.columns(3); articolo=c1.text_input("Articolo"); quantita=c2.text_input("Quantità"); negozio=c3.text_input("Negozio")
        if st.form_submit_button("Aggiungi") and articolo:
            registra(db,"spesa",{"articolo":articolo,"quantita":quantita,"negozio":negozio,"acquistato":False},True); st.rerun()
    for x in visibili(db["spesa"]):
        c1,c2=st.columns([8,1]); nuovo=c1.checkbox(f"{x.get('articolo')} · {x.get('quantita')} · {x.get('negozio')}",value=x.get("acquistato",False),key=x["id"])
        if nuovo != x.get("acquistato",False): x["acquistato"]=nuovo; salva(db); st.rerun()
        if c2.button("🗑️",key="s"+x["id"]): elimina(db,"spesa",x["id"]); st.rerun()

def scadenze(db):
    st.title("⏰ Scadenze e promemoria")
    with st.form("f_scad"):
        c1,c2=st.columns(2); titolo=c1.text_input("Scadenza"); data=c2.date_input("Data"); note=st.text_area("Note"); condiviso=st.checkbox("Condivisa",True)
        if st.form_submit_button("Salva") and titolo: registra(db,"scadenze",{"titolo":titolo,"data":str(data),"note":note,"completata":False},condiviso); st.rerun()
    for x in visibili(db["scadenze"]):
        c1,c2=st.columns([8,1]); nuovo=c1.checkbox(f"{x.get('data')} · {x.get('titolo')} · {x.get('note','')}",value=x.get("completata",False),key="scad_"+x["id"])
        if nuovo != x.get("completata",False): x["completata"]=nuovo; salva(db); st.rerun()
        if c2.button("🗑️",key="scad_del_"+x["id"]): elimina(db,"scadenze",x["id"]); st.rerun()

def archivio(db, tipo):
    media = tipo=="media"; st.title("📷 Foto e filmati" if media else "📁 Documenti importanti")
    anno=st.selectbox("Anno",list(range(date.today().year+1,1999,-1))); evento=st.text_input("Evento / categoria"); descrizione=st.text_input("Descrizione")
    if media:
        st.subheader("📱 Carica dal telefono, tablet o computer")
    files=st.file_uploader("Seleziona file",accept_multiple_files=True,type=None if media else ["pdf","doc","docx","jpg","jpeg","png","xlsx"])
    condiviso=st.checkbox("Visibile alla famiglia",True)
    if st.button("Carica su Google Drive",type="primary",disabled=not files or not evento):
        ok=0
        for f in files:
            try:
                out=drive_upload(db,f,["ARCHIVIO",str(anno),evento,"Foto e Video" if media else "Documenti"])
                registra(db,tipo,{"anno":anno,"evento":evento,"descrizione":descrizione,"nome_file":out["name"],"drive_id":out["id"],"link":out.get("webViewLink","")},condiviso); ok+=1
            except Exception as e: st.error(str(e)); break
        if ok: st.success(f"Caricati {ok} file su Google Drive.")
    if media:
        st.divider(); st.subheader("🖼️ Importa da Google Foto")
        st.caption("Seleziona anche molte foto e filmati insieme; il gestionale li copierà automaticamente nell'evento indicato sopra.")
        if st.button("1. Avvia selezione Google Foto", disabled=not evento, use_container_width=True):
            try:
                sessione=photos_crea_sessione()
                st.session_state["photos_session_id"]=sessione["id"]
                st.session_state["photos_picker_uri"]=sessione["pickerUri"]
            except Exception as exc: st.error(str(exc))
        picker_uri=st.session_state.get("photos_picker_uri")
        session_id=st.session_state.get("photos_session_id")
        if picker_uri and session_id:
            uri=picker_uri.rstrip("/")+"/autoclose"
            st.link_button("2. Apri Google Foto e scegli i file",uri,use_container_width=True)
            if st.button("3. Completa importazione",type="primary",use_container_width=True):
                try:
                    with st.spinner("Importazione da Google Foto e caricamento su Drive..."):
                        importati,saltati,completata=photos_importa_selezione(db,session_id,anno,evento,descrizione,condiviso)
                    if not completata: st.info("La selezione non è ancora terminata in Google Foto. Completala e riprova.")
                    else:
                        st.session_state.pop("photos_session_id",None); st.session_state.pop("photos_picker_uri",None)
                        st.success(f"Importazione completata: {importati} file copiati su Drive"+(f", {saltati} già presenti." if saltati else "."))
                except Exception as exc: st.error(str(exc))
        st.divider()
        st.subheader("☁️ Archivio automatico Dropbox")
        st.caption(
            "Aggiorna l'elenco con le foto e i filmati già copiati in "
            "Google Drive dal collegamento Dropbox. I file non vengono duplicati."
        )
        scelta_dropbox = st.selectbox(
            "Persona da sincronizzare",
            ["Entrambi", "Papà", "Mamma"],
            key="persona_sync_dropbox",
        )
        if st.button(
            "Sincronizza archivio Dropbox da Google Drive",
            use_container_width=True,
        ):
            try:
                with st.spinner("Lettura dell'archivio Google Drive..."):
                    persone = ["Papà", "Mamma"] if scelta_dropbox == "Entrambi" else [scelta_dropbox]
                    aggiunti = gia_presenti = 0
                    for persona_dropbox in persone:
                        nuovi, presenti = sincronizza_archivio_dropbox(db, persona_dropbox)
                        aggiunti += nuovi
                        gia_presenti += presenti
                st.success(
                    f"Sincronizzazione completata: {aggiunti} nuovi file registrati, "
                    f"{gia_presenti} già presenti."
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Sincronizzazione archivio non riuscita: {exc}")
    righe=visibili(db[tipo])
    if media:
        dati_aggiornati = False
        for riga_media in righe:
            if not riga_media.get("data_scatto"):
                data_rilevata = data_ora_da_nome_file(riga_media.get("nome_file", ""))
                if data_rilevata:
                    riga_media["data_scatto"] = data_rilevata
                    dati_aggiornati = True
            titolo_esistente = str(riga_media.get("titolo", "")).strip()
            parole_esistenti = str(riga_media.get("parole_chiave", "")).strip()
            if parole_esistenti and re.fullmatch(r"\d{4}-\d{2}-\d{2}[ .:_-]*\d{2}[ .:_-]*\d{2}[ .:_-]*\d{2}", titolo_esistente):
                riga_media["titolo"] = parole_esistenti
                titolo_esistente = parole_esistenti
                dati_aggiornati = True
            if "DA_CLASSIFICARE" in str(riga_media.get("evento", "")).upper() and titolo_esistente:
                riga_media["evento"] = titolo_esistente
                dati_aggiornati = True
        if dati_aggiornati:
            salva(db)
    if not righe: st.info("Nessun file archiviato."); return
    anni=["Tutti"]+[str(x) for x in sorted({r.get("anno") for r in righe},reverse=True)]
    eventi=["Tutti"]+sorted({str(r.get("evento","")) for r in righe if r.get("evento")})
    filtro_anno=st.selectbox("Filtra per anno",anni,key="anno_"+tipo); filtro_evento=st.selectbox("Filtra per evento",eventi,key="evento_"+tipo)
    filtro_persona = "Tutti"
    if media:
        persone = ["Tutti"] + sorted({str(r.get("persona", "Famiglia")) for r in righe})
        filtro_persona = st.selectbox("Filtra per persona", persone, key="persona_"+tipo)
    filtrate=[r for r in righe if (filtro_anno=="Tutti" or str(r.get("anno"))==filtro_anno) and (filtro_evento=="Tutti" or r.get("evento")==filtro_evento) and (filtro_persona=="Tutti" or str(r.get("persona", "Famiglia"))==filtro_persona)]
    if media and filtrate:
        st.subheader("👁️ Visualizza foto o filmato")
        opzioni_anteprima = {
            " · ".join(filter(None, [
                str(r.get("persona", "Famiglia")),
                str(r.get("categoria", "Da classificare")),
                str(r.get("luogo", "")),
                str(r.get("titolo", r.get("nome_file", "File"))),
                str(r.get("data_scatto", "")),
            ])): r
            for r in filtrate if r.get("drive_id")
        }
        scelta_anteprima = st.selectbox(
            "Scegli il file da visualizzare",
            [""] + list(opzioni_anteprima),
            key="anteprima_media",
        )
        if scelta_anteprima:
            elemento = opzioni_anteprima[scelta_anteprima]
            if elemento.get("link"):
                st.link_button("↗️ Apri su Google Drive", elemento["link"], use_container_width=True)
            try:
                with st.spinner("Caricamento anteprima..."):
                    info_file, contenuto_file = drive_leggi_anteprima(elemento["drive_id"])
                mime = str(info_file.get("mimeType", ""))
                if mime.startswith("image/") and mime not in {"image/heic", "image/heif"}:
                    st.image(contenuto_file, caption=info_file.get("name", "Foto"), use_container_width=True)
                elif mime.startswith("video/"):
                    st.video(contenuto_file, format=mime)
                else:
                    st.info("Anteprima non disponibile per questo formato. Usa il pulsante Apri su Google Drive.")
            except Exception as exc:
                st.warning(f"Anteprima non disponibile: {exc}")
            st.subheader("🏷️ Classifica e rinomina")
            nome_corrente = str(elemento.get("nome_file", "File"))
            estensione = Path(nome_corrente).suffix
            nome_base = Path(nome_corrente).stem
            categorie = [
                "Da classificare", "Famiglia", "Vacanze", "Compleanni",
                "Feste", "Scuola", "Sport", "Viaggi", "Ricordi", "Altro",
            ]
            categoria_corrente = str(elemento.get("categoria", "Da classificare"))
            if categoria_corrente not in categorie:
                categorie.append(categoria_corrente)
            with st.form("classifica_" + str(elemento.get("id", elemento.get("drive_id", "file")))):
                nuovo_luogo = st.text_input(
                    "Luogo (es. Napoli)",
                    value=str(elemento.get("luogo", "")),
                )
                nuovo_titolo = st.text_input(
                    "Titolo (es. Matrimonio Fabio)",
                    value=str(elemento.get("titolo", nome_base)),
                )
                st.text_input(
                    "Data e ora della foto/filmato",
                    value=str(elemento.get("data_scatto") or data_ora_da_nome_file(nome_corrente)),
                    disabled=True,
                )
                nuova_categoria = st.selectbox(
                    "Categoria",
                    categorie,
                    index=categorie.index(categoria_corrente),
                )
                nuove_parole = st.text_input(
                    "Parole chiave (separate da virgola)",
                    value=str(elemento.get("parole_chiave", "")),
                    placeholder="es. mare, estate, nonni",
                )
                rinomina_drive = st.checkbox("Rinomina anche il file su Google Drive", True)
                salva_classificazione = st.form_submit_button(
                    "Salva classificazione",
                    type="primary",
                    use_container_width=True,
                )
            if salva_classificazione:
                titolo_pulito = nuovo_titolo.strip()
                if not titolo_pulito:
                    st.error("Inserisci un titolo.")
                else:
                    try:
                        luogo_pulito = nuovo_luogo.strip()
                        nome_finale = f"{luogo_pulito} - {titolo_pulito}" if luogo_pulito else titolo_pulito
                        if estensione and not nome_finale.lower().endswith(estensione.lower()):
                            nome_finale += estensione
                        if rinomina_drive:
                            risultato_nome = drive_rinomina_file(elemento["drive_id"], nome_finale)
                            elemento["nome_file"] = risultato_nome.get("name", nome_finale)
                        elemento["titolo"] = titolo_pulito
                        elemento["luogo"] = luogo_pulito
                        if "DA_CLASSIFICARE" in str(elemento.get("evento", "")).upper():
                            elemento["evento"] = titolo_pulito
                        elemento["data_scatto"] = elemento.get("data_scatto") or data_ora_da_nome_file(nome_corrente)
                        elemento["categoria"] = nuova_categoria
                        elemento["parole_chiave"] = nuove_parole.strip()
                        elemento["classificato_il"] = datetime.now().isoformat(timespec="seconds")
                        salva(db)
                        st.success("Foto o filmato classificato correttamente.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Classificazione non riuscita: {exc}")
    colonne = ["anno","evento","descrizione","nome_file","link"]
    if media:
        colonne = ["persona", "categoria", "luogo", "titolo", "data_scatto"] + colonne
    tabella_con_elimina(db,tipo,filtrate,colonne)

def semplice(db, raccolta, titolo, campi, condiviso_default):
    st.title(titolo)
    with st.form("f_"+raccolta):
        vals={}
        for key,label,kind in campi:
            vals[key]=st.date_input(label) if kind=="date" else st.text_area(label) if kind=="area" else st.text_input(label)
        condiviso=st.checkbox("Condiviso",condiviso_default)
        if st.form_submit_button("Salva") and str(vals[campi[0][0]]).strip():
            vals={k:str(v) for k,v in vals.items()}; registra(db,raccolta,vals,condiviso); st.rerun()
    if raccolta=="faccende":
        for x in visibili(db[raccolta]):
            c1,c2=st.columns([8,1]); nuovo=c1.checkbox(f"{x.get('data')} · {x.get('titolo')} · {x.get('persona')} · {x.get('note','')}",value=x.get("completata",False),key="fac_"+x["id"])
            if nuovo != x.get("completata",False): x["completata"]=nuovo; salva(db); st.rerun()
            if c2.button("🗑️",key="fac_del_"+x["id"]): elimina(db,raccolta,x["id"]); st.rerun()
    else:
        tabella_con_elimina(db,raccolta,visibili(db[raccolta]),[x[0] for x in campi])

def amministrazione(db):
    st.title("⚙️ Amministrazione")
    if not admin(): st.error("Sezione riservata agli amministratori."); return
    st.subheader("Componenti della famiglia")
    st.dataframe([{"Utente":u,"Nome":x["nome"],"Ruolo":x["ruolo"],"Attivo":x.get("attivo",True)} for u,x in db["utenti"].items()],hide_index=True,use_container_width=True)
    scelto=st.selectbox("Utente da aggiornare",list(db["utenti"])); info=db["utenti"][scelto]
    with st.form("utenti"):
        nome=st.text_input("Nome visualizzato",info["nome"]); ruolo=st.selectbox("Ruolo",["amministratore","adulto","figlio"],index=["amministratore","adulto","figlio"].index(info["ruolo"])); pwd=st.text_input("Nuova password",type="password"); attivo=st.checkbox("Account attivo",info.get("attivo",True))
        if st.form_submit_button("Aggiorna utente"):
            info.update(nome=nome,ruolo=ruolo,attivo=attivo)
            if pwd: info["password"]=password_hash(pwd)
            salva(db); st.success("Utente aggiornato.")
    folder=st.text_input("ID cartella principale Google Drive",db["config"].get("drive_folder_id",""))
    if st.button("Salva configurazione Drive"): db["config"]["drive_folder_id"]=folder.strip(); salva(db); st.success("Configurazione salvata.")
    budget=st.number_input("Budget familiare mensile €",min_value=0.0,value=float(db["config"].get("budget_mensile",0) or 0),step=50.0)
    if st.button("Salva budget mensile"): db["config"]["budget_mensile"]=budget; salva(db); st.success("Budget mensile salvato.")
    st.subheader("Stato Google Drive")
    if st.session_state.get("drive_sync_error"): st.error(st.session_state["drive_sync_error"])
    else: st.success(st.session_state.get("drive_sync_status","Google Drive configurato"))

def backup(db):
    st.title("💾 Backup")
    payload=json.dumps(db,ensure_ascii=False,indent=2).encode()
    st.download_button("Scarica backup JSON",payload,f"gestionale_famiglia_{oggi()}.json","application/json",use_container_width=True)
    if st.button("Crea backup su Google Drive",type="primary"):
        class F:
            name=f"gestionale_famiglia_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"; type="application/json"
            def getvalue(self): return payload
        try:
            out=drive_upload(db,F(),["BACKUP"]); st.success(f"Backup creato: {out['name']}")
        except Exception as e: st.error(str(e))

db=carica()
if not st.session_state.get("autenticato"):
    login(db); st.stop()

try:
    backup_giornaliero(db)
    st.session_state.pop("backup_giornaliero_error",None)
except Exception as exc:
    st.session_state["backup_giornaliero_error"]=str(exc)

info=db["utenti"][utente()]
with st.sidebar:
    st.title("🏠 Gestionale Famiglia"); st.write(f"👤 **{info['nome']}**"); st.caption(info["ruolo"].title())
    if st.session_state.get("drive_sync_error"): st.error("Sincronizzazione Drive non riuscita")
    else: st.success("Google Drive sincronizzato")
    if st.session_state.get("backup_giornaliero_error"): st.warning("Backup giornaliero da verificare")
    opzioni=list(SEZIONI)
    if not admin(): opzioni.remove("⚙️ Amministrazione")
    scelta=st.radio("Menu",opzioni)
    if st.button("Esci",use_container_width=True):
        for k in ["autenticato","username","ruolo"]: st.session_state.pop(k,None)
        st.rerun()

sez=SEZIONI[scelta]
if sez=="dashboard": dashboard(db)
elif sez=="calendario": calendario(db)
elif sez=="finanze": finanze(db)
elif sez=="spesa": spesa(db)
elif sez=="scadenze": scadenze(db)
elif sez in ["media","documenti"]: archivio(db,sez)
elif sez=="attivita": semplice(db,"attivita","🎓 Attività scolastiche e sportive",[("titolo","Attività","text"),("data","Data","date"),("persona","Persona","text"),("note","Note","area")],True)
elif sez=="salute": semplice(db,"salute","🩺 Farmaci e visite mediche",[("titolo","Farmaco / visita","text"),("data","Data","date"),("persona","Persona","text"),("note","Indicazioni","area")],False)
elif sez=="faccende": semplice(db,"faccende","🧹 Faccende domestiche",[("titolo","Faccenda","text"),("data","Scadenza","date"),("persona","Assegnata a","text"),("note","Note","area")],True)
elif sez=="admin": amministrazione(db)
elif sez=="backup": backup(db)
