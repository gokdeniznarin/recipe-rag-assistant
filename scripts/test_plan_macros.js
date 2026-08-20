/**
 * Meal Plan sayfasındaki GÜNLÜK BESİN TOPLAMI davranış testi (sahte DOM).
 *
 *   node scripts/test_plan_macros.js
 *
 * NEDEN VAR: bu özellik ekrana SAYI basıyor ve yanlış bir sayı, eksik bir
 * sayıdan farklı olarak kendini belli etmiyor — sayfa hatasız görünür, toplam
 * sessizce yanlış olur. Sabitlenen dört kırılma biçimi:
 *   1. aynı tarif iki slotta → İKİ öğün, iki kez sayılmalı
 *   2. kartta alan yoksa (eski backend) → 0, "NaN" DEĞİL
 *   3. tarif veri setinden kalkmışsa (`recipe: null`) → toplam patlamamalı
 *   4. boş gün → dört değer de 0 (istenen davranış; gizlemek değil)
 * Ayrıca değer↔etiket eşleşmesi: proteini "carb" başlığı altında göstermek
 * hiçbir şeyi kırmaz, o yüzden testte her makro FARKLI bir sayı taşıyor.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'js', 'plan.js'), 'utf8');

let pass = 0;
let failures = 0;
const check = (name, cond, extra) => {
  if (cond) { console.log('  ok    ' + name); pass++; }
  else { console.error('  FAIL  ' + name + (extra ? ' :: ' + extra : '')); failures++; }
};

// ── Sahte DOM ────────────────────────────────────────────
function element(tag) {
  const classes = new Set();
  let text = '';
  let html = '';
  const el = {
    tag,
    children: [],
    handlers: {},
    title: '',
    className: '',
    href: '',
    disabled: false,
    // `escapeHtml` gerçekten çalışsın diye textContent → innerHTML kaçışı
    // taklit ediliyor; aksi hâlde tarif adları testte boş dizeye düşerdi.
    get textContent() { return text; },
    set textContent(v) {
      text = String(v);
      html = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },
    get innerHTML() { return html; },
    set innerHTML(v) { html = String(v); if (v === '') el.children.length = 0; },
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
      toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
    },
    appendChild(child) { el.children.push(child); return child; },
    addEventListener(type, fn) { el.handlers[type] = fn; },
    querySelector() { return element('stub'); },
    querySelectorAll() { return []; },
    setAttribute() {},
    focus() {},
  };
  return el;
}

function build({ weekPayload } = {}) {
  const byId = {};
  const requests = [];

  const ctx = {
    console,
    URLSearchParams,
    setTimeout: () => 0,
    document: {
      getElementById: (id) => (byId[id] = byId[id] || element('div')),
      createElement: (tag) => element(tag),
    },
    window: { location: { search: '' } },
    Logger: {
      get: () => ({ debug() {}, info() {}, warn() {}, error() {} }),
      timed: (fn) => fn,
      duration() {},
    },
    apiRequest: (url) => {
      requests.push(url);
      return Promise.resolve(weekPayload || { week_start: '2026-07-27', entries: [] });
    },
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);

  // plan.js hiçbir şey export etmiyor (klasik <script>). Kaynağın SONUNA
  // eklenen satır aynı sözcüksel kapsamda çalışıyor, yani `entries` gibi
  // top-level `let`'lere erişebiliyor — üretim koduna test kancası açmadan.
  vm.runInContext(
    SRC + '\n;globalThis.__test = {'
        + ' render(e, week) { entries = e; currentWeek = week; renderWeek(); },'
        + ' MACROS };',
    ctx
  );

  return { ctx, byId, requests };
}

// Bir gün sütununun SON çocuğu = toplam bloğu.
function macrosOf(dayCol) {
  const el = dayCol.children[dayCol.children.length - 1];
  return {
    el,
    className: el.className,
    title: el.title,
    values: [...el.innerHTML.matchAll(/day-macro-value">(-?[\d.]+)/g)].map(m => m[1]),
    labels: [...el.innerHTML.matchAll(/day-macro-label">([a-z]+)</g)].map(m => m[1]),
  };
}

const MONDAY = '2026-07-27';           // gerçek bir pazartesi
const recipe = (over = {}) => ({
  id: '1', name: 'Test Recipe', total_time_min: 20,
  calories: 300, protein_content: 25, carbohydrate_content: 10, fat_content: 5,
  ...over,
});
const entry = (date, slot, over) => ({ date, slot, recipe_id: '1', recipe: recipe(over) });

// ── 1. Izgara: her gün beş öğe, sonuncusu toplam ─────────
{
  const { ctx, byId } = build();
  ctx.__test.render([], MONDAY);
  const grid = byId['week-grid'];
  check('grid renders 7 day columns', grid.children.length === 7, `got ${grid.children.length}`);
  const col = grid.children[0];
  check('each day column has 5 items (head + 3 slots + totals)',
        col.children.length === 5, `got ${col.children.length}`);
  check('the totals block is the LAST item of the day',
        macrosOf(col).className.startsWith('day-macros'));
}

// ── 2. Boş gün: dört değer de 0 ──────────────────────────
{
  const { ctx, byId } = build();
  ctx.__test.render([], MONDAY);
  const m = macrosOf(byId['week-grid'].children[0]);
  check('empty day shows four zeros', JSON.stringify(m.values) === '["0","0","0","0"]',
        JSON.stringify(m.values));
  check('empty day is dimmed, not hidden', m.className.includes('day-macros--empty'));
  check('labels are kcal / prot / carb / fat',
        JSON.stringify(m.labels) === '["kcal","prot","carb","fat"]', JSON.stringify(m.labels));
}

// ── 3. Tek tarif: değerler kartın kendisinden ────────────
{
  const { ctx, byId } = build();
  // Her makro FARKLI bir sayı: değer/etiket çaprazlanırsa test görsün.
  ctx.__test.render([entry(MONDAY, 'dinner')], MONDAY);
  const m = macrosOf(byId['week-grid'].children[0]);
  check('one recipe: values come straight from the card',
        JSON.stringify(m.values) === '["300","25","10","5"]', JSON.stringify(m.values));
  check('a planned day is not dimmed', !m.className.includes('day-macros--empty'));
}

// ── 4. İki öğün toplanıyor ve yuvarlanıyor ───────────────
{
  const { ctx, byId } = build();
  ctx.__test.render([
    entry(MONDAY, 'lunch',  { calories: 396.7, protein_content: 31.9, carbohydrate_content: 11.3, fat_content: 24.5 }),
    entry(MONDAY, 'dinner', { calories: 12.4,  protein_content: 0.2,  carbohydrate_content: 0.4,  fat_content: 0.5 }),
  ], MONDAY);
  const m = macrosOf(byId['week-grid'].children[0]);
  check('two meals are summed and rounded',
        JSON.stringify(m.values) === '["409","32","12","25"]', JSON.stringify(m.values));
}

// ── 5. Aynı tarif iki slotta = İKİ öğün ──────────────────
{
  const { ctx, byId } = build();
  ctx.__test.render([entry(MONDAY, 'lunch'), entry(MONDAY, 'dinner')], MONDAY);
  const m = macrosOf(byId['week-grid'].children[0]);
  check('the same recipe planned twice counts twice', m.values[0] === '600', m.values[0]);
}

// ── 6. Günler birbirine karışmıyor ───────────────────────
{
  const { ctx, byId } = build();
  ctx.__test.render([
    entry(MONDAY, 'dinner'),
    entry('2026-07-29', 'lunch', { calories: 111 }),
  ], MONDAY);
  const cols = byId['week-grid'].children;
  check('monday counts only monday', macrosOf(cols[0]).values[0] === '300');
  check('wednesday counts only wednesday', macrosOf(cols[2]).values[0] === '111');
  check('an untouched day stays at zero', macrosOf(cols[1]).values[0] === '0');
}

// ── 7. 🔴 Eski backend: alan yoksa 0, "NaN" DEĞİL ────────
// Render ile Vercel AYRI AYRI deploy oluyor: bu dosyanın yeni, API'nin hâlâ
// eski olduğu bir pencere var ve orada kartta üç makro yok. TEK bir NaN
// toplamın tamamını NaN yapar → ekranda "NaN kcal".
{
  const { ctx, byId } = build();
  ctx.__test.render([{
    date: MONDAY, slot: 'dinner', recipe_id: '1',
    recipe: { id: '1', name: 'Old card', calories: 300, total_time_min: 20 },
  }], MONDAY);
  const m = macrosOf(byId['week-grid'].children[0]);
  check('a card without the new fields degrades to 0, never NaN',
        JSON.stringify(m.values) === '["300","0","0","0"]', JSON.stringify(m.values));
  check('no NaN anywhere in the rendered totals', !/NaN/.test(m.el.innerHTML));
}

// ── 8. Silinmiş tarif (recipe: null) ─────────────────────
{
  const { ctx, byId } = build();
  ctx.__test.render([
    entry(MONDAY, 'lunch'),
    { date: MONDAY, slot: 'dinner', recipe_id: '99999', recipe: null },
  ], MONDAY);
  const m = macrosOf(byId['week-grid'].children[0]);
  check('a recipe that no longer exists does not break the total',
        m.values[0] === '300', m.values[0]);
  check('...and the day is not dimmed (something IS planned)',
        !m.className.includes('day-macros--empty'));
  check('...and the tooltip says it was left out',
        /no longer available/.test(m.title), m.title);
  check('a day with no gaps carries the plain tooltip',
        /Daily total of the recipes/.test(macrosOf(byId['week-grid'].children[1]).title));
}

// ── 9. Sıfır/negatif değerler toplamı bozmuyor ───────────
{
  const { ctx, byId } = build();
  ctx.__test.render([
    entry(MONDAY, 'lunch',  { calories: 0, protein_content: 0, carbohydrate_content: 0, fat_content: 0 }),
    entry(MONDAY, 'dinner', { calories: -5, protein_content: 25, carbohydrate_content: 10, fat_content: 5 }),
  ], MONDAY);
  const m = macrosOf(byId['week-grid'].children[0]);
  check('bogus (0 / negative) numbers are skipped, not subtracted',
        JSON.stringify(m.values) === '["0","25","10","5"]', JSON.stringify(m.values));
}

// ── 10. Alan adları backend kartıyla aynı ────────────────
// Bu dört ad `main._recipe_card`'daki anahtarların kopyası. Ayrışırsa hiçbir
// şey patlamaz, ekranda sessizce 0 görünür — 7. testteki pencerenin kalıcı
// hâli. Karşı taraf `test_meal_plan.py`'de sabitli.
{
  const { ctx } = build();
  check('field names match the API card contract',
        JSON.stringify(ctx.__test.MACROS.map(m => m.field)) ===
        JSON.stringify(['calories', 'protein_content', 'carbohydrate_content', 'fat_content']));
}

// ── 11. Yükleme yolu haftayı detaylarıyla istiyor ────────
// (Toplam kartlardan hesaplanıyor; `include_details` düşerse `recipe` hiç
// gelmez ve her gün 0 görünür.)
{
  const { requests } = build();
  check('the week is requested with include_details=true',
        requests.some(u => u.includes('include_details=true')), requests.join(' '));
}

console.log('');
if (failures) {
  console.error(`plan macros checks FAILED (${failures} of ${pass + failures})`);
  process.exit(1);
}
console.log(`plan macros checks passed (${pass})`);
