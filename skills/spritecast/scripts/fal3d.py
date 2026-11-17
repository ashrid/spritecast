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


# --- a prop's detailed model (isoprop.py model) -----------------------------------------------------------------------------------------
def text_model(spec, d, args, size, prompt):
    """Tripo H3.1 text-to-3d on fal → <name>/fal.glb; the spec file gets "model" and its blocks become "blocks_draft", as the Tripo branch does"""
    W, D, H = size; out = Path(d) / 'fal.glb'
    if out.exists() and not args.again: return print(f'model: {out} is there already (--again to make it anew)')
    if not gate(args, f'model: fal Tripo H3.1 text-to-3d, ${PRICE["text"]:.2f}; made {H:.2f} m tall in its own proportions (the blocks: {W} x {D} m)'): return
    t0 = time.time()
    r = run('tripo3d/h3.1/text-to-3d', {'prompt': prompt, 'texture': True, 'texture_quality': 'standard', 'face_limit': 80000},
            Path(d) / 'fal-request.txt', args.again)
    url = (r.get('model_mesh') or {}).get('url') or ((r.get('model_urls') or {}).get('glb') or {}).get('url')
    if not url: sys.exit(f'model: fal sent no model back ({", ".join(r)})')
    fetch(url, out)
    raw = json.loads(Path(args.spec).read_text(encoding='utf-8'))
    raw['model'] = {'glb': f"{spec['name']}/fal.glb", 'size': [W, D, round(H, 3)], 'yaw': 0}
    if 'blocks' in raw: raw['blocks_draft'] = raw.pop('blocks')
    Path(args.spec).write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'model: {out}  ({time.time() - t0:.0f} s, ${PRICE["text"]:.2f}) - the spec now uses it; run `yaws` to turn it the right way')


# --- the rig's clips: Meshy gives one complete GLB per clip; they become one rig.glb -----------------------------------------------------
REQUIRED_BONES = ('Hips', 'LeftFoot', 'RightFoot', 'LeftToeBase', 'RightToeBase', 'LeftHand', 'RightHand')
SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
COMPS = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


def key(name):
    import re
    return re.sub(r'^mixamorig\d*:?', '', name or '', flags=re.I)        # the rule addclip.py and render_char.html use


def _one_buffer(js, path):
    if len(js.get('buffers') or []) != 1: sys.exit(f'merge: {Path(path).name} has {len(js.get("buffers") or [])} buffers - one expected')


def merge(base, clips, out):
    """base: the walking GLB, kept whole (mesh, skin, scene) with its animation named "walk"; clips: [(name, GLB)] - only each one's
    animation is copied in, its data appended and its channels put on the base's bones (matched by name, Mixamo prefix aside).
    Returns {clip: seconds} for every animation in `out`."""
    import charlib as CL
    js, bin_ = CL.read_glb(base); _one_buffer(js, base)
    js['animations'] = js.get('animations', [])[:1]
    if not js['animations']: sys.exit(f'merge: {Path(base).name} has no animation')
    js['animations'][0]['name'] = 'walk'
    node_of = {key(n.get('name')): i for i, n in enumerate(js['nodes'])}
    for name, path in clips:
        cj, cb = CL.read_glb(path); _one_buffer(cj, path)
        if not cj.get('animations'): sys.exit(f'merge: {Path(path).name} ({name}) has no animation')
        an = cj['animations'][0]; copied = {}
        def copy(i):
            if i in copied: return copied[i]
            a = dict(cj['accessors'][i]); bv = cj['bufferViews'][a['bufferView']]; esz = SIZE[a['componentType']] * COMPS[a['type']]
            if bv.get('byteStride', esz) != esz: sys.exit(f'merge: {Path(path).name}: interleaved animation data is not handled')
            o = bv.get('byteOffset', 0) + a.pop('byteOffset', 0)
            while len(bin_) % 4: bin_.append(0)
            js['bufferViews'].append({'buffer': 0, 'byteOffset': len(bin_), 'byteLength': a['count'] * esz}); bin_.extend(cb[o:o + a['count'] * esz])
            a['bufferView'] = len(js['bufferViews']) - 1; js['accessors'].append(a); copied[i] = len(js['accessors']) - 1
            return copied[i]
        samplers = [dict(s, input=copy(s['input']), output=copy(s['output'])) for s in an['samplers']]
        channels = []
        for c in an['channels']:
            bone = cj['nodes'][c['target']['node']].get('name'); k = key(bone)
            if k not in node_of: sys.exit(f'merge: bone "{bone}" of the {name} clip is not in the rigged model')
            channels.append({'sampler': c['sampler'], 'target': dict(c['target'], node=node_of[k])})
        js['animations'] = [a for a in js['animations'] if a['name'] != name] + [{'name': name, 'samplers': samplers, 'channels': channels}]
    while len(bin_) % 4: bin_.append(0)
    js['buffers'][0]['byteLength'] = len(bin_); CL.write_glb(out, js, bin_)
    return durations(js)


