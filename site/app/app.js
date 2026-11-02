/* Destiny OS customer panel */
const API = (window.DESTINY_API || '').replace(/\/$/, '');
const $ = id => document.getElementById(id);
const esc = t => String(t ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = t => esc(t).replace(/\n/g, '<br>').replace(/\*(.*?)\*/g, '<strong>$1</strong>');
const todayISO = () => new Date().toLocaleDateString('en-CA');
const MEALS_KEY = 'destinyos.meals.v2';

let me = null, report = null, sys = 'pythagorean', chart = null;
let pending = { phone: null, signup: null };

/* ── storage helpers (per-browser conveniences only) ── */
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
  sget(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
  sset(k, v) { try { sessionStorage.setItem(k, v); } catch (e) {} }
};
function meals() { const m = store.get(MEALS_KEY, null); return m && m.date === todayISO() ? m.items : []; }
function saveMeals(items) { store.set(MEALS_KEY, { date: todayISO(), items }); }

/* ── API ── */
class ApiError extends Error { constructor(msg, status) { super(msg); this.status = status; } }
async function api(path, { method = 'GET', body, form } = {}) {
  const opt = { method, credentials: 'same-origin', headers: {} };
  if (form) opt.body = form;
  else if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(API + path, opt); } catch (e) { throw new ApiError('No connection. Check your internet and try again.', 0); }
  let data = null; try { data = await res.json(); } catch (e) {}
  if (!res.ok) {
    const msg = data && typeof data.detail === 'string' ? data.detail : res.status >= 500 ? 'Something went wrong on our side. Try again shortly.' : 'Check your details and try again.';
    if (res.status === 401 && !path.startsWith('/api/auth')) { showAuth(); }
    throw new ApiError(msg, res.status);
  }
  return data;
}
function toast(t) { const el = $('toast'); el.textContent = t; el.classList.remove('hide'); clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.add('hide'), 3200); }
function busy(btn, on, label) { if (!btn) return; if (on) { btn.dataset.l = btn.textContent; btn.textContent = label || 'Please wait…'; btn.disabled = true; } else { btn.textContent = btn.dataset.l || btn.textContent; btn.disabled = false; } }

/* ── source tracking: /free-report?src=instagram → stored until registration ── */
(function () { const s = new URLSearchParams(location.search).get('src'); if (s) store.sset('dos_src', s.slice(0, 40)); })();

/* ───────── AUTH ───────── */
function showAuth() { $('screen-panel').classList.add('hide'); $('screen-auth').classList.remove('hide'); step('step-phone'); }
function step(id) { ['step-phone', 'step-code', 'step-details'].forEach(s => $(s).classList.toggle('hide', s !== id)); const f = $(id).querySelector('input'); if (f) setTimeout(() => f.focus(), 50); }

async function sendOtp(btn) {
  $('err-phone').textContent = $('err-code').textContent = '';
  busy(btn, true, 'Sending…');
  try {
    const r = await api('/api/auth/otp', { method: 'POST', body: { phone: $('in-phone').value } });
    pending.phone = r.phone;
    $('code-sent-to').textContent = `We sent it to ${r.phone}.` + (r.dev_mode ? ' (Test mode: the code is in the server log.)' : '');
    step('step-code');
  } catch (e) { (pending.phone ? $('err-code') : $('err-phone')).textContent = e.message; }
  finally { busy(btn, false); }
}
$('btn-otp').onclick = e => sendOtp(e.target);
$('in-phone').onkeydown = e => { if (e.key === 'Enter') $('btn-otp').click(); };
$('btn-resend').onclick = e => sendOtp(e.target);
$('btn-change').onclick = () => { pending.phone = null; step('step-phone'); };
$('in-code').oninput = e => { e.target.value = e.target.value.replace(/\D/g, ''); if (e.target.value.length === 6) $('btn-verify').click(); };
$('btn-verify').onclick = async e => {
  $('err-code').textContent = '';
  busy(e.target, true, 'Checking…');
  try {
    const r = await api('/api/auth/verify', { method: 'POST', body: { phone: pending.phone, code: $('in-code').value } });
    if (r.needs_registration) {
      pending.signup = r.signup_token;
      try { $('consent-text').textContent = (await api('/api/auth/consent-text')).text; } catch (_) {}
      step('step-details');
    } else { await enter(); }
  } catch (err) { $('err-code').textContent = err.message; $('in-code').value = ''; }
  finally { busy(e.target, false); }
};
$('btn-register').onclick = async e => {
  const v = id => $(id).value.trim();
  $('err-details').textContent = '';
  if (!v('in-name') || !v('in-dob') || !v('in-city')) return $('err-details').textContent = 'Enter your name, date of birth and birth city.';
  if (!$('in-consent').checked) return $('err-details').textContent = 'Please tick the consent box to continue.';
  busy(e.target, true, 'Creating…');
  try {
    await api('/api/auth/register', { method: 'POST', body: {
      signup_token: pending.signup, name: v('in-name'), dob: v('in-dob'), birth_time: v('in-time') || null, city: v('in-city'),
      consent: true, whatsapp_optin: $('in-wa').checked, source: store.sget('dos_src') } });
    await enter(true);
  } catch (err) { $('err-details').textContent = err.message; }
  finally { busy(e.target, false); }
};

