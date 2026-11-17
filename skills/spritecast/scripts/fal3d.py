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


def run(endpoint, body, keep, again, tag=''):
    """one fal queue job; its id is kept in `keep` before waiting, so a run cut off picks the paid-for result up instead of buying it again.
    tag: what the job was made from (the rig: its model) - a kept id is taken only under the same tag"""
    keep = Path(keep); parts = keep.read_text().split() if keep.exists() and not again else []
    rid = parts[-1] if parts and parts[:-1] == ([tag] if tag else []) else ''
    app = '/'.join(endpoint.split('/')[:2])                             # a sub-path model's requests live under its app id (fal-ai/meshy)
    st_url = res_url = None
    if not rid:
        r = _call(QUEUE + endpoint, body); rid = r['request_id']; keep.parent.mkdir(parents=True, exist_ok=True); keep.write_text(f'{tag} {rid}'.strip())
        st_url, res_url = r.get('status_url'), r.get('response_url')
    st_url = st_url or f'{QUEUE}{app}/requests/{rid}/status'; res_url = res_url or f'{QUEUE}{app}/requests/{rid}'; t0 = time.time()
    while True:
        st = _call(st_url)
        if st.get('status') == 'COMPLETED': break
        if st.get('status') in ('FAILED', 'ERROR', 'CANCELLED'):
            keep.unlink(missing_ok=True); sys.exit(f'fal {endpoint}: {st.get("status")} {st.get("error") or st}')
        if time.time() - t0 > 1200: sys.exit(f'fal {endpoint}: still {st.get("status")} after 20 min - run again later to pick it up ({keep})')
        time.sleep(5)
    try: return _call(res_url)
    except SystemExit:                                                  # fal fails a job as COMPLETED + an error result: not one to pick up again
        keep.unlink(missing_ok=True); raise


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


# --- a character's (or animal's) model from its turnaround (charpipe.py model) ----------------------------------------------------------
def views_model(s, d, args, out, grey):
    """Meshy v6 multi-image-to-3d on fal, the same settings as charpipe's own Meshy call → model/model.glb.
    grey: charpipe.grey_texture (passed in: charpipe imports this module)"""
    d = Path(d)
    if args.again:                                                      # a new model: what was made from the old one goes with it
        for f in ('model/fal-request.txt', 'rig/fal-request.txt'): (d / f).unlink(missing_ok=True)
    if not gate(args, f'model: fal Meshy v6 multi-image-to-3d, ${PRICE["views"]:.2f}, a few minutes'): return
    body = {'image_urls': [data_uri(d / f'turnaround/{n}.png', 'image/png') for n in ('front', 'side', 'left', 'back')], 'should_texture': True,
            'enable_pbr': False, 'should_remesh': True, 'topology': 'quad', 'target_polycount': 40000, 'pose_mode': 'a-pose'}
    t0 = time.time(); keep = d / 'model/fal-request.txt'
    r = run('fal-ai/meshy/v6/multi-image-to-3d', body, keep, args.again)
    url = (r.get('model_glb') or {}).get('url') or ((r.get('model_urls') or {}).get('glb') or {}).get('url')
    if not url: sys.exit(f'model: fal sent no model back ({", ".join(r)})')
    fetch(url, out)
    if (r.get('thumbnail') or {}).get('url'): fetch(r['thumbnail']['url'], d / 'model/thumb-fal.png')
    if grey(out): sys.exit(f'model: fal sent the model back uncoloured - run `model --again` to make it anew (${PRICE["views"]:.2f} again)')
    print(f'model: {out} ({time.time() - t0:.0f} s, ${PRICE["views"]:.2f}) - look at model/thumb-fal.png before `rig`')


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


def facing(glb):
    """degrees to turn the model about +Y so it faces +z (CL.facing's sign), from the hip axis: left thigh minus right thigh, crossed with up.
    Not CL.facing's toes: Meshy's rig places the toe bones unevenly (24° and -69° on a rig that faces +z), which reads as -72°"""
    import math, numpy as np
    import charlib as CL
    js, _ = CL.read_glb(glb); nodes = js['nodes']; parent = {c: i for i, n in enumerate(nodes) for c in n.get('children', [])}
    def local(n):
        x, y, z, w = n.get('rotation', [0, 0, 0, 1]); m = np.eye(4)
        m[:3, :3] = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                              [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]) * n.get('scale', [1, 1, 1])
        m[:3, 3] = n.get('translation', [0, 0, 0]); return m
    def world(i):
        m = local(nodes[i])
        while i in parent: i = parent[i]; m = local(nodes[i]) @ m
        return m[:3, 3]
    at = {key(n.get('name')): i for i, n in enumerate(nodes)}
    f = np.cross(world(at['LeftUpLeg']) - world(at['RightUpLeg']), [0, 1, 0])
    return -math.degrees(math.atan2(f[0], f[2]))


