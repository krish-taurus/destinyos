/* Destiny OS beta — frontend logic */
const API = (window.DESTINY_API || '').replace(/\/$/, '');
const STORE_KEY = 'destinyos.profile.v1';
const $ = id => document.getElementById(id);
const esc = t => String(t ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const todayISO = () => new Date().toLocaleDateString('en-CA');

let profile = null;   // {name, dob, time, city, numerology, chart, chartDate}
let meals = [];       // today's meals
let brief = null;

/* ── Storage (per-browser; safe if unavailable) ── */
function save() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify({ profile, meals, mealsDate: todayISO() })); } catch (e) {}
}
function load() {
  try {
    const d = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
    if (!d || !d.profile) return false;
    profile = d.profile;
    meals = d.mealsDate === todayISO() ? (d.meals || []) : [];
    return true;
  } catch (e) { return false; }
}

/* ── API ── */
async function api(path, body, isForm = false) {
  const res = await fetch(API + path, {
    method: 'POST',
    headers: isForm ? undefined : { 'Content-Type': 'application/json' },
    body: isForm ? body : JSON.stringify(body)
  });
  let data = null;
  try { data = await res.json(); } catch (e) {}
  if (!res.ok) throw new Error((data && data.detail && (typeof data.detail === 'string' ? data.detail : 'Check your details and try again.')) || 'Server unavailable. Try again shortly.');
  return data;
}
function apiProfile(extra = {}) {
  return { name: profile.name, numerology: profile.numerology, chart: slimChart(profile.chart), meals, ...extra };
}
function slimChart(c) {
  if (!c) return null;
  return { lagna: c.lagna, natal: c.natal, dasha: c.dasha, transits: c.transits, moon_today: c.moon_today };
}

/* ── Numerology ── */
const PYTH = {}; 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('').forEach((c, i) => PYTH[c] = (i % 9) + 1);
const CHALD = { A:1,B:2,C:3,D:4,E:5,F:8,G:3,H:5,I:1,J:1,K:2,L:3,M:4,N:5,O:7,P:8,Q:1,R:2,S:3,T:4,U:6,V:6,W:6,X:5,Y:1,Z:7 };
const VOWELS = 'AEIOU';
const reduce = n => { while (n > 9 && ![11, 22, 33].includes(n)) n = String(n).split('').reduce((a, d) => a + +d, 0); return n; };
const reduceFull = n => { while (n > 9) n = String(n).split('').reduce((a, d) => a + +d, 0); return n; };
const sumName = (name, map, type) => name.toUpperCase().replace(/[^A-Z]/g, '').split('').reduce((a, ch) => {
  if (type === 'v' && !VOWELS.includes(ch)) return a;
  if (type === 'c' && VOWELS.includes(ch)) return a;
  return a + (map[ch] || 0);
}, 0);

function numerology(name, dob, map = PYTH, when = new Date()) {
  const [y, m, d] = dob.split('-').map(Number);
  const lifePath = reduce(reduce(m) + reduce(d) + reduce(y));
  const py = reduceFull(reduceFull(m) + reduceFull(d) + reduceFull(when.getFullYear()));
  const pm = reduceFull(py + when.getMonth() + 1);
  const pd = reduceFull(pm + when.getDate());
  return {
    lifePath, birthNumber: reduceFull(d),
    expression: reduce(sumName(name, map)), expressionCompound: sumName(name, map),
    soulUrge: reduce(sumName(name, map, 'v')), personality: reduce(sumName(name, map, 'c')),
    personalYear: py, personalMonth: pm, personalDay: pd
  };
}