/* ───────── PANEL ───────── */
async function loadMe() { me = await api('/api/me'); return me; }
const plus = () => me && me.plan.subscribed;

async function enter(isNew) {
  await loadMe();
  $('screen-auth').classList.add('hide'); $('screen-panel').classList.remove('hide');
  $('hello-name').textContent = me.name.split(' ')[0] + '.';
  $('today-label').textContent = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' });
  renderPlan();
  await showReport(isNew);
  const want = (location.hash || '').slice(1);
  if (want && $('page-' + want)) page(want);
}

function renderPlan() {
  const p = me.plan;
  $('plan-pill').textContent = p.subscribed ? 'Destiny Plus' : 'Free';
  $('plan-pill').classList.toggle('plus', p.subscribed);
  $('top-upgrade').classList.toggle('hide', p.subscribed);
}

/* navigation */
function page(id) {
  document.querySelectorAll('.page').forEach(p => p.classList.toggle('on', p.id === 'page-' + id));
  document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('on', b.dataset.page === id));
  history.replaceState(null, '', '#' + id);
  window.scrollTo(0, 0);
  ({ today: showToday, ask: showAsk, charts: showCharts, compass: showCompass, food: showFood, extras: showExtras, account: showAccount }[id] || (() => {}))();
}
$('nav').onclick = e => { const b = e.target.closest('button[data-page]'); if (b) page(b.dataset.page); };
document.addEventListener('click', e => { if (e.target.closest('.js-upgrade')) openSub(); });
$('top-upgrade').onclick = () => openSub();

function lockCard(el, title, text) {
  $(el).innerHTML = `<div class="card lockcard"><div class="ic">✦</div><h3>${esc(title)}</h3><p class="muted">${esc(text)}</p>
    <button class="btn btn-dark js-upgrade">Unlock with Destiny Plus · ₹599/month</button></div>`;
}

/* ── report ── */
const NUM_LABELS = [['lifePath', 'Life Path'], ['expression', 'Expression'], ['soulUrge', 'Soul Urge'], ['personalYear', 'Personal Year']];
async function showReport(autoCreate) {
  ['report-empty', 'report-loading', 'report-used', 'report-out'].forEach(i => $(i).classList.add('hide'));
  if (me.has_report) {
    try { report = await api('/api/report'); return renderReport(); } catch (e) { $('err-report').textContent = e.message; }
  }
  if (me.free_report_available || plus()) {
    $('report-empty').classList.remove('hide');
    $('btn-make-report').textContent = plus() ? 'Create my full report' : 'Create my free report';
    if (autoCreate) createReport();
  } else $('report-used').classList.remove('hide');
}
async function createReport() {
  $('report-empty').classList.add('hide'); $('report-loading').classList.remove('hide');
  const lis = [...$('load-steps').children]; let i = 0;
  lis.forEach(l => l.className = '');
  const tick = setInterval(() => { if (i > 0) lis[i - 1].className = 'done'; if (i < lis.length) lis[i].className = 'on'; i = Math.min(i + 1, lis.length); }, 2200);
  try {
    report = await api('/api/report', { method: 'POST' });
    me.has_report = true; me.free_report_available = false;
    renderReport();
  } catch (e) {
    $('report-loading').classList.add('hide');
    if (e.status === 402) { $('report-used').classList.remove('hide'); }
    else { $('report-empty').classList.remove('hide'); $('err-report').textContent = e.message; }
  } finally { clearInterval(tick); }
}
$('btn-make-report').onclick = () => createReport();

