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
for (const file of jsFiles) {
  const source = fs.readFileSync(path.join(JS_DIR, file), 'utf8');
  try {
    new vm.Script(source, { filename: file });
  } catch (e) {
    fail(`${file} derlenmiyor :: ${e.message}`);
  }
}
if (!failures) ok(`${jsFiles.length} JS dosyası derleniyor`);

// ── 2. Sayfaya özel script'in aradığı ID'ler HTML'de var mı ──
// YALNIZCA sayfaya özel script kontrol ediliyor (son <script src="js/...">).
// api.js gibi PAYLAŞILAN dosyalar bilerek dışarıda: onlar her sayfada yükleniyor
// ve olmayan elemanlara karşı `if (!el) return` ile korunuyorlar, yani orada
// eksik bir ID hata değil normal durum.
const SHARED = new Set(['firebase.js', 'logger.js', 'config.js', 'api.js', 'camera.js', 'stores.js']);

for (const page of fs.readdirSync(ROOT).filter(f => f.endsWith('.html'))) {
  const html = fs.readFileSync(path.join(ROOT, page), 'utf8');

  const scripts = [...html.matchAll(/<script src="js\/([^"]+)"><\/script>/g)].map(m => m[1]);
  for (const s of scripts) {
    if (!fs.existsSync(path.join(JS_DIR, s))) fail(`${page}: js/${s} yok`);
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
    if (missing.length) fail(`${page} ← js/${script}: eksik ID → ${missing.join(', ')}`);
    else ok(`${page} ← js/${script} (${wanted.size} ID)`);
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
  if (missing.length) fail(`${page}: sidebar iskeletinde eksik → ${missing.join(', ')}`);
}

console.log(failures === 0 ? '\nfrontend kontrolleri geçti' : `\n${failures} sorun`);
process.exit(failures === 0 ? 0 : 1);
