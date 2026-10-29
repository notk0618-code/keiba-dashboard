import os, json, base64, io, sys
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
FOLDER = "1Pbfmhfp5onM9XF0dmZBXMeK6w-xfzbDz"
def creds():
    v = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"].strip()
    try: info = json.loads(v)
    except Exception: info = json.loads(base64.b64decode(v))
    return service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
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