function renderReport() {
  ['report-empty', 'report-loading', 'report-used'].forEach(i => $(i).classList.add('hide'));
  $('report-out').classList.remove('hide');
  $('rep-headline').textContent = report.headline || 'Your blueprint';
  const n = (report.numbers || me.numerology).pythagorean, c = (report.numbers || me.numerology).chaldean;
  $('rep-numbers').innerHTML = NUM_LABELS.map(([k, l]) => `<div><small>${l}</small><b>${esc(n[k])}</b><span>Pythagorean</span></div>`).join('') +
    `<div><small>Name (Chaldean)</small><b>${esc(c.expressionCompound)}/${esc(c.expression)}</b><span>Compound / root</span></div>`;
  let anyLocked = false;
  $('rep-sections').innerHTML = report.sections.map((s, i) => {
    if (s.locked) { anyLocked = true; return `<div class="card sec locked" style="animation:rise .5s ${i * 60}ms both"><span class="lock">🔒 PLUS</span><h3>${esc(s.title)}</h3><p>${esc(s.teaser)}</p><div class="blur"></div></div>`; }
    return `<div class="card sec" style="animation:rise .5s ${i * 60}ms both"><h3>${esc(s.title)}</h3><p>${esc(s.body)}</p></div>`;
  }).join('');
  $('rep-upsell').classList.toggle('hide', !anyLocked);
}

/* ── today ── */
const MEANING = { 1: 'Initiation', 2: 'Cooperation', 3: 'Expression', 4: 'Foundation', 5: 'Change', 6: 'Harmony', 7: 'Introspection', 8: 'Achievement', 9: 'Completion', 11: 'Illumination', 22: 'Master building', 33: 'Master teaching' };
async function showToday() {
  $('err-today').textContent = '';
  if (!plus()) { $('today-out').classList.add('hide'); return lockCard('today-lock', 'Daily guidance is part of Destiny Plus', 'Your Personal Day, today\'s transits, colours to wear, three decisions for the day, and a manifestation practice, every morning on WhatsApp and here.'); }
  $('today-lock').innerHTML = '';
  const pd = me.numerology.pythagorean.personalDay;
  $('pd-num').textContent = pd; $('pd-name').textContent = MEANING[pd] || '';
  try {
    const b = await api('/api/brief', { method: 'POST', body: { meals: meals() } });
    $('num-note').textContent = b.numerology_note || '';
    $('astro-head').textContent = b.astro_headline || ''; $('astro-detail').textContent = b.astro_detail || '';
    $('manifest-today').innerHTML = fmt(b.manifestation || '');
    const ic = { go: '✓', pause: '⏸', stop: '✕' };
    $('decisions').innerHTML = (b.decisions || []).map(d => `<div class="dec"><i class="${esc(d.type)}">${ic[d.type] || '•'}</i><div><b>${esc(d.text)}</b><div class="muted small">${esc(d.why)}</div></div></div>`).join('');
    const sw = a => (a || []).map(c => `<div><span style="background:${/^#[0-9a-f]{3,8}$/i.test(c.hex) ? c.hex : '#ccc'}"></span>${esc(c.name)}</div>`).join('');
    $('wear').innerHTML = sw(b.wear); $('avoid').innerHTML = sw(b.avoid);
    $('psych-tip').textContent = b.psychology_tip || ''; $('extra').textContent = b.extra ? '✦ ' + b.extra : '';
    $('today-out').classList.remove('hide');
  } catch (e) { $('err-today').textContent = e.message; }
}