const MEANING = {
  1: ['Initiation', 'Start things, lead, act independently.'],
  2: ['Cooperation', 'Partnership, listening, patient diplomacy.'],
  3: ['Expression', 'Create, communicate, connect socially.'],
  4: ['Foundation', 'Structure, discipline, finish practical work.'],
  5: ['Change', 'Adapt, explore, try something new.'],
  6: ['Harmony', 'Family, care, responsibility, beauty.'],
  7: ['Introspection', 'Research, reflection, spiritual work.'],
  8: ['Achievement', 'Money, authority, decisive execution.'],
  9: ['Completion', 'Release, finish, give back.'],
  11: ['Illumination', 'Intuition and inspiration (master number).'],
  22: ['Master building', 'Large practical vision (master number).'],
  33: ['Master teaching', 'Service and healing (master number).']
};
const COLOUR = { 1: ['Gold', '#D4A017'], 2: ['Cream', '#F3E9D2'], 3: ['Yellow', '#E8C547'], 4: ['Grey-blue', '#6C7A89'],
  5: ['Green', '#3D9A5F'], 6: ['Rose', '#E3A1B5'], 7: ['Violet', '#7B5EA7'], 8: ['Navy', '#1C2E5A'], 9: ['Red', '#B83A3A'] };

/* ── Screens & nav ── */
function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  $(id).classList.add('active');
  document.body.classList.toggle('in-app', id === 'screen-dashboard');
}
function showPage(id) {
  document.querySelectorAll('.page-section').forEach(p => p.classList.remove('active'));
  $('page-' + id).classList.add('active');
  document.querySelectorAll('[data-page]').forEach(n => n.classList.toggle('active', n.dataset.page === id));
  window.scrollTo(0, 0);
  if (id === 'chat' && !$('wa-messages').children.length) greet();
}
document.addEventListener('click', e => {
  const nav = e.target.closest('[data-page]');
  if (nav) return showPage(nav.dataset.page);
  const go = e.target.closest('[data-goto]');
  if (go) return showPage(go.dataset.goto);
  const q = e.target.closest('[data-q]');
  if (q) return sendChat(q.dataset.q);
  const sys = e.target.closest('[data-sys]');
  if (sys) {
    document.querySelectorAll('[data-sys]').forEach(b => b.classList.toggle('active', b === sys));
    renderNumGrid(sys.dataset.sys);
  }
});

/* ── Onboarding ── */
$('btn-step1').onclick = () => {
  const name = $('inp-name').value.trim(), dob = $('inp-dob').value, city = $('inp-city').value.trim();
  $('step1-err').textContent = '';
  if (!name || !dob || !city) return $('step1-err').textContent = 'Enter your name, date of birth and birth city.';
  if (new Date(dob) > new Date()) return $('step1-err').textContent = 'Date of birth is in the future.';
  $('step-1').classList.remove('active'); $('step-2').classList.add('active');
};
$('btn-back').onclick = () => { $('step-2').classList.remove('active'); $('step-1').classList.add('active'); };
$('btn-start').onclick = async () => {
  if (!$('c-data').checked || !$('c-nature').checked) return $('step2-err').textContent = 'Tick both boxes to continue.';
  profile = { name: $('inp-name').value.trim(), dob: $('inp-dob').value, time: $('inp-time').value || null, city: $('inp-city').value.trim() };
  await buildProfile();
};

async function buildProfile() {
  showScreen('screen-loading');
  $('load-err').textContent = '';
  const step = (n, st) => $('ls-' + n).className = 'loading-step ' + st;
  try {
    step(1, 'active');
    profile.numerology = numerology(profile.name, profile.dob);
    step(1, 'done'); step(2, 'active');
    await new Promise(r => setTimeout(r, 300));
    step(2, 'done'); step(3, 'active');
    profile.chart = await api('/api/chart', { dob: profile.dob, time: profile.time, city: profile.city });
    profile.chartDate = todayISO();
    step(3, 'done'); step(4, 'active');
    await new Promise(r => setTimeout(r, 300));
    step(4, 'done');
    save();
    enterApp();
  } catch (e) {
    $('load-err').innerHTML = esc(e.message) + ' <button class="link-btn" id="retry">Go back</button>';
    $('retry').onclick = () => showScreen('screen-onboard');
  }
}

async function refreshDaily() {
  profile.numerology = numerology(profile.name, profile.dob);
  if (profile.chartDate !== todayISO()) {
    try {
      profile.chart = await api('/api/chart', { dob: profile.dob, time: profile.time, city: profile.city });
      profile.chartDate = todayISO();
      save();
    } catch (e) { /* keep yesterday's chart; brief still works */ }
  }
}

