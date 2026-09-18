"""Copia sicura dei caricamenti fotocamera Dropbox nell'archivio Google Drive."""
from __future__ import annotations

import io, json, mimetypes, os, re, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

DROPBOX_API = "https://api.dropboxapi.com/2"
DROPBOX_CONTENT = "https://content.dropboxapi.com/2"
MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp", ".mov", ".mp4", ".m4v", ".avi", ".3gp", ".mts", ".m2ts"}

def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value: raise RuntimeError(f"Manca il secret GitHub {name}")
    return value

def clean_folder(value: str) -> str:
    return (re.sub(r"[\\/:*?\"<>|]", "-", value).strip(" .")[:120] or "DA_CLASSIFICARE")

def dropbox_token() -> str:
    response = requests.post("https://api.dropboxapi.com/oauth2/token", data={
        "grant_type": "refresh_token", "refresh_token": required("DROPBOX_REFRESH_TOKEN"),
        "client_id": required("DROPBOX_APP_KEY"), "client_secret": required("DROPBOX_APP_SECRET"),
    }, timeout=45)
    if not response.ok:
        try:
            detail = response.json()
        except Exception:
            detail = response.text[:500]
        raise RuntimeError(f"Dropbox OAuth {response.status_code}: {detail}")
    return response.json()["access_token"]

def dbx_post(endpoint: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(f"{DROPBOX_API}/{endpoint}", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload, timeout=90)
    if not response.ok: raise RuntimeError(f"Dropbox {endpoint}: {response.status_code} {response.text[:500]}")
    return response.json()

def list_dropbox_files(token: str, source: str) -> list[dict[str, Any]]:
    result = dbx_post("files/list_folder", token, {"path": source, "recursive": True, "limit": 2000})
    entries = list(result.get("entries", []))
    while result.get("has_more"):
        result = dbx_post("files/list_folder/continue", token, {"cursor": result["cursor"]})
        entries.extend(result.get("entries", []))
    files = [x for x in entries if x.get(".tag") == "file" and Path(x.get("name", "")).suffix.lower() in MEDIA_EXTENSIONS]
    return sorted(files, key=lambda x: (x.get("client_modified", ""), x.get("path_lower", "")))

def download_dropbox(token: str, path: str, destination: str) -> None:
    with requests.post(f"{DROPBOX_CONTENT}/files/download", headers={"Authorization": f"Bearer {token}", "Dropbox-API-Arg": json.dumps({"path": path})}, stream=True, timeout=300) as response:
        response.raise_for_status()
        with open(destination, "wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                if chunk: output.write(chunk)
def delete_dropbox(token: str, path: str) -> None:
    dbx_post("files/delete_v2", token, {"path": path})

def drive_service():
    credentials = Credentials(token=None, refresh_token=required("GDRIVE_REFRESH_TOKEN"), token_uri="https://oauth2.googleapis.com/token", client_id=required("GDRIVE_CLIENT_ID"), client_secret=required("GDRIVE_CLIENT_SECRET"))
    credentials.refresh(Request())
    return build("drive", "v3", credentials=credentials, cache_discovery=False)

def drive_folder(service, name: str, parent: str) -> str:
    safe = name.replace("'", "")
    query = f"name='{safe}' and mimeType='application/vnd.google-apps.folder' and trashed=false and '{parent}' in parents"
    found = service.files().list(q=query, fields="files(id)", pageSize=1).execute().get("files", [])
    if found: return found[0]["id"]
    return service.files().create(body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent]}, fields="id").execute()["id"]

def drive_path(service, root: str, parts: list[str]) -> str:
    parent = root
    for part in parts: parent = drive_folder(service, clean_folder(part), parent)
    return parent

def find_by_dropbox_hash(service, content_hash: str) -> dict[str, Any] | None:
    safe_hash = re.sub(r"[^a-fA-F0-9]", "", content_hash)
    if not safe_hash: return None
    query = f"appProperties has {{ key='dropbox_content_hash' and value='{safe_hash}' }} and trashed=false"
    files = service.files().list(q=query, spaces="drive", fields="files(id,name,size)", pageSize=1).execute().get("files", [])
    return files[0] if files else None

def read_family_database(service, root: str) -> dict[str, Any]:
    data_folder = drive_path(service, root, ["DATI"])
    query = f"name='gestionale_famiglia_live.json' and trashed=false and '{data_folder}' in parents"
    files = service.files().list(q=query, fields="files(id)", pageSize=1).execute().get("files", [])
    if not files: return {}
    buffer = io.BytesIO(); downloader = MediaIoBaseDownload(buffer, service.files().get_media(fileId=files[0]["id"])); done = False
    while not done: _, done = downloader.next_chunk()
    return json.loads(buffer.getvalue().decode("utf-8"))

