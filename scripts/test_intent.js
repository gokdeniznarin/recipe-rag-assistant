/**
 * "Kaydolduktan sonra kaldığım yere dön" niyeti (Faz 29, adım 6).
 *
 *   node scripts/test_intent.js
 *
 * NEDEN VAR — iki ayrı sebep:
 *
 * 1. **Açık yönlendirme (open redirect).** Saklanan yol doğrudan
 *    `window.location.href`'e gidiyor. `//evil.com` protokol-göreceli bir
 *    MUTLAK adres: tarayıcı onu dış siteye götürür. Değer bizim yazdığımız
 *    depodan geldiği için "güvenilir" sanılıyor ve bu sınıf hata tam da o
 *    varsayımdan doğuyor.
 *
 * 2. **Sekme paylaşımı.** sessionStorage sekmeye özel ama KULLANICIYA özel
 *    değil. A kişisi ♡'ye basıp vazgeçse, aynı sekmede B kaydolduğunda
 *    A'nın tarifine düşer ve o tarif B'nin favorilerine eklenir — Faz 20'de
 *    birebir aynı hata yaşandı. Bayatlama penceresi bunun sınırı.
 */
const path = require('path');
const fs = require('fs');
const vm = require('vm');

const NOW = 1700000000000;

let pass = 0;
let failures = 0;
const check = (name, cond, extra) => {
  if (cond) { console.log('  ok    ' + name); pass++; }
  else { console.error('  FAIL  ' + name + (extra ? ' :: ' + extra : '')); failures++; }
};

/** intent.js'i taze bir sahte ortamda yükler. */
function load(opts = {}) {
  const store = new Map(Object.entries(opts.store || {}));
  const storage = opts.throws
    ? {
        getItem() { throw new Error('SecurityError'); },
        setItem() { throw new Error('SecurityError'); },
        removeItem() { throw new Error('SecurityError'); },
      }
    : {
        getItem: (k) => (store.has(k) ? store.get(k) : null),
        setItem: (k, v) => store.set(k, v),
        removeItem: (k) => store.delete(k),
      };

  let fakeNow = opts.now || NOW;
  const sandbox = {
    sessionStorage: storage,
    window: { location: { pathname: opts.pathname || '/recipes/25500-x', search: opts.search || '' } },
    Date: Object.assign(function () {}, { now: () => fakeNow }),
    module: { exports: {} },
    console,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, '..', 'frontend', 'js', 'intent.js'), 'utf8'),
    sandbox
  );
  return {
    api: sandbox.module.exports,
    store,
    advance: (ms) => { fakeNow += ms; },
  };
}

// ── 1–8. 🔴 Açık yönlendirme koruması ────────────────────
const { api } = load();
check('accepts an ordinary relative path', api.isSafeReturnPath('/recipes/25500-x'));
check('accepts a path with a query string', api.isSafeReturnPath('/recipe.html?id=25500'));
// Bunlar tarayıcıyı DIŞ bir siteye götürür.
check('rejects a protocol-relative url', !api.isSafeReturnPath('//evil.com'));
check('rejects the backslash variant', !api.isSafeReturnPath('/\\evil.com'));
check('rejects an absolute url', !api.isSafeReturnPath('https://evil.com/x'));
check('rejects a javascript: url', !api.isSafeReturnPath('javascript:alert(1)'));
check('rejects a bare relative path', !api.isSafeReturnPath('search.html'));
check('rejects a newline (header/parse tricks)', !api.isSafeReturnPath('/a\nb'));

// ── 9–12. Kaydet ve tüket ────────────────────────────────
{
  const { api: a, store } = load({ pathname: '/recipes/25500-x' });
  a.saveReturnIntent('25500');
  check('stores both the path and the favourite',
        store.has(a.RETURN_PATH_KEY) && store.has(a.PENDING_FAVORITE_KEY));
  check('returns the path to auth.js', a.takeReturnPath() === '/recipes/25500-x');
  // Tek kullanımlık: yönlendirme başarısız olsa bile niyet ortada kalmamalı,
  // yoksa kullanıcı bir SONRAKİ girişinde sebepsiz eski bir tarife atılır.
  check('the path is consumed exactly once', a.takeReturnPath() === null);
  // İKİ AYRI ANAHTAR olmasının sebebi: yolu okumak favori niyetini SİLMEMELİ.
  check('reading the path leaves the favourite intact', a.takePendingFavorite() === '25500');
}

// ── 13–14. Favori niyeti de tek kullanımlık ──────────────
{
  const { api: a } = load();
  a.saveReturnIntent('999');
  check('returns the pending favourite once', a.takePendingFavorite() === '999');
  check('and not twice', a.takePendingFavorite() === null);
}

