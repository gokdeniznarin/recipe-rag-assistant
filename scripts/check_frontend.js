/**
 * Frontend sağlık kontrolü — CI'da ve yerelde aynı script.
 *
 *   node scripts/check_frontend.js
 *
 * NEDEN VAR: bu projede JS için test çatısı yok (sade tarayıcı JS'i, modül
 * sistemi yok). Ama bu oturumda GERÇEK hatalar yakalandı ve hepsi buradaki
 * iki kontrolden biriyle bulunabilirdi:
 *   - silinmiş bir değişkene bakan kalıntı → ReferenceError, sayfa komple ölür
 *   - HTML'de olmayan bir element ID'si → null, sayfa yüklenirken çöker
 * İkisi de sessiz: sayfa normal görünür ama hiçbir buton çalışmaz.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..', 'frontend');
const JS_DIR = path.join(ROOT, 'js');

let failures = 0;
const fail = (msg) => { console.error('  FAIL  ' + msg); failures++; };
const ok = (msg) => console.log('  ok    ' + msg);

// ── 1. Her JS dosyası derleniyor mu ──────────────────────
const jsFiles = fs.readdirSync(JS_DIR).filter(f => f.endsWith('.js'));
// sw.js js/ ALTINDA DEĞİL (service worker'ın scope'u bulunduğu klasör olduğu için
// kökte durmak zorunda) — listeye elle ekleniyor, yoksa sessizce kontrolsüz kalır.
const toParse = jsFiles.map(f => ['js/' + f, path.join(JS_DIR, f)]);
toParse.push(['sw.js', path.join(ROOT, 'sw.js')]);

for (const [label, full] of toParse) {
  try {
    new vm.Script(fs.readFileSync(full, 'utf8'), { filename: label });
  } catch (e) {
    fail(`${label} does not parse :: ${e.message}`);
  }
}
if (!failures) ok(`${toParse.length} JS files parse`);

// ── 2. Sayfaya özel script'in aradığı ID'ler HTML'de var mı ──
// YALNIZCA sayfaya özel script kontrol ediliyor (son <script src="js/...">).
// api.js gibi PAYLAŞILAN dosyalar bilerek dışarıda: onlar her sayfada yükleniyor
// ve olmayan elemanlara karşı `if (!el) return` ile korunuyorlar, yani orada
// eksik bir ID hata değil normal durum.
const SHARED = new Set(['firebase.js', 'logger.js', 'config.js', 'api.js', 'camera.js', 'stores.js', 'pwa.js']);

for (const page of fs.readdirSync(ROOT).filter(f => f.endsWith('.html'))) {
  const html = fs.readFileSync(path.join(ROOT, page), 'utf8');

  const scripts = [...html.matchAll(/<script src="js\/([^"]+)"><\/script>/g)].map(m => m[1]);
  for (const s of scripts) {
    if (!fs.existsSync(path.join(JS_DIR, s))) fail(`${page}: js/${s} does not exist`);
  }

  const own = scripts.filter(s => !SHARED.has(s));
  if (own.length === 0) continue;

  const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]));
  for (const script of own) {
    const source = fs.readFileSync(path.join(JS_DIR, script), 'utf8');
    const wanted = new Set(
      [...source.matchAll(/getElementById\(['"]([^'"]+)['"]\)/g)].map(m => m[1])
    );
    const missing = [...wanted].filter(id => !ids.has(id));
    if (missing.length) fail(`${page} <- js/${script}: missing id(s) -> ${missing.join(', ')}`);
    else ok(`${page} <- js/${script} (${wanted.size} ids)`);
  }
}

// ── 3. Sidebar'lı sayfalarda ortak iskelet tam mı ────────
// api.js bu ID'leri arıyor; biri eksikse kullanıcı menüsü ya da çekmece sessizce
// çalışmaz (api.js guard'lı olduğu için hata da vermez — en sinsi tür).
const SIDEBAR_IDS = ['sidebar', 'nav-toggle', 'nav-overlay', 'user-email', 'user-avatar', 'logout-btn'];
for (const page of fs.readdirSync(ROOT).filter(f => f.endsWith('.html'))) {
  const html = fs.readFileSync(path.join(ROOT, page), 'utf8');
  if (!html.includes('class="sidebar"')) continue;
  const missing = SIDEBAR_IDS.filter(id => !html.includes(`id="${id}"`));
  if (missing.length) fail(`${page}: sidebar shell missing -> ${missing.join(', ')}`);
}

// ── 4. PWA: sw.js precache listesi diskle uyumlu mu ──────
// Yeni bir sayfa ya da JS dosyası ekleyip sw.js'i güncellemeyi unutmak SESSİZ
// bir bozulma: uygulama çevrimiçi sorunsuz çalışır, yalnızca çevrimdışı açılmaz
// (ya da silinmiş bir dosya yüzünden precache kısmen başarısız olur).
const sw = fs.readFileSync(path.join(ROOT, 'sw.js'), 'utf8');
const block = sw.slice(sw.indexOf('const PRECACHE'), sw.indexOf('];', sw.indexOf('const PRECACHE')));
const precached = new Set([...block.matchAll(/'(\/[^']*)'/g)].map(m => m[1]));

const shouldCache = [
  ...fs.readdirSync(ROOT).filter(f => f.endsWith('.html')).map(f => '/' + f),
  ...fs.readdirSync(JS_DIR).filter(f => f.endsWith('.js')).map(f => '/js/' + f),
  ...fs.readdirSync(path.join(ROOT, 'icons')).map(f => '/icons/' + f),
  '/css/style.css',
];
const notCached = shouldCache.filter(f => !precached.has(f));
if (notCached.length) fail(`sw.js PRECACHE missing -> ${notCached.join(', ')}`);

const stale = [...precached].filter(u => u !== '/' && !fs.existsSync(path.join(ROOT, u)));
if (stale.length) fail(`sw.js PRECACHE lists deleted file(s) -> ${stale.join(', ')}`);

if (!notCached.length && !stale.length) ok(`sw.js precache in sync (${precached.size} entries)`);

// Her sayfa PWA'ya bağlı mı (manifest + ikon + kayıt script'i)
for (const page of fs.readdirSync(ROOT).filter(f => f.endsWith('.html'))) {
  const html = fs.readFileSync(path.join(ROOT, page), 'utf8');
  const missing = ['rel="manifest"', 'apple-touch-icon', 'js/pwa.js']
    .filter(needle => !html.includes(needle));
  if (missing.length) fail(`${page}: PWA wiring missing -> ${missing.join(', ')}`);
}

console.log(failures === 0 ? '\nfrontend checks passed' : `\n${failures} problem(s)`);
process.exit(failures === 0 ? 0 : 1);