$('btn-reset').onclick = () => {
  if (!confirm('Erase your profile and meal log from this browser?')) return;
  try { localStorage.removeItem(STORE_KEY); } catch (e) {}
  location.reload();
};

/* ── Dashboard ── */
function enterApp() {
  showScreen('screen-dashboard');
  const first = profile.name.split(' ')[0];
  $('greeting-name').textContent = first;
  $('sidebar-name').textContent = profile.name;
  $('sidebar-avatar').textContent = first[0].toUpperCase();
  $('sidebar-sub').textContent = 'LIFE PATH ' + profile.numerology.lifePath;
  $('today-label').textContent = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).toUpperCase();
  renderNumerologyCard();
  renderNumGrid('pyth');
  renderAstrology();
  renderColourWeek();
  renderLog();
  loadBrief();
}

function renderNumerologyCard() {
  const n = profile.numerology, m = MEANING[n.personalDay];
  $('pd-num').textContent = n.personalDay;
  $('pd-name').textContent = m[0];
  $('pd-sub').textContent = `Personal Day ${n.personalDay} · Life Path ${n.lifePath}`;
}

async function loadBrief() {
  $('brief-err').textContent = '';
  try {
    brief = await api('/api/brief', apiProfile());
    $('num-note').textContent = brief.numerology_note || MEANING[profile.numerology.personalDay][1];
    $('astro-body').innerHTML = `<strong style="color:var(--nebula-light);font-size:14px">${esc(brief.astro_headline)}</strong><br>
      <span style="color:var(--stardust);font-size:12px;display:block;margin-bottom:8px">${esc(dashaLine())}</span>${esc(brief.astro_detail)}`;
    $('psych-tip').textContent = brief.psychology_tip || '';
    const icon = { go: ['go', '✓'], pause: ['pause', '⏸'], stop: ['stop', '✗'] };
    $('decisions').innerHTML = (brief.decisions || []).map(d => {
      const [cls, ic] = icon[d.type] || icon.pause;
      return `<div class="decision-item"><div class="decision-icon ${cls}">${ic}</div><div><div class="decision-text">${esc(d.text)}</div><div class="decision-reason">${esc(d.why)}</div></div></div>`;
    }).join('');
    const sw = (arr, avoid) => (arr || []).map(c => `<div class="swatch ${avoid ? 'avoid' : ''}"><div class="swatch-dot" style="background:${/^#[0-9a-f]{3,8}$/i.test(c.hex) ? c.hex : '#888'}"></div><div class="swatch-label">${esc(c.name)}</div></div>`).join('');
    $('wear').innerHTML = sw(brief.wear); $('avoid').innerHTML = sw(brief.avoid, true);
    if (brief.extra) { $('extra').style.display = 'block'; $('extra').innerHTML = '<strong style="color:var(--gold)">✦ </strong>' + esc(brief.extra); }
  } catch (e) {
    $('brief-err').textContent = e.message;
    $('num-note').textContent = MEANING[profile.numerology.personalDay][1];
    ['astro-body', 'psych-tip', 'decisions'].forEach(id => $(id).textContent = 'Guidance unavailable right now.');
  }
}

function dashaLine() {
  const c = profile.chart; if (!c) return '';
  const d = c.dasha;
  return `${c.lagna ? c.lagna.sign + ' lagna · ' : ''}${d.mahadasha.lord} Mahadasha · ${d.antardasha ? d.antardasha.lord + ' Antardasha' : ''}`;
}

