"""Mirror keiba_db from Drive into a local dir (skips backups and huge raw CSVs). Writes _manifest.json."""
import sys, os, json, re, hashlib
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__)); import gdrive
dst = sys.argv[1]; os.makedirs(dst, exist_ok=True)
SKIP = re.compile(r"_backup_|^ghp_")
s = gdrive.svc(); files = gdrive.list_folder(s)
pick = {}
for f in files:
    if f["mimeType"].startswith("application/vnd.google-apps"): continue
    n = f["name"]; sz = int(f.get("size", 0))
    if SKIP.search(n) or (sz > 60e6 and n != "keiba.duckdb"): continue
    if n not in pick or f["modifiedTime"] > pick[n]["modifiedTime"]: pick[n] = f
def md5(p):
    h = hashlib.md5(); [h.update(b) for b in iter(lambda: open(p,'rb').read(), b'')] if False else None
    with open(p, 'rb') as fh:
        for b in iter(lambda: fh.read(1<<20), b''): h.update(b)
    return h.hexdigest()
def get(f):
    p = os.path.join(dst, f["name"])
    if os.path.exists(p) and f.get("md5Checksum") and md5(p) == f["md5Checksum"]: return
    gdrive.download(gdrive.svc(), f["id"], p)
with ThreadPoolExecutor(8) as ex: list(ex.map(get, pick.values()))
json.dump({n: {k: f.get(k) for k in ("id","modifiedTime","md5Checksum","size")} for n, f in pick.items()},
          open(os.path.join(dst, "..", "_manifest_keiba_db.json"), "w"), ensure_ascii=False, indent=0)
print(f"mirrored {len(pick)} files ({sum(int(f.get('size',0)) for f in pick.values())/1e6:.0f}MB) of {len(files)}")