def plan_clips(s):
    """[(name, Meshy id)] to ask for - idle first, then each action with an id, nine in all (fal's limit is ten) - and the actions left out"""
    picked, skipped = [('idle', 0)], []
    for n, a in (s.get('actions') or {}).items():
        c = a.get('clip'); i = a.get('meshy_id', c if isinstance(c, int) else ACTIONS.get(c, ACTIONS.get(n)))
        if i is not None and len(picked) < 9: picked.append((n, i))
        else: skipped.append(n)
    return picked, skipped


def rig(s, d, args):
    """Meshy rigging on fal (Mixamo skeleton): the walk (it comes with the rig), idle and the actions, merged into rig/rig.glb and made
    renderable the way charpipe makes Tripo's (facing, bone names and hips, feet planted); the walk's real stride written to the spec.
    Called after charpipe.rig's own checks (not an animal, no rig yet or --again, a model there). True when rig.glb was made."""
    import hashlib
    import charlib as CL
    d = Path(d); out = d / 'rig/rig.glb'; model = d / 'model/model.glb'
    picked, skipped = plan_clips(s)
    if skipped: print(f'rig: no Meshy clip for {", ".join(skipped)} (or more than eight actions) - left out; give a Meshy id as "clip", or your own rig ("rig_glb")')
    cost = PRICE['rig'] + len(picked) * PRICE['clip']
    if not gate(args, f'rig: fal Meshy rig ${PRICE["rig"]:.2f} + {len(picked)} clips × ${PRICE["clip"]:.2f} = ${cost:.2f} (the walk comes with it), a few minutes'): return False
    tag = hashlib.sha1(model.read_bytes()).hexdigest()[:12]              # the rig kept for a cut-off run belongs to THIS model
    url = data_uri(model, 'model/gltf-binary')                          # always the model on disk: a saved fal URL can expire or be another model's
    t0 = time.time()
    r = run('fal-ai/meshy/rigging/multi-animation', {'model_url': url, 'skeleton_template': 'mixamo', 'height_meters': float(s.get('height_m', 1.7)),
                                                    'animation_action_ids': [i for _, i in picked]}, d / 'rig/fal-request.txt', args.again, tag=tag)
    walk = ((r.get('basic_animations') or {}).get('walking_glb') or {}).get('url'); clips = r.get('animations') or []
    if not walk or len(clips) != len(picked): sys.exit(f'rig: fal sent {len(clips)} clips for {len(picked)} asked, walk {"yes" if walk else "no"} ({", ".join(r)})')
    base = fetch(walk, d / 'rig/fal-walk.glb')
    parts = [(n, fetch(c['animation_glb']['url'], d / f'rig/fal-{n}.glb')) for (n, _), c in zip(picked, clips)]
    m = d / 'rig/merged.glb'; merge(base, parts, m)
    turn = round(facing(m) / 90) * 90 % 360
    if turn: CL.turn_root(m, m, turn)
    durs = CL.fix_tripo(m, d / 'rig/named.glb'); feet = CL.plant_feet(d / 'rig/named.glb', out)
    validate(out, ['walk'] + [n for n, _ in picked])
    t1 = durs['walk'] / gait_cycles(out, 'walk')
    write_spec(args.spec, s, t1, picked)
    print(f'rig: {out}  clips {durs}  turned {turn}°  feet corrected {feet}  walk stride {t1:.3f} s  ({time.time() - t0:.0f} s, ${cost:.2f})')
    return True