// ── 15–16. ♡ yerine "koleksiyona ekle" tıklandıysa ───────
{
  const { api: a, store } = load();
  a.saveReturnIntent();                       // favoriteId YOK
  check('no favourite is recorded when none was asked for',
        !store.has(a.PENDING_FAVORITE_KEY));
  check('but the return path still is', a.takeReturnPath() !== null);
}

// ── 17–18. 🔴 Bayatlama — sekme paylaşımının sınırı ──────
{
  const { api: a, advance } = load();
  a.saveReturnIntent('25500');
  advance(a.INTENT_MAX_AGE_MS + 1000);
  check('a stale path is ignored', a.takeReturnPath() === null);
}
{
  const { api: a, advance } = load();
  a.saveReturnIntent('25500');
  advance(a.INTENT_MAX_AGE_MS + 1000);
  check('a stale favourite is ignored', a.takePendingFavorite() === null,
        'yoksa bir sonraki kullanıcının favorilerine yabancı bir tarif eklenir');
}

// ── 19. Depoda kurcalanmış yol OKURKEN de eleniyor ───────
// Yazma anında geçerli olan bir değerin depoda değişmediği VARSAYILMIYOR.
{
  const { api: a } = load({
    store: { return_path_v1: JSON.stringify({ value: '//evil.com', at: NOW }) },
  });
  check('a tampered path is rejected on read', a.takeReturnPath() === null);
}

// ── 20–21. Bozuk / eksik kayıt ───────────────────────────
{
  const { api: a } = load({ store: { return_path_v1: 'not json{' } });
  check('corrupt storage does not throw', a.takeReturnPath() === null);
}
{
  const { api: a } = load({ store: { return_path_v1: JSON.stringify({ value: '/x' }) } });
  check('a record without a timestamp is ignored', a.takeReturnPath() === null);
}

// ── 22–23. Depolama hiç yoksa (Safari gizli mod) ─────────
// Bu dosya giriş akışının içinde çalışıyor: burada fırlatılan bir istisna
// "hiç kimse giriş yapamıyor" demek (Faz 13b dersi).
{
  const { api: a } = load({ throws: true });
  let threw = false;
  try { a.saveReturnIntent('1'); } catch (e) { threw = true; }
  check('saving never throws when storage is blocked', !threw);
  check('reading returns null when storage is blocked', a.takeReturnPath() === null);
}

// ── 24. Temizleme her iki anahtarı da siliyor ────────────
{
  const { api: a, store } = load();
  a.saveReturnIntent('25500');
  a.clearReturnIntent();
  check('clearing removes both keys', store.size === 0, String(store.size));
}

// ── 25–27. Bağlantılar: dosyalar birbirini gerçekten çağırıyor mu ──
const FRONTEND = path.join(__dirname, '..', 'frontend');
const authJs = fs.readFileSync(path.join(FRONTEND, 'js', 'auth.js'), 'utf8');
const recipeJs = fs.readFileSync(path.join(FRONTEND, 'js', 'recipe.js'), 'utf8');
const apiJs = fs.readFileSync(path.join(FRONTEND, 'js', 'api.js'), 'utf8');

check('auth.js sends the user back to the stored path', /takeReturnPath\(\)/.test(authJs));
check('recipe.js completes the pending favourite', /takePendingFavorite\(\)/.test(recipeJs));
// Faz 20 dersi: aynı sekmede hesap değişince önceki kullanıcının izi kalmamalı.
check('signing out clears the intent',
      /return_path_v1/.test(apiJs) && /pending_favorite_v1/.test(apiJs));

// ── 28–29. Script sırası: intent.js tüketicilerinden ÖNCE ──
// Sonra yüklenirse `takeReturnPath` tanımsız olur. auth.js'te `typeof`
// koruması var (giriş akışı ölmesin diye) ama o zaman özellik SESSİZCE
// çalışmaz — yani sıra teste bağlı olmalı.
for (const [page, consumer] of [['index.html', 'js/auth.js'], ['recipe.html', 'js/api.js']]) {
  const html = fs.readFileSync(path.join(FRONTEND, page), 'utf8');
  check(`${page} loads intent.js before ${consumer}`,
        html.indexOf('js/intent.js') > -1 &&
        html.indexOf('js/intent.js') < html.indexOf(consumer));
}

console.log(failures === 0
  ? `\nreturn intent checks passed (${pass})`
  : `\n${failures} problem(s)`);
process.exit(failures === 0 ? 0 : 1);