/* ── ask ── */
const turns = [];
function bubble(html, who) { const d = document.createElement('div'); d.className = 'msg ' + who; d.innerHTML = html; $('chat-msgs').appendChild(d); $('chat-msgs').scrollTop = 1e6; }
function qLeft(q) {
  if (!q) return;
  $('q-left').textContent = q.kind === 'free' ? `${q.left} of ${q.of} free questions left · Destiny Plus = ask as many as you like` : `${q.left} questions left today (fair use)`;
}
function showAsk() {
  qLeft(me.questions);
  if (!$('chat-msgs').children.length) {
    const n = me.numerology.pythagorean;
    bubble(fmt(`🌅 *Hi ${me.name.split(' ')[0]}.* Today is your Personal Day ${n.personalDay} (${MEANING[n.personalDay]}). Ask me about timing, decisions, colours or how to handle something today.`), 'bot');
  }
}
async function sendChat(text) {
  text = (text || '').trim(); if (!text) return;
  bubble(fmt(text), 'me'); turns.push({ role: 'user', content: text });
  const t = document.createElement('div'); t.className = 'typing'; t.innerHTML = '<i></i><i></i><i></i>'; $('chat-msgs').appendChild(t);
  try {
    const r = await api('/api/ask', { method: 'POST', body: { turns: turns.slice(-12), meals: meals() } });
    turns.push({ role: 'assistant', content: r.reply }); t.remove(); bubble(fmt(r.reply), 'bot');
    me.questions = r.questions; qLeft(r.questions);
  } catch (e) {
    turns.pop(); t.remove();
    bubble(esc(e.message) + (e.status === 402 ? ' <button class="link js-upgrade">Get Destiny Plus</button>' : ''), 'bot');
    if (e.status === 402) openSub();
  }
}
$('chat-send').onclick = () => { sendChat($('chat-input').value); $('chat-input').value = ''; };
$('chat-input').onkeydown = e => { if (e.key === 'Enter') $('chat-send').click(); };
$('chat-chips').onclick = e => { const b = e.target.closest('[data-q]'); if (b) sendChat(b.dataset.q); };

/* ── charts ── */
const NUM_DESC = { lifePath: ['Life Path', 'The broad theme of your life'], birthNumber: ['Birth number (Mulank)', 'Your day of birth, reduced'],
  expression: ['Name number', 'How you express your talents'], soulUrge: ['Soul Urge', 'What you most deeply want'],
  personality: ['Personality', 'How others first see you'], personalYear: ['Personal Year', 'This year\'s theme'] };
function renderNums() {
  const n = me.numerology[sys];
  $('num-grid').innerHTML = Object.entries(NUM_DESC).map(([k, [t, d]], i) =>
    `<div style="animation-delay:${i * 50}ms"><b>${k === 'expression' ? `${n.expressionCompound}/${n.expression}` : n[k]}</b><strong>${t}</strong><span>${d}</span>${MEANING[n[k]] ? `<em class="theme">${MEANING[n[k]]}</em>` : ''}</div>`).join('');
}
$('sys-seg').onclick = e => { const b = e.target.closest('[data-sys]'); if (!b) return; sys = b.dataset.sys; [...$('sys-seg').children].forEach(x => x.classList.toggle('on', x === b)); renderNums(); };
async function showCharts() {
  renderNums();
  if (chart) return;
  try {
    chart = await api('/api/chart');
    const order = ['Sun', 'Moon', 'Mars', 'Mercury', 'Jupiter', 'Venus', 'Saturn', 'Rahu', 'Ketu'];
    const row = (k, p, extra) => `<tr><td>${k}${p.retrograde ? ' ℞' : ''}</td><td>${esc(p.sign)} ${(+p.degree).toFixed(1)}° · ${esc(p.nakshatra)}</td><td>${extra}</td></tr>`;
    $('natal-tbl').innerHTML = (chart.lagna ? row('Lagna', chart.lagna, '1st') : '') + order.map(k => row(k, chart.natal[k], chart.natal[k].house ? 'H' + chart.natal[k].house : '')).join('');
    $('transit-tbl').innerHTML = order.map(k => row(k, chart.transits[k], 'H' + chart.transits[k].house_from_moon + ' from Moon')).join('');
    const md = chart.dasha.mahadasha, ad = chart.dasha.antardasha;
    $('md-lord').textContent = md.lord + ' Mahadasha'; $('md-dates').textContent = `${md.start} to ${md.end} · ${md.years} years`;
    const pct = Math.min(100, Math.max(0, (Date.now() - new Date(md.start)) / (new Date(md.end) - new Date(md.start)) * 100));
    requestAnimationFrame(() => $('md-bar').style.width = pct.toFixed(0) + '%');
    $('ad-text').innerHTML = (ad ? `Antardasha: <strong>${esc(ad.lord)}</strong> (${esc(ad.start)} to ${esc(ad.end)}). ` : '') + `Birth nakshatra: ${esc(chart.dasha.birth_nakshatra)}. Next: ${esc(chart.dasha.next_mahadasha.lord)} from ${esc(chart.dasha.next_mahadasha.start)}.`;
    $('chart-notes').textContent = (chart.notes || []).join(' ');
  } catch (e) { $('chart-notes').textContent = e.message; }
}

