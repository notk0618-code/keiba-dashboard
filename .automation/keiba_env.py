"""Load keiba_dashboard_full_restore_v7.py outside Colab (shared by the weekly and daily runners).
Assumes keiba_db is mirrored at /content/drive/MyDrive/keiba_db and the site repo is cloned at `site`.
Every GitHub publish is staged into the clone: the cloud proxy only allows git push, not API writes,
and github.io is unreachable, so race_archive keys are read from the clone too."""
import sys, os, types, json, time, subprocess
KDB = '/content/drive/MyDrive/keiba_db'
STAGED = []
HEADER_ANCHOR = '<a id="confidence-link-icon" href="index.html#confidence-ranking" style="color:#ff6600; text-decoration:none; font-size:16px;" title="堅軸TOP10">🔥</a>'
BETS_LINK = '<a id="bets-link-icon" href="bets.html" style="color:#ff6600; text-decoration:none; font-size:16px;" title="買い目リスト">🎫</a>'

def load(site):
    os.chdir(KDB)
    # --- Colab stand-ins ---
    colab = types.ModuleType('google.colab'); colab.drive = types.SimpleNamespace(mount=lambda *x, **k: print('[runner] drive.mount skipped (local mirror)'))
    sys.modules['google.colab'] = colab
    import getpass; getpass.getpass = lambda prompt='': 'PROXY-AUTH'  # the session proxy authenticates GitHub
    import github as _gh
    class _ReadOnlyRepo:
        """Reads pass through; any API write raises so a missed publish path can never half-publish."""
        def __init__(self, real): self._real = real
        def __getattr__(self, n):
            if n.startswith(('create_', 'update_', 'delete_', 'edit')) or n == 'merge':
                raise RuntimeError(f'[runner] blocked direct GitHub API write: repo.{n}')
            return getattr(self._real, n)
    _RealGithub = _gh.Github
    class _ProxyGithub:
        def __init__(self, *x, **k): self._g = _RealGithub()
        def get_repo(self, name): return _ReadOnlyRepo(self._g.get_repo(name))
    _gh.Github = _ProxyGithub

    ns = {'__name__': '__main__'}
    t0 = time.time()
    code = open(f'{KDB}/keiba_dashboard_full_restore_v7.py', encoding='utf-8').read()
    exec(compile(code, 'keiba_dashboard_full_restore_v7.py', 'exec'), ns)
    print(f'[runner] restore_v7 loaded in {time.time()-t0:.0f}s')
    _header = ns['build_common_header']
    def _header_with_bets(*x, **k):  # add the bet list (bet_list.py) to the shared header without editing restore_v7
        h = _header(*x, **k)
        return h if BETS_LINK in h else h.replace(HEADER_ANCHOR, HEADER_ANCHOR + '\n' + BETS_LINK, 1)
    ns['build_common_header'] = _header_with_bets
    def _stage_bytes(github_filename, data):
        dst = os.path.join(site, github_filename); os.makedirs(os.path.dirname(dst) or site, exist_ok=True)
        with open(dst, 'wb') as f: f.write(data)
        STAGED.append(github_filename); print(f'[runner] staged: {github_filename} ({len(data)/1e6:.2f}MB)')
    def _stage_file(*x, **k):
        # restore_v7 calls these with local_html_path= or local_path=, positionally or by keyword
        path = k.get('local_html_path') or k.get('local_path') or x[0]
        name = k.get('github_filename') or (x[1] if len(x) > 1 else 'index.html')
        _stage_bytes(name, open(path, 'rb').read())
    def _stage_batch(files, commit_message, *x, **k):
        for path, text in files.items(): _stage_bytes(path, text.encode('utf-8') if isinstance(text, str) else text)
    for fn in ('upload_to_github', 'upload_to_github_v2', 'upload_large_file_via_git_clone', 'upload_binary_to_github'):
        ns[fn] = _stage_file
    ns['upload_files_batch_to_github'] = _stage_batch

    try:
        ns['_RACE_ARCHIVE_KEYS_CACHE'] = set(json.load(open(os.path.join(site, 'race_archive.json'), encoding='utf-8')).keys())
        print(f"[runner] race_archive keys from clone: {len(ns['_RACE_ARCHIVE_KEYS_CACHE'])}")
    except Exception as e:
        sys.exit(f'[runner] cannot read race_archive.json from site clone: {e}')
    return ns

def finish(ns, site, trial, message, result):
    """Checkpoint the DB (so the Drive .wal can be emptied) and commit staged site files locally."""
    ns['con'].execute('CHECKPOINT'); ns['con'].close()
    def git(*args): return subprocess.run(['git', '-C', site, *args], capture_output=True, text=True)
    result['staged_files'] = len(set(STAGED))
    changed = [l[3:] for l in git('status', '--porcelain').stdout.splitlines()]
    result['site_changed_files'] = len(changed)
    result['site_changed_sample'] = changed[:30]
    if changed and not trial:
        git('add', '-A')
        result['committed'] = git('commit', '-m', message).returncode == 0  # pushed by the shell wrapper after write-back
    print('[runner] RESULT ' + json.dumps(result, ensure_ascii=False))
