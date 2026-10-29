import os, json, base64, io, sys
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
FOLDER = "1Pbfmhfp5onM9XF0dmZBXMeK6w-xfzbDz"
SCOPES = ["https://www.googleapis.com/auth/drive"]
def _env_json(name):
    v = os.environ.get(name, "").strip()
    if not v: return None
    try: return json.loads(v)
    except Exception: return json.loads(base64.b64decode(v))
def can_create():
    """Only the owner's OAuth token can create files: a service account has no Drive storage quota."""
    return _env_json("GOOGLE_OAUTH_JSON") is not None
def creds():
    o = _env_json("GOOGLE_OAUTH_JSON")
    if o:
        from google.oauth2.credentials import Credentials
        return Credentials(None, refresh_token=o["refresh_token"], client_id=o["client_id"],
                           client_secret=o["client_secret"], token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES)
    return service_account.Credentials.from_service_account_info(_env_json("GOOGLE_SERVICE_ACCOUNT_JSON"), scopes=SCOPES)
def svc(): return build("drive", "v3", credentials=creds(), cache_discovery=False)
def list_folder(s, folder=FOLDER):
    out, tok = [], None
    while True:
        r = s.files().list(q=f"'{folder}' in parents and trashed=false", pageSize=1000, pageToken=tok,
            fields="nextPageToken, files(id,name,size,modifiedTime,mimeType,capabilities/canEdit,md5Checksum)",
            supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        out += r["files"]; tok = r.get("nextPageToken")
        if not tok: return out
def download(s, fid, path):
    req = s.files().get_media(fileId=fid, supportsAllDrives=True)
    with io.FileIO(path, "wb") as fh:
        d = MediaIoBaseDownload(fh, req, chunksize=32*1024*1024); done = False
        while not done: _, done = d.next_chunk()
