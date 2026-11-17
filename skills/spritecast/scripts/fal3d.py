"""fal3d: SpriteCast's 3D steps through fal.ai instead of Tripo - a prop's model from its description (Tripo H3.1 on fal), a character's model
from its turnaround (Meshy v6 on fal) and its rig with the walk, idle and actions (Meshy on fal, Mixamo skeleton), merged into one rig.glb.

    SPRITECAST_3D   tripo | fal   (unset: tripo if TRIPO_API_KEY is set, else fal if FAL_KEY is)
    FAL_KEY         fal.ai

Each call site (isoprop.make_model, charpipe.model / rig / make3d) hands over here when provider3d() is 'fal'; the Tripo code stays as it is.
"""
import base64, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

KEYS3D = {'tripo': 'TRIPO_API_KEY', 'fal': 'FAL_KEY'}
PRICE = {'text': 0.20, 'views': 1.20, 'rig': 0.20, 'clip': 0.12}       # USD on fal, 2026-11
# SpriteCast's action names → Meshy library ids (https://api.meshy.ai/web/public/animations/resources); a spec action with an int "clip" is that id
ACTIONS = {'run': 14, 'jump': 61, 'slash': 219, 'shoot': 232, 'dive': 506, 'climb': 438, 'fall': 490, 'hurt': 178, 'turn': 576}
QUEUE = 'https://queue.fal.run/'


def provider3d():
    p = os.environ.get('SPRITECAST_3D', '').strip().lower()
    if p:
        if p not in KEYS3D: sys.exit(f'SPRITECAST_3D={p}: give one of {", ".join(KEYS3D)}')
        if not os.environ.get(KEYS3D[p]): sys.exit(f'3D: SPRITECAST_3D={p} needs {KEYS3D[p]}')
        return p
    return next((p for p, k in KEYS3D.items() if os.environ.get(k)), None)


def gate(args, what):
    print(what)
    if not args.yes: print('not spent - run again with --yes'); return False
    return True


def price(s):
    if s.get('kind') == 'animal': return f'fal: Meshy model ${PRICE["views"]:.2f}'
    k = len(s.get('actions') or {}) + 1                                 # idle and each action; the walk comes with the rig
    total = PRICE['views'] + PRICE['rig'] + k * PRICE['clip']
    return f'fal: Meshy model ${PRICE["views"]:.2f} + rig ${PRICE["rig"]:.2f} + {k} clips × ${PRICE["clip"]:.2f} = ${total:.2f}'


def data_uri(path, mime): return f'data:{mime};base64,' + base64.b64encode(Path(path).read_bytes()).decode()