/* ── compass ── */
let compass = null;
function showCompass() {
  if (!plus()) { $('compass-form').classList.add('hide'); return lockCard('compass-lock', 'Life Compass is part of Destiny Plus', 'A personalised 30-day plan across body, mind, money, relationships and purpose, built from your numbers, your Dasha and your goals.'); }
  $('compass-lock').innerHTML = ''; $('compass-form').classList.remove('hide');
}
const PILLARS = [['body', 'Body'], ['mind', 'Mind'], ['money', 'Money'], ['relationships', 'Relationships'], ['purpose', 'Purpose']];
$('compass-btn').onclick = async e => {
  busy(e.target, true, 'Building your plan…'); $('compass-status').textContent = 'This can take up to a minute.';
  try {
    compass = await api('/api/compass', { method: 'POST', body: { context: { work: $('ctx-work').value, goal_90_days: $('ctx-goal').value, energy: $('ctx-energy').value, sleep: $('ctx-sleep').value, weighing_on_them: $('ctx-worry').value } } });
    $('compass-status').textContent = compass.headline || ''; renderCompass('money');
  } catch (err) { $('compass-status').textContent = err.message; }
  finally { busy(e.target, false); }
};
function renderCompass(active) {
  const f = compass.focus || {}, kinds = { evidence: 'Evidence', classical: 'Classical', symbolic: 'Symbolic' };
  const recs = (compass.pillars && compass.pillars[active]) || [];
  $('compass-out').innerHTML = `<div class="focus">${PILLARS.map(([k, l]) => `<div><b>${Math.round(+f[k] || 0)}/10</b>${l}</div>`).join('')}</div>
    <div class="tabs">${PILLARS.map(([k, l]) => `<button data-p="${k}" class="${k === active ? 'on' : ''}">${l}</button>`).join('')}</div>
    ${recs.map(r => { const k = kinds[r.kind] ? r.kind : 'evidence'; return `<div class="rec"><b>${esc(r.title)}<span class="tag ${k}">${kinds[k]}</span></b><span class="muted small">${esc(r.why)}</span></div>`; }).join('') || '<p class="muted">Nothing for this pillar.</p>'}`;
  $('compass-out').querySelectorAll('[data-p]').forEach(b => b.onclick = () => renderCompass(b.dataset.p));
}

/* ── food ── */
let foodBlob = null;
function showFood() {
  if (!plus()) { $('food-ui').classList.add('hide'); return lockCard('food-lock', 'Food Lens is part of Destiny Plus', 'Photograph your plate to see calories and macros, and how the meal fits your day.'); }
  $('food-lock').innerHTML = ''; $('food-ui').classList.remove('hide'); renderLog();
}
async function shrink(file, max = 1568) {
  const url = URL.createObjectURL(file);
  const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
  const s = Math.min(1, max / Math.max(img.width, img.height)), cv = document.createElement('canvas');
  cv.width = Math.round(img.width * s); cv.height = Math.round(img.height * s);
  cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height); URL.revokeObjectURL(url);
  return new Promise(res => cv.toBlob(res, 'image/jpeg', 0.85));
}
$('food-file').onchange = async e => {
  const f = e.target.files[0]; if (!f) return;
  try { foodBlob = await shrink(f); $('drop-inner').innerHTML = `<img src="${URL.createObjectURL(foodBlob)}" alt="Your meal">`; $('food-btn').disabled = false; }
  catch (_) { $('food-status').textContent = "That file couldn't be opened as a photo. Try a JPEG or PNG."; }
};
$('food-btn').onclick = async e => {
  if (!foodBlob) return;
  busy(e.target, true, 'Reading your plate…'); $('food-status').textContent = 'This can take 10–30 seconds.';
  const fd = new FormData(); fd.append('image', foodBlob, 'meal.jpg'); fd.append('hint', $('food-hint').value.trim()); fd.append('meals', JSON.stringify(meals()));
  try {
    const r = await api('/api/food', { method: 'POST', form: fd }), n = v => Math.round(+v || 0);
    $('food-status').textContent = '';
    $('food-out').innerHTML = `<h3 class="h3">${esc(r.meal_name || 'Your meal')}</h3><div class="macros"><div><b>${n(r.kcal_best)}</b>kcal (${n(r.kcal_low)}–${n(r.kcal_high)})</div><div><b>${n(r.protein_g)}g</b>Protein</div><div><b>${n(r.carbs_g)}g</b>Carbs</div><div><b>${n(r.fat_g)}g</b>Fat</div></div>
      ${(r.items || []).map(i => `<div class="rec small"><b>${esc(i.name)}</b><span class="muted">${esc(i.portion)} · ${n(i.kcal)} kcal</span></div>`).join('')}<p class="small" style="margin-top:10px">${esc(r.advice || '')}</p>`;
    if ((r.items || []).length) { const m = meals(); m.push({ name: r.meal_name || 'Meal', kcal: n(r.kcal_best), p: n(r.protein_g), time: new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) }); saveMeals(m); renderLog(); }
  } catch (err) { $('food-status').textContent = err.message; }
  finally { busy(e.target, false); }
};
function renderLog() {
  const m = meals(); if (!m.length) return $('meal-log').textContent = 'No meals logged yet today.';
  $('meal-log').innerHTML = m.map(x => `<div>${esc(x.time)} · ${esc(x.name)} · ~${x.kcal} kcal</div>`).join('') + `<div style="margin-top:6px"><b>~${m.reduce((a, x) => a + x.kcal, 0)} kcal · ${m.reduce((a, x) => a + x.p, 0)} g protein today</b></div>`;
}

