/**
 * Add to your Render Node server (same app as converter is fine).
 *
 * GET /pv-dl?id=GAME_ID&t=TOKEN
 * → talks to PocketVault dl_meta + dl_file, streams JAR/ZIP bytes
 *
 * Env (optional):
 *   PV_ORIGIN=https://pocketvault.ct.ws
 */
const express = require('express');
// If you already have app, don't create new — only copy the route.
const router = express.Router();

const PV_ORIGIN = process.env.PV_ORIGIN || 'https://pocketvault.ct.ws';

function toNumbers(hex) {
  const e = [];
  String(hex).replace(/(..)/g, (d) => e.push(parseInt(d, 16)));
  return e;
}
function toHex(arr) {
  return arr.map((x) => ('0' + (x & 255).toString(16)).slice(-2)).join('');
}

// Minimal AES used by free-host cookie pages
function aesDecrypt(cipher, key, iv) {
  // Use Node crypto for AES-128-CBC
  const crypto = require('crypto');
  const keyBuf = Buffer.from(key);
  const ivBuf = Buffer.from(iv);
  const data = Buffer.from(cipher);
  const decipher = crypto.createDecipheriv('aes-128-cbc', keyBuf, ivBuf);
  decipher.setAutoPadding(true);
  return Buffer.concat([decipher.update(data), decipher.final()]);
}

function solveCookie(html) {
  let m = html.match(
    /slowAES\.decrypt\(\s*toNumbers\(["']([a-f0-9]+)["']\)\s*,\s*2\s*,\s*toNumbers\(["']([a-f0-9]+)["']\)\s*,\s*toNumbers\(["']([a-f0-9]+)["']\)/i
  );
  let c, a, b;
  if (m) {
    c = toNumbers(m[1]);
    a = toNumbers(m[2]);
    b = toNumbers(m[3]);
  } else {
    m = html.match(
      /toNumbers\(["']([a-f0-9]+)["']\)[\s\S]{0,120}toNumbers\(["']([a-f0-9]+)["']\)[\s\S]{0,120}toNumbers\(["']([a-f0-9]+)["']\)/i
    );
    if (!m) return null;
    a = toNumbers(m[1]);
    b = toNumbers(m[2]);
    c = toNumbers(m[3]);
  }
  try {
    return toHex([...aesDecrypt(c, a, b)]);
  } catch (e) {
    return null;
  }
}

async function fetchPv(url, cookie) {
  const res = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Linux; Android 10) Chrome/120.0.0.0 Mobile',
      Accept: '*/*',
      Cookie: cookie || '',
    },
    redirect: 'follow',
  });
  const ct = (res.headers.get('content-type') || '').toLowerCase();
  const set = res.headers.get('set-cookie') || '';
  let c = cookie || '';
  const sm = set.match(/__test=([^;]+)/);
  if (sm) c = c ? c + '; __test=' + sm[1] : '__test=' + sm[1];
  const buf = Buffer.from(await res.arrayBuffer());
  const text = buf.toString('utf8');
  if (text.includes('toNumbers') || text.includes('slowAES')) {
    const sol = solveCookie(text);
    if (sol) {
      c = c ? c + '; __test=' + sol : '__test=' + sol;
      return fetchPv(url, c);
    }
  }
  return { res, buf, ct, cookie: c, text };
}

router.get('/pv-dl', async (req, res) => {
  try {
    const id = String(req.query.id || '');
    const t = String(req.query.t || '');
    if (!id || !t) {
      res.status(400).type('text').send('Missing id or t');
      return;
    }

    const metaUrl = PV_ORIGIN + '/dl_meta.php?id=' + encodeURIComponent(id) + '&t=' + encodeURIComponent(t);
    let pack = await fetchPv(metaUrl, '');
    let meta;
    try {
      meta = JSON.parse(pack.text);
    } catch (e) {
      res.status(502).type('text').send('Bad meta from site');
      return;
    }
    if (!meta.ok) {
      res.status(403).type('text').send(meta.error || 'Denied');
      return;
    }

    // Only allow jar/zip style for this endpoint (optional filter)
    const name = (meta.name || 'file.bin').toLowerCase();
    const ext = name.split('.').pop();
    // User asked JAR mainly — still allow zip/jad
    // if (!['jar', 'jad', 'zip'].includes(ext)) { ... }

    let fileUrl;
    if (meta.mode === 'remote' && meta.url) fileUrl = meta.url;
    else if (meta.fetch) fileUrl = PV_ORIGIN + '/' + String(meta.fetch).replace(/^\//, '');
    else {
      res.status(502).type('text').send('No file');
      return;
    }

    pack = await fetchPv(fileUrl, pack.cookie);
    if ((pack.ct || '').includes('text/html')) {
      res.status(502).type('text').send('Origin still HTML');
      return;
    }

    res.setHeader('Content-Type', meta.mime || pack.ct || 'application/java-archive');
    res.setHeader(
      'Content-Disposition',
      'attachment; filename="' + String(meta.name || 'game.jar').replace(/"/g, '') + '"'
    );
    res.setHeader('Cache-Control', 'no-store');
    res.send(pack.buf);
  } catch (e) {
    res.status(500).type('text').send('Render error: ' + (e.message || String(e)));
  }
});

module.exports = router;
// Usage in main server.js:
//   app.use(require('./render_pv_dl'));
