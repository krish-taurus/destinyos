// The signed-in report page: free report, the ₹499 three-year report and the ₹4,999 session.
(() => {
  const API = window.DESTINY_API || '';
  const WA = 'https://wa.me/917975554666';
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let me, buys = { purchases: [], ready: false };

  async function api(path, method = 'GET', body) {
    let res;
    try { res = await fetch(API + path, { method, credentials: 'include', headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined }); }
    catch { throw new Error('No connection. Check your internet and try again.'); }
    const data = await res.json().catch(() => null);
    if (res.status === 401) { location.replace('/sign-in/'); throw Object.assign(new Error('Please sign in.'), { status: 401 }); }
    if (!res.ok) { const d = data && data.detail; throw Object.assign(new Error(typeof d === 'string' ? d : 'Something went wrong. Please try again.'), { status: res.status }); }
    return data;
  }
  const text = body => { const lines = String(body || '').split(/\n+/).map(l => l.trim()).filter(Boolean);
    return lines.length > 1 && lines.every(l => /^[•\-]/.test(l) || /^[A-Z][a-z]+ \d{4}:/.test(l))
      ? '<ul>' + lines.map(l => `<li>${esc(l.replace(/^[•\-]\s*/, ''))}</li>`).join('') + '</ul>'
      : lines.map(l => `<p>${esc(l.replace(/^•\s*/, ''))}</p>`).join(''); };
  const bought = item => buys.purchases.find(p => p.item === item && (p.status === 'paid' || p.status === 'fulfilled'));

  // ── waiting screen ──
  let rot = 0;
  function wait(title, lines) { $('page').classList.add('hide'); $('wait').classList.remove('hide'); $('retry').classList.add('hide'); $('wait-e').textContent = '';
    $('wait-h').textContent = title; clearInterval(rot); let i = 0; $('wait-t').textContent = lines[0] || '';
    if (lines.length > 1) rot = setInterval(() => { i = (i + 1) % lines.length; $('wait-t').textContent = lines[i]; }, 3200); scrollTo(0, 0); }
  function fail(msg, again) { clearInterval(rot); $('wait-h').textContent = 'That did not go through.'; $('wait-t').textContent = ''; $('wait-e').textContent = msg;
    $('retry').classList.remove('hide'); $('retry').onclick = again; }
  function done() { clearInterval(rot); $('wait').classList.add('hide'); $('page').classList.remove('hide'); }

  // ── the report ──
  function count(node, to) { if (still) return node.textContent = to; const t0 = performance.now(); (function f(t) { const p = Math.min(1, (t - t0) / 1100); node.textContent = Math.round(to * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(f); })(t0); }
  function renderCore(r) {
    const n = (r.numbers || me.numerology).pythagorean;
    $('hello').textContent = `Namaste, ${me.name.split(' ')[0]}.`; $('headline').textContent = r.headline || '';
    count($('n-lp'), n.lifePath);
    $('four').innerHTML = [['Birth number', n.birthNumber], ['Expression', n.expression], ['Soul urge', n.soulUrge], ['Personal year', n.personalYear]]
      .map(([l, v]) => `<div><b>${esc(v)}</b><span>${l}</span></div>`).join('');
    const open = r.sections.filter(s => !s.locked), shut = r.sections.filter(s => s.locked);
    $('sections').innerHTML = open.map(s => `<article class="sec"><h2>${esc(s.title)}</h2><div class="body">${text(s.body)}</div></article>`).join('');
    $('locked').classList.toggle('hide', !shut.length);
    $('locks').innerHTML = shut.map(s => `<div><svg width="18" height="20" viewBox="0 0 18 20" fill="none" stroke="#E7B45A" stroke-width="1.8" aria-hidden="true"><rect x="2" y="9" width="14" height="10" rx="1.5"/><path d="M5 9V6a4 4 0 018 0v3"/></svg><p><b>${esc(s.title)}</b><span>${esc(s.teaser)}</span></p></div>`).join('');
  }
  async function loadCore() {
    let r;
    try { r = await api('/api/report'); }
    catch (e) {
      if (e.status !== 404) throw e;
      wait('Your report is being written.', ['Counting the numbers in your name and birth date…', 'Placing the planets for the moment you were born…', 'Finding the life chapter you are in now…', 'Writing it in plain words. This takes about a minute.']);
      r = await api('/api/report', 'POST');
    }
    renderCore(r);
  }

  // ── three-year report ──
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const day = (s, back = 0) => { const d = new Date(new Date(s + 'T00:00:00Z') - back * 864e5); return `${d.getUTCDate()} ${MON[d.getUTCMonth()]}`; };
  function renderYears(t) {
    const cal = Object.fromEntries((t.calendar || []).map(c => [c.year, c]));
    const yrs = t.years.map(y => { const c = cal[y.year] || { dasha: [] };
      const total = c.dasha.reduce((a, d) => a + (new Date(d.end) - new Date(d.start)), 0) || 1;
      const strip = c.dasha.length ? `<div class="strip" role="img" aria-label="Dasha periods in ${y.year}">${c.dasha.map(d => `<i style="flex:${(new Date(d.end) - new Date(d.start)) / total}" title="${esc(d.maha)}–${esc(d.antar)}">${(new Date(d.end) - new Date(d.start)) / total > .14 ? esc(d.antar) : ''}</i>`).join('')}</div>
        <div class="months"><span>Jan</span><span>Apr</span><span>Jul</span><span>Oct</span><span>Dec</span></div>
        <p class="legend">${c.dasha.map(d => `<b style="color:var(--lamp-2)">${esc(d.maha)}–${esc(d.antar)}</b> ${day(d.start)} to ${day(d.end, 1)}`).join(' · ')}</p>` : '';
      return `<article class="year"><div class="yhead"><b>${esc(y.year)}</b><div><h3>${esc(y.theme)}</h3><span>Personal Year ${esc(c.personal_year ?? '')}</span></div></div>
        ${strip}<div class="body">${text(y.overview)}</div>
        <div class="cols"><div><h4>Work and money</h4><p>${esc(y.work_money)}</p></div><div><h4>Relationships</h4><p>${esc(y.relationships)}</p></div><div><h4>Energy and habits</h4><p>${esc(y.energy_habits)}</p></div></div>
        <div class="two"><div><b>Supportive months</b>${esc(y.good_months)}</div><div><b>Go slowly</b>${esc(y.go_slow)}</div></div>
        <div class="acts"><h4>Three steps for ${esc(y.year)}</h4><ol>${(y.actions || []).map(a => `<li>${esc(a)}</li>`).join('')}</ol></div></article>`; }).join('');
    const first = t.years[0].year;
    $('years').innerHTML = `<h2>${first} to ${first + 2}.</h2><p class="lead" style="margin-top:14px">${esc(t.headline)}</p>
      <div class="stand"><h3>Where you stand today</h3><p>${esc(t.where_you_stand)}</p>${t.halia_answers ? '' : '<p class="cap" style="margin-top:10px">Written without HALIA answers. Answer the questions in HALIA chat for guidance that starts from your own life.</p>'}</div>
      ${yrs}
      <article class="year"><h3 style="font-size:clamp(32px,6vw,56px)">What to build across three years</h3><div class="body">${text(t.three_year_plan)}</div><div class="body"><p>${esc(t.closing)}</p></div>
        <p class="noprint" style="margin-top:26px"><button class="btn pdf">Download the full report as PDF</button> <span class="err pdf-e" role="alert" style="display:block"></span></p></article>
      <div class="fine"><p class="cap" style="max-width:44em">The Personal Year numbers and Dasha periods are calculated from your birth details using the Pythagorean method and the Lahiri sidereal system. What they mean is a matter of tradition and is offered for reflection, not as a prediction. The steps follow the HALIA method and come from the answers you gave. Nothing here replaces medical, legal or financial advice.</p></div>`;
    $('years').classList.remove('hide'); $('offer3').classList.add('hide'); $('prep').classList.add('hide');
    wirePdf();
  }
  async function writeYears(pid) {
    wait('Your three years are being written.', ['Working out your Personal Year for each year…', 'Laying out your Dasha periods month by month…', 'Reading each year for work, relationships and energy…', 'Building your plan from your answers. This takes about a minute.']);
    try { const t = await api(`/api/addon/${pid}/generate`, 'POST'); const r = await api('/api/report'); renderCore(r); renderYears(t); done(); $('years').scrollIntoView(); }
    catch (e) { fail(e.message, () => writeYears(pid)); }
  }

  const QS = [['Q_L_CAREER_V1', 'How satisfied are you with your work or studies right now?'], ['Q_L_RELATIONSHIPS_V1', 'How satisfied are you with your closest relationships right now?'],
    ['Q_L_MONEY_V1', 'How in control of your money do you feel right now?'], ['Q_L_HAPPINESS_V1', 'Overall, how satisfied are you with life these days?'], ['Q_L_WELLBEING_V1', 'How would you rate your energy this week?']];
  const SCALE = [['1', 'Very low'], ['2', 'Low'], ['3', 'OK'], ['4', 'Good'], ['5', 'Very good']];
  const EXTRA = [['Q_FOCUS_PILLAR_V1', 'What would you most like to improve right now?', [['career', 'Career'], ['relationships', 'Relationships'], ['money', 'Money'], ['happiness', 'Happiness'], ['health', 'Health']]],
    ['Q_TIME_AVAILABLE_V1', 'How much time could you realistically spare each day?', [['5', '5 minutes'], ['15', '15 minutes'], ['30', '30 minutes'], ['60', 'An hour or more']]]];
  // pid given: the paid report is written afterwards. No pid: only the snapshot is refreshed.
  async function prep(pid) {
    const after = () => pid ? writeYears(pid) : ($('prep').classList.add('hide'), snapshot(true));
    if (!me.age_18) return pid && writeYears(pid);
    let st; try { st = await api('/api/halia/state'); } catch { return pid && writeYears(pid); }
    const have = Object.fromEntries((st.answers || []).map(a => [a.field, String(a.value)]));
    const all = [...QS.map(([id, q]) => [id, q, SCALE]), ...EXTRA];
    $('qs').innerHTML = all.map(([id, q, opts]) => { const f = id.slice(2, -3);
      return `<fieldset class="q" style="border:0"><legend style="font:500 18px var(--sans);margin-bottom:10px">${q}</legend><div class="seg">${opts.map(([c, l]) => `<label><input type="radio" name="${id}" value="${c}"${have[f] === c ? ' checked' : ''}><span>${l}</span></label>`).join('')}</div></fieldset>`; }).join('');
    $('prep-h').textContent = pid ? 'Seven questions before we write.' : 'Seven questions about your life today.';
    $('prep-lead').textContent = pid ? 'HALIA starts from your life today, so your plan is built on your own answers. It takes about a minute.' : 'HALIA works only from what you tell it. Answer what you can; it takes about a minute.';
    $('b-prep').textContent = pid ? 'Write my three-year report' : 'Show where I stand'; $('skip').classList.toggle('hide', !pid);
    $('h-consent-text').textContent = st.consent_text; $('h-consent').checked = !!st.consented; $('h-consent').closest('label').classList.toggle('hide', !!st.consented);
    if (pid) $('offer3').classList.add('hide'); $('prep').classList.remove('hide'); done(); $('prep').scrollIntoView();
    $('skip').onclick = () => writeYears(pid);
    $('f-prep').onsubmit = async ev => { ev.preventDefault(); const E = $('e-prep'); E.textContent = '';
      const picked = all.map(([id]) => [id, (document.querySelector(`input[name=${id}]:checked`) || {}).value]).filter(([, v]) => v);
      if (!picked.length) return E.textContent = pid ? 'Answer at least one question, or write it without your answers.' : 'Answer at least one question.';
      if (!st.consented && !$('h-consent').checked) return E.textContent = 'Tick the box so HALIA can use your answers.';
      $('b-prep').disabled = true;
      try { if (!st.consented) await api('/api/halia/consent', 'POST', { consent: true, daily_optin: false });
        for (const [id, v] of picked) await api('/api/halia/answers', 'POST', { question_id: id, value: v });
        after(); }
      catch (e) { E.textContent = e.message; }
      $('b-prep').disabled = false; };
  }

  // ── HALIA snapshot: worked out by the engine from the person's own answers ──
  async function snapshot(scroll) {
    if (!me.age_18) return;
    const S = $('snap'); let s = null;
    try { s = await api('/api/halia/snapshot'); } catch (e) { if (e.status !== 403) return; }
    if (!s || !s.answered) {
      S.innerHTML = `<h2>Where do you stand today?</h2><p class="lead" style="margin-top:14px">Your chart describes the sky you were born under. HALIA looks at your life as it is now: work, relationships, money, happiness and health. Seven questions, one minute, and it gives you one step to take today.</p>
        <p style="margin-top:22px"><button class="btn" id="snap-go">Answer seven questions</button></p>`;
    } else {
      S.innerHTML = `<h2>Where you stand today.</h2><p class="lead" style="margin-top:14px">${s.chosen ? `You chose to work on ${esc(s.focus_name.toLowerCase())} first.` : `${esc(s.focus_name)} is your lowest area right now, so HALIA starts there.`}</p>
        <div class="lv">${s.levels.map(l => `<div class="${l.pillar === s.lowest ? 'low' : ''}"><span>${esc(l.name)}</span><i style="--w:${(l.value || 0) * 20}%"></i><b>${esc(l.label || 'Not answered')}</b></div>`).join('')}</div>
        <div class="step"><span class="cap">One step for today, about ${esc(s.minutes)} minutes</span><p>${esc(s.step)}</p></div>
        <p class="cap" style="margin-top:14px;max-width:44em">${esc(s.note)} <button class="link" id="snap-go" style="padding:0;font-size:14.5px">Update my answers</button></p>`;
    }
    S.classList.remove('hide'); $('snap-go').onclick = () => prep(null); if (scroll) S.scrollIntoView();
  }

  // ── PDF download ──
  async function pdf(btn) { const was = btn.textContent, E = btn.parentNode.querySelector('.pdf-e'); btn.disabled = true; btn.textContent = 'Preparing your PDF…'; if (E) E.textContent = '';
    try { const res = await fetch(API + '/api/report/pdf', { credentials: 'include' });
      if (!res.ok) { const d = await res.json().catch(() => null); throw new Error(d && typeof d.detail === 'string' ? d.detail : 'The PDF could not be made just now. Try again.'); }
      const url = URL.createObjectURL(await res.blob()), a = document.createElement('a');
      a.href = url; a.download = (/filename="([^"]+)"/.exec(res.headers.get('content-disposition') || '') || [])[1] || 'Destiny-OS-report.pdf';
      document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000); }
    catch (e) { if (E) E.textContent = e.message === 'Failed to fetch' ? 'No connection. Check your internet and try again.' : e.message; }
    btn.disabled = false; btn.textContent = was; }
  const wirePdf = () => document.querySelectorAll('button.pdf').forEach(b => b.onclick = () => pdf(b));

  // ── payments ──
  const rzp = () => window.Razorpay ? Promise.resolve() : new Promise((res, rej) => { const s = document.createElement('script'); s.src = 'https://checkout.razorpay.com/v1/checkout.js'; s.onload = res; s.onerror = () => rej(new Error('The payment window could not load. Check your connection.')); document.head.appendChild(s); });
  async function pay(item, coupon) {
    const o = await api('/api/billing/order', 'POST', { item, coupon: coupon || null }); if (o.free) return o.purchase_id; await rzp();
    return new Promise((res, rej) => new Razorpay({ key: o.key_id, order_id: o.order_id, amount: o.amount, currency: 'INR', name: 'Destiny OS', description: o.description,
      prefill: { name: o.name, contact: o.phone }, theme: { color: '#E7B45A' }, modal: { ondismiss: () => rej(new Error('')) },
      handler: p => api('/api/billing/order/verify', 'POST', p).then(v => res(v.purchase_id), rej) }).open());
  }
  document.querySelectorAll('.code-t').forEach(b => b.onclick = () => { $(b.dataset.for).classList.remove('hide'); $(b.dataset.for).focus(); b.classList.add('hide'); });
  function sell(btn, errId, item, label, then, codeId) {
    if (!buys.ready) { const a = document.createElement('a'); a.className = btn.className; a.textContent = 'Ask for it on WhatsApp'; a.target = '_blank'; a.rel = 'noopener';
      a.href = WA + '?text=' + encodeURIComponent(`Hi, I'd like the ${label}. My name is ${me.name}.`); btn.replaceWith(a);
      $(errId).style.color = 'var(--dim)'; $(errId).textContent = 'Online payment opens shortly.'; return; }
    btn.onclick = async () => { $(errId).textContent = ''; btn.disabled = true;
      try { then(await pay(item, $(codeId).value.trim())); } catch (e) { $(errId).textContent = e.message; }
      btn.disabled = false; };
  }
  async function session(pid) { try { const r = await api(`/api/addon/${pid}/generate`, 'POST');
      $('buyS').outerHTML = `<a class="btn wide" href="${esc(r.whatsapp)}" target="_blank" rel="noopener">Schedule on WhatsApp</a>`; $('e-buyS').style.color = 'var(--lamp-2)'; $('e-buyS').textContent = 'Paid. Thank you.'; }
    catch (e) { $('e-buyS').textContent = e.message; } }

  async function start() {
    wait('Opening your report…', []);
    try {
      me = await api('/api/me');
      [buys] = await Promise.all([api('/api/billing/purchases'), loadCore()]);
      const b3 = bought('three_year'), bs = bought('consultation');
      snapshot();
      if (bs) session(bs.id); else sell($('buyS'), 'e-buyS', 'consultation', '30-minute personal session with Dr. Krish', session, 'codeS');
      if (b3 && b3.status === 'fulfilled') { const all = await api('/api/addon/reports'); const t = all.reports.find(r => r.kind === 'three_year'); if (t) renderYears(t); }
      else if (b3) return prep(b3.id);
      else { $('offer3').classList.remove('hide'); sell($('buy3'), 'e-buy3', 'three_year', 'three-year report', prep, 'code3'); }
      done();
    } catch (e) { if (e.status !== 401) fail(e.message, start); }
  }
  wirePdf();
  $('out').onclick = async () => { try { await api('/api/auth/logout', 'POST'); } catch {} location.replace('/'); };
  start();
})();