def event_for_date(database: dict[str, Any], iso_date: str, person: str) -> str:
    events = []
    for item in database.get("calendario", []):
        if str(item.get("data", "")) != iso_date: continue
        assigned = str(item.get("persona", "")).casefold()
        if assigned and assigned not in {"tutta la famiglia", person.casefold()}: continue
        title = clean_folder(str(item.get("titolo", "")))
        if title and title not in events: events.append(title)
    return " + ".join(events[:3]) if events else "DA_CLASSIFICARE"

def capture_datetime(path: str, metadata: dict[str, Any]) -> datetime:
    if Path(path).suffix.lower() in {".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp"}:
        try:
            from PIL import Image, ExifTags
            with Image.open(path) as image:
                names = {ExifTags.TAGS.get(key, key): value for key, value in image.getexif().items()}
                raw = names.get("DateTimeOriginal") or names.get("DateTimeDigitized") or names.get("DateTime")
                if raw: return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
        except Exception: pass
    raw = metadata.get("client_modified") or metadata.get("server_modified")
    if raw: return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone()
    return datetime.now(timezone.utc).astimezone()

def upload_verified(service, local_path: str, metadata: dict[str, Any], parent: str, person: str) -> dict[str, Any]:
    mime = mimetypes.guess_type(metadata["name"])[0] or "application/octet-stream"
    body = {"name": metadata["name"], "parents": [parent], "appProperties": {
        "dropbox_content_hash": metadata.get("content_hash", ""), "dropbox_path": metadata.get("path_lower", "")[:120], "family_person": person,
    }}
    created = service.files().create(body=body, media_body=MediaFileUpload(local_path, mimetype=mime, resumable=True), fields="id,name,size,webViewLink").execute()
    remote = service.files().get(fileId=created["id"], fields="id,name,size,webViewLink").execute()
    if int(remote.get("size", -1)) != os.path.getsize(local_path): raise RuntimeError(f"Verifica dimensione fallita per {metadata['name']}")
    return remote

def main() -> int:
    token = dropbox_token()
    service = drive_service()
    root = required("GDRIVE_FOLDER_ID")

    person = os.environ.get("DROPBOX_PERSONA", "Papà").strip() or "Papà"
    source = os.environ.get(
        "DROPBOX_SOURCE_PATH",
        "/Caricamenti da fotocamera",
    ).strip()
    limit = max(1, min(int(os.environ.get("SYNC_MAX_FILES", "50")), 500))

    database = read_family_database(service, root)
    files = list_dropbox_files(token, source)

    print(
        f"Trovati {len(files)} file multimediali in Dropbox; "
        f"massimo per esecuzione: {limit}"
    )

    copied = 0
    skipped = 0
    deleted = 0
    failed = 0
    processed = 0

    for item in files:
        if processed >= limit:
            break

        processed += 1

        try:
            content_hash = item.get("content_hash", "")
            existing = find_by_dropbox_hash(service, content_hash)

            if existing:
                dropbox_size = int(item.get("size", -1))
                drive_size = int(existing.get("size", -2))

                if dropbox_size < 0 or drive_size != dropbox_size:
                    raise RuntimeError(
                        f"Dimensione non coincidente per {item['name']}: "
                        f"Dropbox={dropbox_size}, Drive={drive_size}"
                    )

                delete_dropbox(token, item["path_lower"])
                print(
                    f"GIÀ VERIFICATO SU DRIVE E RIMOSSO DA DROPBOX: "
                    f"{item['name']}"
                )
                skipped += 1
                deleted += 1
                continue

            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=Path(item["name"]).suffix,
            ) as temp:
                temp_path = temp.name

            try:
                download_dropbox(
                    token,
                    item["path_lower"],
                    temp_path,
                )

                taken = capture_datetime(temp_path, item)
                iso_date = taken.date().isoformat()
                event = event_for_date(database, iso_date, person)

                destination = drive_path(
                    service,
                    root,
                    [
                        "ARCHIVIO",
                        person,
                        str(taken.year),
                        f"{iso_date} - {event}",
                        "Foto e Video",
                    ],
                )

                uploaded = upload_verified(
                    service,
                    temp_path,
                    item,
                    destination,
                    person,
                )

                delete_dropbox(token, item["path_lower"])

                print(
                    f"COPIATO, VERIFICATO E RIMOSSO DA DROPBOX: "
                    f"{item['name']} -> {iso_date} - {event} "
                    f"({uploaded['id']})"
                )

                copied += 1
                deleted += 1

            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

        except Exception as exc:
            failed += 1
            print(
                f"ERRORE {item.get('name', '')}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    print(
        f"Risultato: elaborati={processed}, copiati={copied}, "
        f"già_presenti={skipped}, rimossi_da_dropbox={deleted}, "
        f"errori={failed}"
    )

    return 1 if failed else 0
if __name__ == "__main__": raise SystemExit(main())