def write_spec(path, s, walk_t1, picked):
    """the rig's real times into the spec FILE (every step loads it anew) and into `s` (make3d renders with it straight after):
    the walk's one stride, unless the user set their own; each rigged action played whole (Tripo's tuned windows, e.g. slash 0.6-2.7 s, would
    cut Meshy's clips wrong), unless the user set its times; an action given as a Meshy id gets the clip name it has in the rig"""
    raw = json.loads(Path(path).read_text(encoding='utf-8')); w = raw.get('walk') or {}
    if w.get('t1') in (None, 1.1835):                                   # (1.1835 s: one stride of Tripo's walk, charpipe's default)
        raw['walk'] = {'clip': w.get('clip', 'walk'), 't0': w.get('t0', 0), 't1': round(walk_t1, 4)}; s.setdefault('walk', {})['t1'] = round(walk_t1, 4)
    rigged = {n: i for n, i in picked if n != 'idle'}; out = []
    for e in raw.get('actions') or []:
        n = e if isinstance(e, str) else e.get('name')
        if n in rigged:
            e = {'name': e} if isinstance(e, str) else dict(e); sa = s.get('actions', {}).get(n, {})
            if 't0' not in e and 't1' not in e: e['t0'], e['t1'] = 0, None; sa.update(t0=0, t1=None)
            if e.get('clip', n) != n:                                   # merged under the action's name; the id kept for `rig --again`
                e['meshy_id'], e['clip'] = rigged[n], n; sa.update(clip=n, meshy_id=rigged[n])
        out.append(e)
    if 'actions' in raw: raw['actions'] = out
    Path(path).write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding='utf-8')


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
        assert not keep.exists()                                       # a failed job is not picked up again on the next run
        keep = tmp / 'k3b.txt'                                         # how fal really fails (the probe): COMPLETED, then the result is a 422
        def urlopen_422(req, timeout=None):
            if req.get_method() == 'POST': return Resp(json.dumps({'request_id': 'r7'}).encode())
            if req.full_url.endswith('/status'): return Resp(json.dumps({'status': 'COMPLETED'}).encode())
            raise urllib.error.HTTPError(req.full_url, 422, 'x', {}, io.BytesIO(b'{"detail": "too many triangles"}'))
        with mock.patch('urllib.request.urlopen', urlopen_422):
            msg = exits(lambda: run('fal-ai/x/y', {}, keep, False))
        assert 'too many triangles' in msg and not keep.exists(), msg
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

    # --- views_model: a character's model from its four views ---------------------------------------------------------------------------
    from PIL import Image
    cd = tmp / 'hero'; (cd / 'turnaround').mkdir(parents=True); (cd / 'model').mkdir()
    for i, n in enumerate(('front', 'side', 'left', 'back')): Image.new('RGB', (8, 8), (i * 60, 0, 0)).save(cd / f'turnaround/{n}.png')
    def fake_run2(endpoint, body, keep, again):
        sent.clear(); sent.update(endpoint=endpoint, body=body, keep=keep); Path(keep).write_text('m1')
        return {'model_glb': {'url': 'https://f/hero.glb'}, 'thumbnail': {'url': 'https://f/t.png'}}
    (cd / 'rig').mkdir(); (cd / 'rig/fal-request.txt').write_text('m0 r0')
    with mock.patch(__name__ + '.run', fake_run2), mock.patch(__name__ + '.fetch', fake_fetch):
        views_model({}, cd, NS(yes=True, again=True), cd / 'model/model.glb', lambda p: False)
        b = sent['body']
        assert sent['endpoint'] == 'fal-ai/meshy/v6/multi-image-to-3d' and len(b['image_urls']) == 4
        assert [base64.b64decode(u.split(',', 1)[1]) for u in b['image_urls']] == [(cd / f'turnaround/{n}.png').read_bytes() for n in ('front', 'side', 'left', 'back')]
        assert all(u.startswith('data:image/png;base64,') for u in b['image_urls'])
        assert {k: b[k] for k in ('should_texture', 'enable_pbr', 'topology', 'target_polycount', 'pose_mode', 'should_remesh')} == \
            {'should_texture': True, 'enable_pbr': False, 'topology': 'quad', 'target_polycount': 40000, 'pose_mode': 'a-pose', 'should_remesh': True}
        assert not (cd / 'rig/fal-request.txt').exists()                 # --again: the old rig belongs to the old model
        assert (cd / 'model/model.glb').exists()
        assert '$1.20' in exits(lambda: views_model({}, cd, NS(yes=True, again=True), cd / 'model/model.glb', lambda p: True))

    # --- rig's pieces: the facing (hip axis), which clips, the spec written, a kept rig only for its own model ----------------------------
    def hips_glb(path, left, right):
        js = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'buffers': [{'byteLength': 0}], 'bufferViews': [], 'accessors': [],
              'nodes': [{'name': 'mixamorig:Hips', 'translation': [0, 1, 0], 'children': [1, 2]},
                        {'name': 'mixamorig:LeftUpLeg', 'translation': left}, {'name': 'mixamorig:RightUpLeg', 'translation': right}]}
        CL.write_glb(path, js, bytearray()); return path
    assert abs(facing(hips_glb(tmp / 'f0.glb', [0.1, 0, 0], [-0.1, 0, 0]))) < 1e-6           # left thigh on +x: facing +z already
    assert abs(abs(facing(hips_glb(tmp / 'f1.glb', [-0.1, 0, 0], [0.1, 0, 0]))) - 180) < 1e-6
    assert abs(facing(hips_glb(tmp / 'f2.glb', [0, 0, -0.1], [0, 0, 0.1])) + 90) < 1e-6       # facing +x: turn -90, as CL.facing would say

    acts = {n: {'clip': n} for n in ['slash', 'wave', 'run', 'jump', 'shoot', 'dive', 'climb', 'fall', 'hurt', 'turn']}
    acts['cast'] = {'clip': 57}; acts['bow'] = {'clip': 'bow', 'meshy_id': 12}
    picked, skipped = plan_clips({'actions': acts})
    assert picked[:3] == [('idle', 0), ('slash', 219), ('run', 14)] and len(picked) == 9, picked
    assert 'wave' in skipped and set(skipped) >= {'cast', 'bow'} - {n for n, _ in picked}, skipped
    picked, skipped = plan_clips({'actions': {'cast': {'clip': 57}, 'bow': {'clip': 'bow', 'meshy_id': 12}}})
    assert picked == [('idle', 0), ('cast', 57), ('bow', 12)] and not skipped

    sp = tmp / 'a.json'; sp.write_text(json.dumps({'name': 'a', 'actions': ['slash', {'name': 'cast', 'clip': 57}, 'wave']}))
    s = {'walk': {'clip': 'walk', 't0': 0, 't1': 1.1835}, 'actions': {'slash': {'clip': 'slash', 't0': 0.6, 't1': 2.7}, 'cast': {'clip': 57, 't0': 0, 't1': None},
                                                                      'wave': {'clip': 'wave', 't0': 0, 't1': None}}}
    write_spec(sp, s, 1.02, [('slash', 219), ('cast', 57)])
    raw = json.loads(sp.read_text())
    assert raw['walk'] == {'clip': 'walk', 't0': 0, 't1': 1.02}
    assert raw['actions'][0] == {'name': 'slash', 't0': 0, 't1': None} and raw['actions'][1] == {'name': 'cast', 'clip': 'cast', 'meshy_id': 57, 't0': 0, 't1': None}
    assert raw['actions'][2] == 'wave'                                  # not rigged: left as the user wrote it
    assert s['walk']['t1'] == 1.02 and s['actions']['slash']['t0'] == 0 and s['actions']['slash']['t1'] is None and s['actions']['cast']['clip'] == 'cast'
    sp.write_text(json.dumps({'name': 'a', 'walk': {'clip': 'walk', 't0': 0, 't1': 0.9}, 'actions': [{'name': 'slash', 't0': 0.2, 't1': 1.0}]}))
    write_spec(sp, {'walk': {'t1': 0.9}, 'actions': {'slash': {'clip': 'slash', 't0': 0.2, 't1': 1.0}}}, 1.02, [('slash', 219)])
    raw = json.loads(sp.read_text())
    assert raw['walk']['t1'] == 0.9 and raw['actions'][0] == {'name': 'slash', 't0': 0.2, 't1': 1.0}    # the user's own times stay
    sp.write_text(json.dumps({'name': 'a', 'actions': [{'name': 'attack', 'clip': 'slash'}]}))           # merged as "attack": render must look for that
    s = {'actions': {'attack': {'clip': 'slash', 't0': 0, 't1': None}}}
    assert plan_clips(s)[0] == [('idle', 0), ('attack', 219)]
    write_spec(sp, s, 1.02, [('attack', 219)])
    assert json.loads(sp.read_text())['actions'][0]['clip'] == 'attack' and s['actions']['attack']['clip'] == 'attack'

    env(FAL_KEY='k')                                                   # (CI has no key: _call reads it before the faked urlopen)
    with mock.patch('time.sleep', lambda s: None):                     # a kept job is taken only under the same tag (the model it was made for)
        keep = tmp / 'k5.txt'; keep.write_text('modelA r5')
        uo, calls = fake([('POST', 'fal-ai/x/y', {'request_id': 'r6'}), ('GET', 'requests/r6/status', {'status': 'COMPLETED'}), ('GET', 'requests/r6', {'ok': 6})])
        with mock.patch('urllib.request.urlopen', uo): assert run('fal-ai/x/y', {}, keep, False, tag='modelB') == {'ok': 6}
        assert keep.read_text() == 'modelB r6'
        uo, calls = fake([('GET', 'requests/r6/status', {'status': 'COMPLETED'}), ('GET', 'requests/r6', {'ok': 6})])
        with mock.patch('urllib.request.urlopen', uo): assert run('fal-ai/x/y', {}, keep, False, tag='modelB') == {'ok': 6}
        assert not any(m == 'POST' for m, _ in calls)
    os.environ.clear(); os.environ.update(keep_env)
    print('fal3d: ok')
