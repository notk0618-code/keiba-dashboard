"""Upload changed keiba_db files back to Drive after a weekly run.
Aborts if any target changed on Drive since the mirror was taken (someone ran Colab meanwhile).
keiba.duckdb is checkpointed locally, so the Drive .wal is emptied first (an old WAL replayed onto the
new DB would corrupt it; an empty WAL is ignored by duckdb 1.1-1.4). Backups are never uploaded:
Drive keeps previous revisions of every updated file."""
import sys, os, json, re, argparse
sys.path.insert(0, os.path.dirname(__file__)); import gdrive
from googleapiclient.http import MediaFileUpload
import subprocess
ap = argparse.ArgumentParser(); ap.add_argument('dir'); ap.add_argument('--dry-run', action='store_true'); a = ap.parse_args()
man = json.load(open(os.path.join(a.dir, '..', '_manifest_keiba_db.json')))
ch = json.loads(subprocess.run([sys.executable, '-I', os.path.join(os.path.dirname(__file__), 'changed.py'), a.dir],
                               capture_output=True, text=True, check=True).stdout)
mod = [n for n in ch['modified'] if not re.search(r'_backup_', n)]
new = [n for n in ch['new'] if not re.search(r'_backup_', n)]
wal = 'keiba.duckdb.wal' in ch['missing_locally'] and 'keiba.duckdb.wal' in man
s = gdrive.svc(); live = {f['name']: f for f in gdrive.list_folder(s)}
conflicts = [n for n in mod + (['keiba.duckdb.wal'] if wal else [])
             if n in live and live[n]['modifiedTime'] != man[n]['modifiedTime']]
plan = {'update': mod, 'empty_wal': wal, 'new_not_uploaded': new, 'conflicts': conflicts}
print('[writeback] ' + json.dumps(plan, ensure_ascii=False))
if conflicts: sys.exit('[writeback] ABORT: Drive changed since the mirror; nothing uploaded')
if a.dry_run: sys.exit(0)
def put(name, path):
    m = MediaFileUpload(path, resumable=True, chunksize=16 * 1024 * 1024)
    req = s.files().update(fileId=man[name]['id'], media_body=m, supportsAllDrives=True); r = None
    while r is None: _, r = req.next_chunk(num_retries=5)
    print(f'[writeback] updated {name}')
if wal:
    empty = os.path.join(a.dir, '..', '_empty.wal'); open(empty, 'wb').close()
    put('keiba.duckdb.wal', empty)
order = (['keiba.duckdb'] if 'keiba.duckdb' in mod else []) + [n for n in mod if n != 'keiba.duckdb']
for n in order: put(n, os.path.join(a.dir, n))
print(f'[writeback] done: {len(order)} files' + (' + emptied .wal' if wal else ''))
