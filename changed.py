"""List local files in the keiba_db mirror that differ from the Drive manifest (new or modified)."""
import json, os, sys, hashlib
d = sys.argv[1]; man = json.load(open(os.path.join(d, '..', '_manifest_keiba_db.json')))
def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
new, mod = [], []
for n in sorted(os.listdir(d)):
    p = os.path.join(d, n)
    if not os.path.isfile(p): continue
    if n not in man: new.append(n)
    elif man[n].get('md5Checksum') and md5(p) != man[n]['md5Checksum']: mod.append(n)
gone = [n for n in man if not os.path.exists(os.path.join(d, n))]
print(json.dumps({'new': new, 'modified': mod, 'missing_locally': gone}, ensure_ascii=False, indent=1))
