"""imagegen: one image edit - a prompt, the input pictures in order ("image 1", "image 2", ...) and the size - by whichever provider is set.

    SPRITECAST_PROVIDER  openai | fal | openrouter   (unset: the first whose key is set, in that order)
    OPENAI_API_KEY       api.openai.com/v1/images/edits
    FAL_KEY              fal.run/openai/<model>/edit (the same OpenAI model, billed by fal)
    OPENROUTER_API_KEY   openrouter.ai/api/v1/images (the same OpenAI model, billed by OpenRouter)
    SPRITECAST_MODEL     gpt-image-2.5-sunburst by default, named as OpenAI names it and turned into each provider's id; a name with
                         a '/' in it is that provider's own id, used as it is (another model: the prompts were tuned on gpt-image-2.5)
    SPRITECAST_QUALITY   low | medium | high (default)

edit() returns (the PNG's bytes, its cost in USD) and raises Refused when the safety check turns the picture down three times.
"""
import base64, io, json, os, sys, time, urllib.error, urllib.request, uuid
from pathlib import Path

from PIL import Image

KEYS = {'openai': 'OPENAI_API_KEY', 'fal': 'FAL_KEY', 'openrouter': 'OPENROUTER_API_KEY'}
PRICE = {'image_in': 8e-6, 'text_in': 5e-6, 'image_out': 30e-6}       # USD per token (gpt-image-2.5, the same on all three)
OUT_TOK = {'low': 196, 'medium': 439, 'high': 1756}
ASPECT = {(1024, 1024): '1:1', (1536, 1024): '3:2', (1024, 1536): '2:3'}   # every size the scripts ask for


class Refused(Exception):
    """the provider's safety check turned a picture down three times running (OpenAI's does now and then, at random, on legs and short skirts)"""


def provider():
    p = os.environ.get('SPRITECAST_PROVIDER', '').strip().lower()
    if p:
        if p not in KEYS: sys.exit(f'SPRITECAST_PROVIDER={p}: give one of {", ".join(KEYS)}')
        if not os.environ.get(KEYS[p]): sys.exit(f'draw: SPRITECAST_PROVIDER={p} needs {KEYS[p]}')
        return p
    p = next((p for p, k in KEYS.items() if os.environ.get(k)), None)
    if not p: sys.exit('draw: set OPENAI_API_KEY, FAL_KEY or OPENROUTER_API_KEY (the plugin\'s settings: /plugin -> SpriteCast)')
    return p


def model_id(p, model):
    if '/' in model: return model
    if p == 'fal':                                                     # gpt-image-2.5-sunburst -> openai/gpt-image-2.5/sunburst/edit
        base, _, variant = model.rpartition('-') if model.count('-') > 2 else (model, '', '')
        return f'openai/{base}/{variant}/edit' if variant else f'openai/{model}/edit'
    return f'openai/{model}' if p == 'openrouter' else model


def data_uri(p): return 'data:image/png;base64,' + base64.b64encode(Path(p).read_bytes()).decode()


def request(p, model, prompt, imgs, size, quality):
    """the provider's HTTP request for one edit"""
    key = os.environ[KEYS[p]]; w, h = map(int, size.split('x'))
    if p == 'openai':
        fields = {'model': model, 'prompt': prompt, 'size': size, 'quality': quality, 'background': 'opaque', 'output_format': 'png', 'n': '1'}
        b = uuid.uuid4().hex; body = b''
        for k, v in fields.items(): body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for i in imgs:
            body += (f'--{b}\r\nContent-Disposition: form-data; name="image[]"; filename="{Path(i).name}"\r\nContent-Type: image/png\r\n\r\n'.encode()
                     + Path(i).read_bytes() + b'\r\n')
        body += f'--{b}--\r\n'.encode()
        return urllib.request.Request('https://api.openai.com/v1/images/edits', data=body, method='POST',
                                      headers={'Authorization': f'Bearer {key}', 'Content-Type': f'multipart/form-data; boundary={b}'})
    if p == 'fal':
        body = {'prompt': prompt, 'image_urls': [data_uri(i) for i in imgs], 'image_size': {'width': w, 'height': h}, 'quality': quality,
                'background': 'opaque', 'output_format': 'png', 'num_images': 1, 'sync_mode': True}
        return urllib.request.Request(f'https://fal.run/{model}', data=json.dumps(body).encode(), method='POST',
                                      headers={'Authorization': f'Key {key}', 'Content-Type': 'application/json'})
    # OpenRouter takes no pixel size for this model, only a ratio - and each size here is one of OpenAI's three, so the ratio gives it back
    body = {'model': model, 'prompt': prompt, 'input_references': [{'type': 'image_url', 'image_url': {'url': data_uri(i)}} for i in imgs],
            'aspect_ratio': ASPECT.get((w, h), 'auto'), 'quality': quality, 'background': 'opaque', 'output_format': 'png', 'n': 1}
    return urllib.request.Request('https://openrouter.ai/api/v1/images', data=json.dumps(body).encode(), method='POST',
                                  headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})