/* ── extras (one-time add-ons) ── */
async function showExtras() {
  try {
    const p = await api('/api/billing/purchases');
    document.querySelectorAll('[data-price]').forEach(el => { const a = p.addons[el.dataset.price]; if (a) el.textContent = '₹' + a.price_inr.toLocaleString('en-IN'); });
    const r = await api('/api/addon/reports');
    $('extras-out').innerHTML = r.reports.map(renderAddon).join('');
  } catch (e) { $('err-extras').textContent = e.message; }
}
function renderAddon(r) {
  if (r.kind === 'compatibility') {
    return `<div class="card"><div class="lbl-sm">Compatibility · ${esc(r.partner)}</div><h3 class="h3">${esc(r.headline)} · ${esc(r.score)}/10</h3>${Object.entries(r.sections || {}).map(([k, v]) => `<p class="small" style="margin-top:8px"><b>${esc(k.replace(/_/g, ' '))}:</b> ${esc(v)}</p>`).join('')}</div>`;
  }
  return `<div class="card"><div class="lbl-sm">Annual forecast · ${esc(r.year)}</div><h3 class="h3">${esc(r.headline)}</h3><p class="small">${esc(r.year_theme)}</p>
    ${(r.months || []).map(m => `<div class="rec small"><b>${esc(m.month)} · Personal Month ${esc(m.personal_month)}</b><span>${esc(m.theme)}. Focus: ${esc(m.focus)}. Careful: ${esc(m.caution)}</span></div>`).join('')}
    <p class="small" style="margin-top:10px"><b>Best windows:</b> ${esc(r.best_windows)}</p></div>`;
}
document.addEventListener('click', async e => {
  const b = e.target.closest('.js-buy'); if (!b) return;
  $('err-extras').textContent = '';
  const item = b.dataset.item, details = item === 'compatibility' ? { name: $('cp-name').value.trim(), dob: $('cp-dob').value, relation: $('cp-rel').value } : null;
  if (item === 'compatibility' && (!details.name || !details.dob)) return $('err-extras').textContent = 'Add their full name and date of birth.';
  busy(b, true, 'Opening payment…');
  try {
    const o = await api('/api/billing/order', { method: 'POST', body: { item, details } });
    await loadCheckout();
    new Razorpay({ key: o.key_id, order_id: o.order_id, amount: o.amount, currency: 'INR', name: 'Destiny OS', description: o.description,
      prefill: { name: o.name, contact: o.phone }, theme: { color: '#15171F' },
      handler: async resp => {
        try {
          const v = await api('/api/billing/order/verify', { method: 'POST', body: resp });
          toast('Payment received. Preparing it now…');
          const out = await api(`/api/addon/${v.purchase_id}/generate`, { method: 'POST' });
          if (out.kind === 'consultation') { toast('Booked! Opening WhatsApp to schedule.'); window.open(out.whatsapp, '_blank', 'noopener'); }
          else $('extras-out').insertAdjacentHTML('afterbegin', renderAddon(out));
        } catch (err) { $('err-extras').textContent = err.message; }
      } }).open();
  } catch (err) { $('err-extras').textContent = err.message; }
  finally { busy(b, false); }
});