function renderNumGrid(sys) {
  const n = numerology(profile.name, profile.dob, sys === 'pyth' ? PYTH : CHALD);
  const cells = [
    [n.lifePath, 'Life Path', MEANING[n.lifePath][1]],
    [n.birthNumber, 'Birth number (Mulank)', MEANING[n.birthNumber][1]],
    [`${n.expressionCompound}/${n.expression}`, 'Name number', MEANING[n.expression][1]],
    [n.soulUrge, 'Soul Urge', 'What you most deeply want.'],
    [n.personality, 'Personality', 'How others first see you.'],
    [n.personalDay, 'Personal Day', MEANING[n.personalDay][1]]
  ];
  $('num-grid').innerHTML = cells.map(c => `<div class="num-cell"><div class="num-cell-val">${c[0]}</div><div class="num-cell-name">${c[1]}</div><div class="num-cell-desc">${esc(c[2])}</div></div>`).join('');
  $('cycles').innerHTML = [['Personal Year', n.personalYear], ['Personal Month', n.personalMonth], ['Personal Day', n.personalDay]]
    .map(([l, v]) => `<div class="focus-cell"><b style="color:var(--gold)">${v}</b><span>${l} · ${MEANING[v][0]}</span></div>`).join('');
}

function renderAstrology() {
  const c = profile.chart; if (!c) return;
  const order = ['Sun', 'Moon', 'Mars', 'Mercury', 'Jupiter', 'Venus', 'Saturn', 'Rahu', 'Ketu'];
  const row = (k, p, extra) => `<tr><td>${k}${p.retrograde ? ' ℞' : ''}</td><td>${p.sign} ${p.degree.toFixed(1)}° · ${p.nakshatra}</td><td>${extra}</td></tr>`;
  $('natal-table').innerHTML = (c.lagna ? row('Lagna', c.lagna, '1st') : '') +
    order.map(k => row(k, c.natal[k], c.natal[k].house ? `H${c.natal[k].house}` : '')).join('');
  $('transit-table').innerHTML = order.map(k => row(k, c.transits[k], `H${c.transits[k].house_from_moon} from Moon`)).join('');
  const d = c.dasha, md = d.mahadasha;
  $('md-lord').textContent = md.lord + ' Mahadasha';
  $('md-dates').textContent = `${md.start} to ${md.end} (${md.years} years)`;
  const pct = Math.min(100, Math.max(0, (Date.now() - new Date(md.start)) / (new Date(md.end) - new Date(md.start)) * 100));
  $('md-bar').style.width = pct.toFixed(0) + '%';
  $('ad-text').innerHTML = (d.antardasha ? `Current Antardasha: <strong style="color:var(--moon)">${esc(d.antardasha.lord)}</strong> (${d.antardasha.start} to ${d.antardasha.end}).<br>` : '') +
    `Birth nakshatra: ${esc(d.birth_nakshatra)}. Next Mahadasha: ${esc(d.next_mahadasha.lord)} from ${d.next_mahadasha.start}.`;
  $('astro-sub').textContent = `Sidereal (Lahiri) · ${c.place ? c.place.city : ''} · ${c.time_known ? 'birth time given' : 'no birth time'}`;
  $('astro-notes').textContent = (c.notes || []).join(' ');
  $('planet-strip').innerHTML = ['Sun', 'Moon', 'Mercury', 'Venus'].map(k => `<div class="planet-chip"><div class="planet-name">${k.toUpperCase()}</div><div class="planet-pos">${c.transits[k].sign}</div></div>`).join('');
}

function renderColourWeek() {
  const days = [];
  for (let i = 0; i < 7; i++) {
    const dt = new Date(); dt.setDate(dt.getDate() + i);
    const pd = numerology(profile.name, profile.dob, PYTH, dt).personalDay;
    const [nm, hex] = COLOUR[pd];
    days.push(`<div style="background:${i ? 'var(--void)' : 'var(--void2)'};border-radius:8px;padding:10px 4px;text-align:center;font-size:11px;color:var(--stardust)">
      <div style="margin-bottom:6px">${dt.toLocaleDateString('en-IN', { weekday: 'short' })}</div>
      <div style="width:28px;height:28px;border-radius:50%;background:${hex};margin:0 auto 4px"></div>
      <div style="font-size:10px">${nm}</div><div style="font-family:'DM Mono',monospace;font-size:9px">Day ${pd}</div></div>`);
  }
  $('colour-week').innerHTML = days.join('');
}

