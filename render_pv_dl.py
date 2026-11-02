"""
PocketVault JAR download helper for Render (Python).

Add to app.py (Flask example at bottom).
Env optional: PV_ORIGIN=https://pocketvault.ct.ws
"""
import os
import re
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

PV_ORIGIN = os.environ.get('PV_ORIGIN', 'https://pocketvault.ct.ws').rstrip('/')


def _to_numbers(hex_str: str):
    return [int(hex_str[i:i + 2], 16) for i in range(0, len(hex_str), 2)]


def _to_hex(arr) -> str:
    return ''.join(f'{b & 0xff:02x}' for b in arr)


def _solve_cookie(html: str):
    """Best-effort free-host cookie (toNumbers / slowAES style)."""
    try:
        from Crypto.Cipher import AES  # pycryptodome
    except ImportError:
        try:
            from Cryptodome.Cipher import AES
        except ImportError:
            return None

    m = re.search(
        r'slowAES\.decrypt\(\s*toNumbers\(["\']([a-f0-9]+)["\']\)\s*,\s*2\s*,\s*'
        r'toNumbers\(["\']([a-f0-9]+)["\']\)\s*,\s*toNumbers\(["\']([a-f0-9]+)["\']\)',
        html,
        re.I,
    )
    if m:
        c, a, b = _to_numbers(m.group(1)), _to_numbers(m.group(2)), _to_numbers(m.group(3))
    else:
        m = re.search(
            r'toNumbers\(["\']([a-f0-9]+)["\']\)[\s\S]{0,120}'
            r'toNumbers\(["\']([a-f0-9]+)["\']\)[\s\S]{0,120}'
            r'toNumbers\(["\']([a-f0-9]+)["\']\)',
            html,
            re.I,
        )
        if not m:
            return None
        a, b, c = _to_numbers(m.group(1)), _to_numbers(m.group(2)), _to_numbers(m.group(3))

    try:
        key, iv, data = bytes(a), bytes(b), bytes(c)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        pt = cipher.decrypt(data)
        pad = pt[-1]
        if 1 <= pad <= 16:
            pt = pt[:-pad]
        return _to_hex(pt)
    except Exception:
        return None


def _fetch(url: str, cookie: str = ''):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10) Chrome/120.0.0.0 Mobile',
        'Accept': '*/*',
    }
    if cookie:
        headers['Cookie'] = cookie
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=60) as resp:
            body = resp.read()
            ct = resp.headers.get('Content-Type', '')
            set_c = resp.headers.get('Set-Cookie') or ''
    except HTTPError as e:
        body = e.read() if e.fp else b''
        ct = e.headers.get('Content-Type', '') if e.headers else ''
        set_c = ''
    except URLError as e:
        raise RuntimeError('Origin unreachable: ' + str(e.reason))

    new_cookie = cookie
    m = re.search(r'__test=([^;]+)', set_c)
    if m:
        part = '__test=' + m.group(1)
        new_cookie = f'{cookie}; {part}' if cookie else part

    text = ''
    try:
        text = body.decode('utf-8', errors='ignore')
    except Exception:
        pass

    if 'toNumbers' in text or 'slowAES' in text:
        sol = _solve_cookie(text)
        if sol:
            part = '__test=' + sol
            new_cookie = f'{new_cookie}; {part}' if new_cookie else part
            return _fetch(url, new_cookie)

    return body, ct, new_cookie, text


def handle_pv_dl(id_: str, t: str):
    """
    Returns (status_code, body_bytes, content_type, filename)
    """
    if not id_ or not t:
        return 400, b'Missing id or t', 'text/plain', None

    meta_url = f'{PV_ORIGIN}/dl_meta.php?{urlencode({"id": id_, "t": t})}'
    body, ct, cookie, text = _fetch(meta_url, '')

    try:
        meta = json.loads(text)
    except Exception:
        return 502, b'Bad meta from PocketVault', 'text/plain', None

    if not meta.get('ok'):
        err = (meta.get('error') or 'Denied').encode('utf-8')
        return 403, err, 'text/plain', None

    if meta.get('mode') == 'remote' and meta.get('url'):
        file_url = meta['url']
    elif meta.get('fetch'):
        file_url = PV_ORIGIN + '/' + str(meta['fetch']).lstrip('/')
    else:
        return 502, b'No file pointer', 'text/plain', None

    fbody, fct, cookie, ftext = _fetch(file_url, cookie)
    if 'text/html' in (fct or '').lower() or 'toNumbers' in (ftext or ''):
        return 502, b'Origin still returned HTML', 'text/plain', None

    mime = meta.get('mime') or fct or 'application/java-archive'
    name = meta.get('name') or 'download.jar'
    return 200, fbody, mime, name


# ---------- Flask ----------
def register_flask(app):
    from flask import request, Response

    @app.route('/pv-dl')
    def pv_dl():
        status, body, mime, name = handle_pv_dl(
            str(request.args.get('id') or ''),
            str(request.args.get('t') or ''),
        )
        headers = {'Cache-Control': 'no-store'}
        if name and status == 200:
            headers['Content-Disposition'] = f'attachment; filename="{name}"'
        return Response(body, status=status, mimetype=mime, headers=headers)


# ---------- FastAPI ----------
def register_fastapi(app):
    from fastapi import Query
    from fastapi.responses import Response

    @app.get('/pv-dl')
    def pv_dl(id: str = Query(''), t: str = Query('')):
        status, body, mime, name = handle_pv_dl(id, t)
        headers = {'Cache-Control': 'no-store'}
        if name and status == 200:
            headers['Content-Disposition'] = f'attachment; filename="{name}"'
        return Response(content=body, status_code=status, media_type=mime, headers=headers)
