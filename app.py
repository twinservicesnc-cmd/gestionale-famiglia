import streamlit as st
import json, os, io, zipfile, hashlib, secrets, uuid
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
    db = {"versione": 1, "famiglia": "La nostra famiglia", "utenti": {}, "config": {"drive_folder_id": ""}}
    for username, nome, ruolo, pwd in utenti:
        db["utenti"][username] = {"nome": nome, "ruolo": ruolo, "password": password_hash(pwd), "attivo": True}
    for c in COLLEZIONI: db[c] = []
    return db

def carica():
    if not DATA.exists():
        salva(nuovo_db())
    try:
        db = json.loads(DATA.read_text(encoding="utf-8"))
    except Exception:
        db = nuovo_db(); salva(db)
    for c in COLLEZIONI: db.setdefault(c, [])
    db.setdefault("utenti", {})
    db.setdefault("config", {"drive_folder_id": ""})
    return db

def salva(db):
    tmp = DATA.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, DATA)

def oggi(): return date.today().isoformat()
def nuovo_id(): return uuid.uuid4().hex
def admin(): return st.session_state.get("ruolo") == "amministratore"
def utente(): return st.session_state.get("username", "")

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
        return build("drive", "v3", credentials=cred, cache_discovery=False)
    except Exception as e:
        raise RuntimeError(f"Google Drive non configurato: {e}")

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

def drive_upload(db, file, percorso):
    from googleapiclient.http import MediaIoBaseUpload
    srv, parent = drive_service(), drive_root(db)
    if not parent: raise RuntimeError("Manca [gcp_famiglia] folder_id nei Secrets.")
    for nome in percorso: parent = drive_cartella(srv, nome, parent)
    media = MediaIoBaseUpload(io.BytesIO(file.getvalue()), mimetype=file.type or "application/octet-stream", resumable=True)
    meta = {"name": file.name, "parents": [parent]}
    out = srv.files().create(body=meta, media_body=media, fields="id,webViewLink,name").execute()
    return out

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
    a,b,c=st.columns(3); a.metric("Entrate",f"€ {entrate:,.2f}"); b.metric("Spese",f"€ {spese:,.2f}"); c.metric("Saldo",f"€ {entrate-spese:,.2f}")
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
    tabella_con_elimina(db,"scadenze",visibili(db["scadenze"]),["data","titolo","note","completata"])

def archivio(db, tipo):
    media = tipo=="media"; st.title("📷 Foto e filmati" if media else "📁 Documenti importanti")
    anno=st.selectbox("Anno",list(range(date.today().year+1,1999,-1))); evento=st.text_input("Evento / categoria"); descrizione=st.text_input("Descrizione")
    files=st.file_uploader("Seleziona file",accept_multiple_files=True,type=None if media else ["pdf","doc","docx","jpg","jpeg","png","xlsx"])
    condiviso=st.checkbox("Visibile alla famiglia",True)
    if st.button("Carica su Google Drive",type="primary",disabled=not files or not evento):
        ok=0
        for f in files:
            try:
                out=drive_upload(db,f,[str(anno),evento,"Foto e Video" if media else "Documenti"])
                registra(db,tipo,{"anno":anno,"evento":evento,"descrizione":descrizione,"nome_file":out["name"],"drive_id":out["id"],"link":out.get("webViewLink","")},condiviso); ok+=1
            except Exception as e: st.error(str(e)); break
        if ok: st.success(f"Caricati {ok} file su Google Drive.")
    righe=visibili(db[tipo]); tabella_con_elimina(db,tipo,righe,["anno","evento","descrizione","nome_file","link"])

def semplice(db, raccolta, titolo, campi, condiviso_default):
    st.title(titolo)
    with st.form("f_"+raccolta):
        vals={}
        for key,label,kind in campi:
            vals[key]=st.date_input(label) if kind=="date" else st.text_area(label) if kind=="area" else st.text_input(label)
        condiviso=st.checkbox("Condiviso",condiviso_default)
        if st.form_submit_button("Salva") and str(vals[campi[0][0]]).strip():
            vals={k:str(v) for k,v in vals.items()}; registra(db,raccolta,vals,condiviso); st.rerun()
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

info=db["utenti"][utente()]
with st.sidebar:
    st.title("🏠 Gestionale Famiglia"); st.write(f"👤 **{info['nome']}**"); st.caption(info["ruolo"].title())
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