/* ── Chat ── */
const turns = [];
function bubble(html, who) {
  const el = document.createElement('div');
  el.className = `wa-msg ${who} visible`;
  el.innerHTML = html + `<div class="msg-time">${new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</div>`;
  $('wa-messages').appendChild(el);
  $('wa-messages').scrollTop = $('wa-messages').scrollHeight;
  return el;
}
const fmt = t => esc(t).replace(/\n/g, '<br>').replace(/\*(.*?)\*/g, '<strong>$1</strong>');
function greet() {
  const n = profile.numerology;
  bubble(fmt(`🌅 *Hi ${profile.name.split(' ')[0]}.* Today is your Personal Day ${n.personalDay} (${MEANING[n.personalDay][0]}), and you're in your ${profile.chart ? profile.chart.dasha.mahadasha.lord : ''} Mahadasha.\n\nAsk me about timing, decisions, colours or how to handle something today.`), 'bot');
}
async function sendChat(text) {
  text = (text || '').trim(); if (!text) return;
  bubble(fmt(text), 'user');
  turns.push({ role: 'user', content: text });
  const typing = document.createElement('div');
  typing.className = 'typing-indicator visible';
  typing.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
  $('wa-messages').appendChild(typing);
  try {
    const r = await api('/api/ask', { profile: apiProfile(), turns: turns.slice(-12) });
    turns.push({ role: 'assistant', content: r.reply });
    typing.remove(); bubble(fmt(r.reply), 'bot');
  } catch (e) {
    turns.pop(); typing.remove(); bubble(esc(e.message), 'bot');
  }
}
$('wa-send').onclick = () => { sendChat($('wa-input').value); $('wa-input').value = ''; };
$('wa-input').onkeydown = e => { if (e.key === 'Enter') $('wa-send').click(); };

/* ── Food Lens ── */
let foodBlob = null;
const zone = $('drop-zone');
zone.onclick = () => $('food-file').click();
zone.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('food-file').click(); } };
zone.ondragover = e => { e.preventDefault(); zone.classList.add('over'); };
zone.ondragleave = () => zone.classList.remove('over');
zone.ondrop = e => { e.preventDefault(); zone.classList.remove('over'); if (e.dataTransfer.files[0]) setFood(e.dataTransfer.files[0]); };
$('food-file').onchange = e => { if (e.target.files[0]) setFood(e.target.files[0]); };

async function shrink(file, max = 1568) {
  const url = URL.createObjectURL(file);
  const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
  const scale = Math.min(1, max / Math.max(img.width, img.height));
  const cv = document.createElement('canvas');
  cv.width = Math.round(img.width * scale); cv.height = Math.round(img.height * scale);
  cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height);
  URL.revokeObjectURL(url);
  return new Promise(res => cv.toBlob(res, 'image/jpeg', 0.85));
}
async function setFood(file) {
  $('food-status').textContent = '';
  try {
    foodBlob = await shrink(file);
    $('drop-inner').innerHTML = `<img src="${URL.createObjectURL(foodBlob)}" alt="Your meal">`;
    $('food-btn').disabled = false;
  } catch (e) { $('food-status').textContent = "That file couldn't be opened as a photo. Try a JPEG or PNG."; }
}
$('food-btn').onclick = async () => {
  if (!foodBlob) return;
  $('food-btn').disabled = true;
  $('food-status').textContent = 'Reading your plate… this can take 10–30 seconds.';
  const fd = new FormData();
  fd.append('image', foodBlob, 'meal.jpg');
  fd.append('hint', $('food-hint').value.trim());
  fd.append('profile', JSON.stringify(apiProfile()));
  try {
    const r = await api('/api/food', fd, true);
    renderFood(r); $('food-status').textContent = '';
  } catch (e) { $('food-status').textContent = e.message; }
  finally { $('food-btn').disabled = false; }
};
function renderFood(r) {
  const n = v => Math.round(Number(v) || 0);
  $('food-out').style.display = 'block';
  $('food-title').textContent = r.meal_name || 'Your meal';
  $('macro-band').innerHTML = `
    <div class="macro"><b>${n(r.kcal_best)}</b><span>kcal (${n(r.kcal_low)}–${n(r.kcal_high)})</span></div>
    <div class="macro"><b>${n(r.protein_g)}g</b><span>Protein</span></div>
    <div class="macro"><b>${n(r.carbs_g)}g</b><span>Carbs</span></div>
    <div class="macro"><b>${n(r.fat_g)}g</b><span>Fat · ${n(r.fibre_g)}g fibre</span></div>`;
  const items = Array.isArray(r.items) ? r.items : [];
  $('food-items').innerHTML = items.map(i => `<div class="food-row"><span>${esc(i.name)} <span style="color:var(--stardust)">· ${esc(i.portion)}</span></span><span style="font-family:'DM Mono',monospace;color:var(--gold)">${n(i.kcal)} kcal</span></div>`).join('') +
    `<div class="note">Confidence: ${esc(r.confidence || 'medium')}</div>`;
  $('food-advice').textContent = r.advice || '';
  if (items.length) {
    meals.push({ name: r.meal_name || 'Meal', kcal: n(r.kcal_best), p: n(r.protein_g), time: new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) });
    save(); renderLog();
  }
}
function renderLog() {
  if (!meals.length) return $('meal-log').innerHTML = '<div class="note">No meals logged yet today.</div>';
  const kcal = meals.reduce((a, m) => a + m.kcal, 0), p = meals.reduce((a, m) => a + m.p, 0);
  $('meal-log').innerHTML = meals.map(m => `<div class="meal-log-item"><span>${esc(m.time)} · ${esc(m.name)}</span><span style="font-family:'DM Mono',monospace;color:var(--gold)">~${m.kcal} kcal</span></div>`).join('') +
    `<div class="note">Running total today: ~${kcal} kcal · ${p} g protein</div>`;
}