def estimate(n_imgs, quality):
    # shortcut: fal reports no usage, so its cost is this estimate (as isoprop's dry run prints); upgrade if fal adds usage to the output
    return n_imgs * 1300 * PRICE['image_in'] + 450 * PRICE['text_in'] + OUT_TOK.get(quality, 1756) * PRICE['image_out']


def parse(p, j, n_imgs, quality):
    """(PNG bytes, USD) from the provider's answer"""
    if p == 'fal':
        url = j['images'][0]['url']
        png = base64.b64decode(url.split(',', 1)[1]) if url.startswith('data:') else urllib.request.urlopen(url, timeout=300).read()
        return png, estimate(n_imgs, quality)
    png = base64.b64decode(j['data'][0]['b64_json']); u = j.get('usage') or {}
    if p == 'openrouter' and u.get('cost') is not None: return png, float(u['cost'])
    i = u.get('input_tokens_details', {})
    return png, i.get('image_tokens', 0) * PRICE['image_in'] + i.get('text_tokens', 0) * PRICE['text_in'] + u.get('output_tokens', 0) * PRICE['image_out']


def edit(prompt, imgs, size, quality=None):
    p = provider(); quality = quality or os.environ.get('SPRITECAST_QUALITY', 'high')
    model = model_id(p, os.environ.get('SPRITECAST_MODEL', 'gpt-image-2.5-sunburst'))
    req = request(p, model, prompt, imgs, size, quality)
    for attempt in range(4):
        try: j = json.load(urllib.request.urlopen(req, timeout=600)); break
        except urllib.error.HTTPError as e:
            msg = e.read()[:300].decode(errors='replace')
            if e.code in (429, 500, 502, 503, 504) and attempt < 3: time.sleep(15 * (attempt + 1)); continue
            if e.code in (400, 422) and ('safety' in msg.lower() or 'moderation' in msg.lower()):   # the same request often passes the next time
                if attempt < 2: print(f'  turned down by the safety check ({p}) - asking again', flush=True); time.sleep(5); continue
                raise Refused(msg)
            sys.exit(f'{p} HTTP {e.code} {msg}')
    png, cost = parse(p, j, len(imgs), quality)
    w, h = map(int, size.split('x')); im = Image.open(io.BytesIO(png))
    if im.size != (w, h):                                              # the guide's crop is in the asked size's pixels
        print(f'  {p} gave {im.size[0]}x{im.size[1]} for {size} - scaled to it', flush=True)
        buf = io.BytesIO(); im.convert('RGB').resize((w, h), Image.LANCZOS).save(buf, 'PNG'); png = buf.getvalue()
    return png, cost


if __name__ == '__main__':                                             # self-check, no network: python imagegen.py
    assert model_id('openai', 'gpt-image-2.5-sunburst') == 'gpt-image-2.5-sunburst'
    assert model_id('fal', 'gpt-image-2.5-sunburst') == 'openai/gpt-image-2.5/sunburst/edit'
    assert model_id('fal', 'gpt-image-2.6-sunburst') == 'openai/gpt-image-2.6/sunburst/edit'
    assert model_id('fal', 'gpt-image-2') == 'openai/gpt-image-2/edit'
    assert model_id('openrouter', 'gpt-image-2.5-sunburst') == 'openai/gpt-image-2.5-sunburst'
    assert model_id('openrouter', 'google/gemini-3-pro-image') == 'google/gemini-3-pro-image'
    import tempfile
    t = Path(tempfile.mkdtemp()) / 'a.png'; Image.new('RGB', (4, 4), (255, 0, 255)).save(t)
    for p in KEYS:
        os.environ[KEYS[p]] = 'k'; r = request(p, model_id(p, 'gpt-image-2.5-sunburst'), 'x', [t, t], '1536x1024', 'high')
        if p != 'openai':
            b = json.loads(r.data)
            assert (b.get('image_size') or {'width': 1536, 'height': 1024}) == {'width': 1536, 'height': 1024} and b.get('aspect_ratio', '3:2') == '3:2'
            assert len(b.get('image_urls') or b.get('input_references')) == 2
    assert parse('fal', {'images': [{'url': data_uri(t)}]}, 2, 'high')[0] == t.read_bytes()
    assert parse('openrouter', {'data': [{'b64_json': base64.b64encode(b'x').decode()}], 'usage': {'cost': 0.07}}, 2, 'high') == (b'x', 0.07)
    print('imagegen: ok')