/* ── account ── */
function showAccount() {
  $('acct-details').innerHTML = `<b>${esc(me.name)}</b><br>${esc(me.phone)}<br>Born ${esc(me.dob)}${me.birth_time ? ' at ' + esc(me.birth_time) : ''} · ${esc(me.city)}`;
  const p = me.plan, until = p.paid_until ? new Date(p.paid_until * 1000).toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' }) : '';
  $('acct-plan').innerHTML = p.subscribed
    ? `<p><b>Active</b>${until ? ` · paid until ${until}` : ''}</p><p class="muted small">₹599/month. If you cancel, you keep access until the end of the month you've paid for.</p><button class="btn btn-line sm" id="cancel-sub">Cancel subscription</button>`
    : `<p class="muted small">You're on the free plan.</p><button class="btn btn-dark sm js-upgrade">Get Destiny Plus · ₹599/month</button>`;
  const c = $('cancel-sub'); if (c) c.onclick = cancelSub;
  $('goal').value = me.manifest_goal || ''; $('acct-wa').checked = me.whatsapp_optin;
}
$('save-goal').onclick = async e => {
  busy(e.target, true, 'Saving…');
  try { await api('/api/me', { method: 'PATCH', body: { manifest_goal: $('goal').value, whatsapp_optin: $('acct-wa').checked } }); me.manifest_goal = $('goal').value; me.whatsapp_optin = $('acct-wa').checked; $('goal-saved').textContent = 'Saved.'; }
  catch (err) { $('goal-saved').textContent = err.message; }
  finally { busy(e.target, false); }
};
async function cancelSub() {
  if (!confirm('Cancel Destiny Plus? You keep access until the end of the month you\'ve paid for.')) return;
  try { await api('/api/billing/cancel', { method: 'POST' }); await loadMe(); renderPlan(); showAccount(); toast('Cancelled. You keep access until your paid period ends.'); }
  catch (e) { toast(e.message); }
}
$('logout').onclick = async () => { try { await api('/api/auth/logout', { method: 'POST' }); } catch (_) {} location.href = '/'; };
$('delete').onclick = async () => {
  if (!confirm('Delete your account and all your data permanently? Any subscription is cancelled now.')) return;
  if (prompt('Type DELETE to confirm') !== 'DELETE') return;
  try { await api('/api/me', { method: 'DELETE' }); try { localStorage.removeItem(MEALS_KEY); } catch (_) {} alert('Your account and data have been deleted.'); location.href = '/'; }
  catch (e) { toast(e.message); }
};

/* ── subscribe ── */
function openSub() { $('err-sub').textContent = ''; $('modal-sub').classList.remove('hide'); }
$('sub-close').onclick = () => $('modal-sub').classList.add('hide');
$('modal-sub').onclick = e => { if (e.target.id === 'modal-sub') $('modal-sub').classList.add('hide'); };
function loadCheckout() {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((res, rej) => { const s = document.createElement('script'); s.src = 'https://checkout.razorpay.com/v1/checkout.js'; s.onload = res; s.onerror = () => rej(new Error('Couldn\'t load the payment window. Check your connection.')); document.head.appendChild(s); });
}
$('sub-pay').onclick = async e => {
  $('err-sub').textContent = '';
  busy(e.target, true, 'Opening payment…');
  try {
    const s = await api('/api/billing/subscribe', { method: 'POST' });
    await loadCheckout();
    new Razorpay({ key: s.key_id, subscription_id: s.subscription_id, name: 'Destiny OS', description: s.description,
      prefill: { name: s.name, contact: s.phone }, theme: { color: '#15171F' },
      handler: async resp => {
        try {
          await api('/api/billing/subscribe/verify', { method: 'POST', body: resp });
          await loadMe(); renderPlan(); $('modal-sub').classList.add('hide');
          toast('Welcome to Destiny Plus ✨');
          if (me.has_report) { report = await api('/api/report'); renderReport(); } else showReport(true);
          page('report');
        } catch (err) { $('err-sub').textContent = err.message; }
      } }).open();
  } catch (err) { $('err-sub').textContent = err.message; }
  finally { busy(e.target, false); }
};

/* ── boot ── */
(async function boot() {
  try { await enter(); } catch (e) { if (e.status !== 401) toast(e.message); showAuth(); }
})();