/* ── Life Compass ── */
const PILLARS = [['body', '💪 Body'], ['mind', '🧠 Mind'], ['money', '💰 Money'], ['relationships', '🤝 Relationships'], ['purpose', '🕉️ Purpose']];
let compass = null;
$('compass-btn').onclick = async () => {
  $('compass-btn').disabled = true;
  $('compass-status').textContent = 'Building your plan… this can take up to a minute.';
  const context = { work: $('ctx-work').value, goal_90_days: $('ctx-goal').value, energy: $('ctx-energy').value, sleep: $('ctx-sleep').value, weighing_on_them: $('ctx-worry').value };
  try {
    compass = await api('/api/compass', apiProfile({ context }));
    $('compass-status').textContent = compass.headline || '';
    renderCompass('money');
  } catch (e) { $('compass-status').textContent = e.message; }
  finally { $('compass-btn').disabled = false; }
};
function renderCompass(active) {
  $('compass-out').style.display = 'block';
  const f = compass.focus || {}, col = v => v >= 8 ? 'var(--coral)' : v >= 5 ? 'var(--gold)' : 'var(--jade)';
  $('focus-meter').innerHTML = PILLARS.map(([k, l]) => { const v = Math.round(+f[k] || 0); return `<div class="focus-cell"><b style="color:${col(v)}">${v}/10</b><span>${l}</span></div>`; }).join('');
  $('pillar-tabs').innerHTML = PILLARS.map(([k, l]) => `<button class="pillar-tab ${k === active ? 'active' : ''}" data-pillar="${k}">${l}</button>`).join('');
  $('pillar-tabs').querySelectorAll('[data-pillar]').forEach(b => b.onclick = () => renderCompass(b.dataset.pillar));
  const kinds = { evidence: 'Evidence', classical: 'Classical', symbolic: 'Symbolic' };
  const recs = (compass.pillars && compass.pillars[active]) || [];
  $('pillar-panel').innerHTML = recs.map(r => { const k = kinds[r.kind] ? r.kind : 'evidence';
    return `<div class="rec"><div class="rec-title">${esc(r.title)}<span class="tag ${k}">${kinds[k]}</span></div><div class="rec-why">${esc(r.why)}</div></div>`; }).join('') || '<div class="note">Nothing for this pillar.</div>';
}

/* ── Boot ── */
(async function boot() {
  if (load()) { await refreshDaily(); save(); enterApp(); }
})();