def _call(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method='POST' if body is not None else 'GET',
                                 headers={'Authorization': f'Key {os.environ["FAL_KEY"]}', 'Content-Type': 'application/json'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=600) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            msg = e.read()[:300].decode(errors='replace')
            if e.code in (429, 500, 502, 503, 504) and attempt < 3: time.sleep(15 * (attempt + 1)); continue
            sys.exit(f'fal {url.split(QUEUE)[-1]}: HTTP {e.code} {msg}')


def run(endpoint, body, keep, again):
    """one fal queue job; its id is kept in `keep` before waiting, so a run cut off picks the paid-for result up instead of buying it again"""
    keep = Path(keep); rid = keep.read_text().strip() if keep.exists() and not again else ''
    app = '/'.join(endpoint.split('/')[:2])                             # a sub-path model's requests live under its app id (fal-ai/meshy)
    st_url = res_url = None
    if not rid:
        r = _call(QUEUE + endpoint, body); rid = r['request_id']; keep.parent.mkdir(parents=True, exist_ok=True); keep.write_text(rid)
        st_url, res_url = r.get('status_url'), r.get('response_url')
    st_url = st_url or f'{QUEUE}{app}/requests/{rid}/status'; res_url = res_url or f'{QUEUE}{app}/requests/{rid}'; t0 = time.time()
    while True:
        st = _call(st_url)
        if st.get('status') == 'COMPLETED': break
        if st.get('status') in ('FAILED', 'ERROR', 'CANCELLED'): sys.exit(f'fal {endpoint}: {st.get("status")} {st.get("error") or st}')
        if time.time() - t0 > 1200: sys.exit(f'fal {endpoint}: still {st.get("status")} after 20 min - run again later to pick it up ({keep})')
        time.sleep(5)
    return _call(res_url)


def fetch(url, path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=600) as r: path.write_bytes(r.read())
    return path


if __name__ == '__main__':                                             # self-check, no network: python fal3d.py
    import io, tempfile
    from unittest import mock
    tmp = Path(tempfile.mkdtemp())
    keep_env = dict(os.environ)
    def env(**kv):
        for k in ('SPRITECAST_3D', 'TRIPO_API_KEY', 'FAL_KEY'): os.environ.pop(k, None)
        os.environ.update(kv)
    def exits(f):
        try: f()
        except SystemExit as e: return str(e.code)
        raise AssertionError('no exit')
    env(TRIPO_API_KEY='k', FAL_KEY='k'); assert provider3d() == 'tripo'
    env(FAL_KEY='k'); assert provider3d() == 'fal'
    env(); assert provider3d() is None
    env(SPRITECAST_3D='fal'); assert 'FAL_KEY' in exits(provider3d)
    env(SPRITECAST_3D='nope', FAL_KEY='k'); exits(provider3d)
    env(FAL_KEY='k')

    assert all(0 <= v <= 696 for v in ACTIONS.values())
    assert price({'kind': 'animal'}) == 'fal: Meshy model $1.20'
    assert price({'kind': 'person', 'actions': {'slash': {}}}).endswith('= $1.64'), price({'kind': 'person', 'actions': {'slash': {}}})

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake(script):                                                  # script: [(method, url-part, answer dict)] in call order
        calls = []
        def urlopen(req, timeout=None):
            m = req.get_method(); u = req.full_url; calls.append((m, u))
            for i, (sm, part, ans) in enumerate(script):
                if sm == m and part in u: script.pop(i); return Resp(json.dumps(ans).encode())
            raise AssertionError(f'unexpected {m} {u}')
        return urlopen, calls
    with mock.patch('time.sleep', lambda s: None):
        keep = tmp / 'k1.txt'; keep.write_text('r1')                  # resume: no POST, the kept request's result
        uo, calls = fake([('GET', 'requests/r1/status', {'status': 'COMPLETED'}), ('GET', 'requests/r1', {'ok': 1})])
        with mock.patch('urllib.request.urlopen', uo): assert run('fal-ai/x/y', {}, keep, False) == {'ok': 1}
        assert not any(m == 'POST' for m, _ in calls)
        assert all('/fal-ai/x/requests/r1' in u for _, u in calls), calls     # a sub-path endpoint's requests live under its app id
        keep = tmp / 'k4.txt'                                          # the URLs fal gives back are used as they are
        uo, calls = fake([('POST', 'fal-ai/x/y', {'request_id': 'r4', 'status_url': 'https://s.example/st', 'response_url': 'https://s.example/res'}),
                          ('GET', 's.example/st', {'status': 'COMPLETED'}), ('GET', 's.example/res', {'ok': 4})])
        with mock.patch('urllib.request.urlopen', uo): assert run('fal-ai/x/y', {}, keep, False) == {'ok': 4}
        keep = tmp / 'k2.txt'                                          # fresh: POST, the id kept before waiting, polled to the end
        uo, calls = fake([('POST', 'queue.fal.run/fal-ai/x/y', {'request_id': 'r2'}), ('GET', 'requests/r2/status', {'status': 'IN_QUEUE'}),
                          ('GET', 'requests/r2/status', {'status': 'COMPLETED'}), ('GET', 'requests/r2', {'ok': 2})])
        with mock.patch('urllib.request.urlopen', uo): assert run('fal-ai/x/y', {'a': 1}, keep, False) == {'ok': 2}
        assert keep.read_text().strip() == 'r2'
        keep = tmp / 'k3.txt'                                          # a failed job: its error in the exit message
        uo, _ = fake([('POST', 'queue.fal.run', {'request_id': 'r3'}), ('GET', 'requests/r3/status', {'status': 'FAILED', 'error': 'bad mesh'})])
        with mock.patch('urllib.request.urlopen', uo): assert 'bad mesh' in exits(lambda: run('fal-ai/x/y', {}, keep, False))
    os.environ.clear(); os.environ.update(keep_env)
    print('fal3d: ok')