def durations(js): return {a['name']: max(js['accessors'][s['input']]['max'][0] for s in a['samplers']) for a in js['animations']}


def validate(glb, need):
    """stop - never fall back - when a bone the renderer needs or a clip is missing (a missing clip would be swapped for the first, silently)"""
    import charlib as CL
    js, _ = CL.read_glb(glb); have = {key(n.get('name')) for n in js['nodes']}
    miss = [b for b in REQUIRED_BONES if b not in have]
    if miss: sys.exit(f'rig: the rigged model has no {", ".join(miss)} bone - not a Mixamo skeleton')
    d = durations(js); gone = [c for c in need if d.get(c, 0) <= 0]
    if gone: sys.exit(f'rig: no clip {", ".join(gone)} in {Path(glb).name} (has {", ".join(d)})')


def gait_cycles(glb, clip):
    """how many strides the walk clip holds: the period of the left thigh's swing (autocorrelation), against the clip's length"""
    import numpy as np
    import charlib as CL
    js, bin_ = CL.read_glb(glb); an = next(a for a in js['animations'] if a['name'] == clip)
    c = next((c for c in an['channels'] if c['target']['path'] == 'rotation' and key(js['nodes'][c['target']['node']].get('name')) == 'LeftUpLeg'), None)
    if c is None: return 1
    s = an['samplers'][c['sampler']]; t = CL._acc(js, bin_, s['input'])[0][:, 0]; q = CL._acc(js, bin_, s['output'])[0].astype(float)
    q = q * np.sign(q @ q[0])[:, None]; q -= q.mean(0)
    x = q @ np.linalg.svd(q, full_matrices=False)[2][0]                  # the swing's main direction
    if len(x) < 8 or x.std() < 1e-6: return 1
    ac = np.correlate(x, x, 'full')[len(x) - 1:]; ac /= ac[0]
    neg = np.argmax(ac < 0)
    if not neg: return 1
    lag = neg + int(np.argmax(ac[neg:]))
    if ac[lag] < 0.3 or lag >= len(x) - 1: return 1
    return max(1, round((t[-1] - t[0]) / (lag * (t[-1] - t[0]) / (len(t) - 1))))


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

    # --- merge, validate, gait cycles: on GLBs built here --------------------------------------------------------------------------------
    import numpy as np
    import charlib as CL
    BONES = ['Hips', 'LeftUpLeg', *[b for b in REQUIRED_BONES if b != 'Hips']]
    def _glb(path, names, anim, times, rots, buffers=1, hips_z=None):
        """one buffer; every accessor of the animation packed into ONE bufferView with its own byteOffset (as exporters do)"""
        nodes = [{'name': n} for n in names]; data = bytearray(); accs = []
        def acc(a, typ):
            a = np.asarray(a, np.float32); o = len(data); data.extend(a.tobytes())
            d = {'bufferView': 0, 'byteOffset': o, 'componentType': 5126, 'count': len(a), 'type': typ}
            if typ == 'SCALAR': d['min'], d['max'] = [float(a.min())], [float(a.max())]
            accs.append(d); return len(accs) - 1
        t = acc(times, 'SCALAR'); samplers, channels = [], []
        for i, n in enumerate(names):
            q = rots.get(n, np.tile([0, 0, 0, 1.0], (len(times), 1)))
            samplers.append({'input': t, 'output': acc(q, 'VEC4')}); channels.append({'sampler': len(samplers) - 1, 'target': {'node': i, 'path': 'rotation'}})
        if hips_z is not None:
            samplers.append({'input': t, 'output': acc(np.c_[np.zeros(len(times)), np.ones(len(times)), hips_z], 'VEC3')})
            channels.append({'sampler': len(samplers) - 1, 'target': {'node': 0, 'path': 'translation'}})
        js = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': nodes, 'accessors': accs,
              'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(data)}], 'buffers': [{'byteLength': len(data)}] * buffers,
              'animations': [{'name': anim, 'samplers': samplers, 'channels': channels}]}
        CL.write_glb(path, js, data); return path
    T = np.linspace(0, 2, 61)
    def swing(cycles, n=61): a = 0.5 * np.sin(2 * np.pi * cycles * np.linspace(0, 1, n)); return np.c_[np.sin(a / 2), 0 * a, 0 * a, np.cos(a / 2)]
    rng = np.random.default_rng(1)
    def rnd(): q = rng.normal(size=(61, 4)); return q / np.linalg.norm(q, axis=1, keepdims=True)
    base = _glb(tmp / 'walk.glb', ['mixamorig:' + b for b in BONES], 'Armature|walking', T, {'mixamorig:LeftUpLeg': swing(2)})
    A = _glb(tmp / 'a.glb', ['mixamorig' + b for b in BONES], 'x', T, {'mixamorigLeftHand': rnd()})
    B = _glb(tmp / 'b.glb', ['mixamorig1:' + b for b in reversed(BONES)], 'y', np.linspace(0, 3, 61), {'mixamorig1:RightFoot': rnd()})
    out = tmp / 'merged.glb'
    dur = merge(base, [('idle', A), ('slash', B)], out)
    assert set(dur) == {'walk', 'idle', 'slash'} and abs(dur['slash'] - 3) < 1e-6, dur
    mj, mb = CL.read_glb(out); bj = {}
    for nm, src in (('idle', A), ('slash', B)):
        sj, sb = CL.read_glb(src); bj[nm] = (sj, sb)
        an = next(a for a in mj['animations'] if a['name'] == nm); sa = sj['animations'][0]
        for c, sc in zip(an['channels'], sa['channels']):
            assert key(mj['nodes'][c['target']['node']]['name']) == key(sj['nodes'][sc['target']['node']]['name'])
            for f in ('input', 'output'):
                assert np.array_equal(CL._acc(mj, mb, an['samplers'][c['sampler']][f])[0], CL._acc(sj, sb, sa['samplers'][sc['sampler']][f])[0])
    assert mj['buffers'][0]['byteLength'] == len(mb) and all(v.get('byteOffset', 0) % 4 == 0 for v in mj['bufferViews'])
    assert [a['name'] for a in mj['animations']][0] == 'walk'
    C = _glb(tmp / 'c.glb', ['mixamorig:' + b for b in BONES] + ['mixamorig:Tail'], 'z', T, {})
    assert 'Tail' in exits(lambda: merge(base, [('idle', C)], tmp / 'm2.glb'))
    D = _glb(tmp / 'd.glb', BONES, 'z', T, {}, buffers=2)
    exits(lambda: merge(base, [('idle', D)], tmp / 'm3.glb'))
    validate(out, ['walk', 'idle', 'slash'])
    assert 'jump' in exits(lambda: validate(out, ['walk', 'jump']))
    E = _glb(tmp / 'e.glb', ['mixamorig:' + b for b in BONES if b != 'LeftToeBase'], 'walking', T, {})
    assert 'LeftToeBase' in exits(lambda: validate(E, ['walking']))
    assert gait_cycles(out, 'walk') == 2
    one = _glb(tmp / 'one.glb', BONES, 'walk', T, {'LeftUpLeg': swing(1)})
    assert gait_cycles(one, 'walk') == 1

    # --- text_model: a prop's model, and the spec file pointed at it ------------------------------------------------------------------------
    from types import SimpleNamespace as NS
    sent = {}
    def fake_run(endpoint, body, keep, again): sent.update(endpoint=endpoint, body=body, keep=keep); return {'model_mesh': {'url': 'https://f/m.glb'}}
    def fake_fetch(url, path): Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_bytes(b'glb'); return Path(path)
    blocks = [{'shape': 'box', 'at': [0, 0, 0], 'size': [0.4, 0.4, 1.2]}]
    sp = tmp / 'lamp.json'; sp.write_text(json.dumps({'name': 'lamp', 'footprint': [0.4, 0.4], 'blocks': blocks}))
    with mock.patch(__name__ + '.run', fake_run), mock.patch(__name__ + '.fetch', fake_fetch):
        before = sp.read_text()
        text_model({'name': 'lamp'}, tmp / 'lamp', NS(yes=False, again=False, spec=str(sp)), (0.4, 0.4, 1.2), 'a lamp')
        assert not sent and sp.read_text() == before
        text_model({'name': 'lamp'}, tmp / 'lamp', NS(yes=True, again=False, spec=str(sp)), (0.4, 0.4, 1.2), 'a lamp')
    raw = json.loads(sp.read_text())
    assert raw['model'] == {'glb': 'lamp/fal.glb', 'size': [0.4, 0.4, 1.2], 'yaw': 0} and 'blocks' not in raw and raw['blocks_draft'] == blocks, raw
    assert sent['endpoint'] == 'tripo3d/h3.1/text-to-3d' and sent['keep'] == tmp / 'lamp/fal-request.txt'
    assert {k: sent['body'][k] for k in ('prompt', 'texture', 'texture_quality', 'face_limit')} == \
        {'prompt': 'a lamp', 'texture': True, 'texture_quality': 'standard', 'face_limit': 80000}
    assert (tmp / 'lamp/fal.glb').read_bytes() == b'glb'
    print('fal3d: ok')
