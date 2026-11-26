// HALIA Match: profile, the matching questions, the swipe deck, matches and messages.
(() => {
  const API = window.DESTINY_API || '', $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let st, cards = [], busy = false, chat = null, poll = 0, lastId = 0;

  async function api(path, method = 'GET', body) {
    let res; try { res = await fetch(API + path, { method, credentials: 'include', headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined }); }
    catch { throw new Error('No connection. Check your internet and try again.'); }
    const d = await res.json().catch(() => null);
    if (res.status === 401) { location.replace('/sign-in/?next=/match/'); throw Object.assign(new Error(''), { status: 401 }); }
    if (!res.ok) throw Object.assign(new Error(d && typeof d.detail === 'string' ? d.detail : 'Something went wrong. Please try again.'), { status: res.status });
    return d;
  }
  const view = v => { ['setup', 'q', 'app'].forEach(x => $('v-' + x).classList.toggle('hide', x !== v)); $('boot').classList.add('hide'); scrollTo(0, 0); };
  const seg = (id, name, opts, val) => $(id).innerHTML = opts.map(([c, l]) => `<label><input type="radio" name="${name}" value="${c}"${c === val ? ' checked' : ''}><span>${l}</span></label>`).join('');
  const picked = name => (document.querySelector(`input[name=${name}]:checked`) || {}).value;

  // ── profile ──
  function setup(editing) {
    const p = st.profile || {};
    seg('p-gender', 'gender', [['woman', 'A woman'], ['man', 'A man'], ['other', 'Another identity']], p.gender);
    seg('p-seeking', 'seeking', [['women', 'Women'], ['men', 'Men'], ['everyone', 'Everyone']], p.seeking);
    seg('p-intent', 'intent', [['marriage', 'Marriage'], ['long_term', 'Long-term'], ['friendship', 'Friendship first']], p.intent || 'marriage');
    $('p-name').value = p.display_name || st.first_name; $('p-city').value = p.city || st.city; $('p-bio').value = p.bio || '';
    $('p-min').value = p.age_min || Math.max(18, st.age - 5); $('p-max').value = p.age_max || Math.min(80, st.age + 5);
    $('c-halia-t').textContent = st.halia_consent_text; $('c-show-t').textContent = st.consent_text;
    $('c-halia-l').classList.toggle('hide', st.halia_on); $('c-show-l').classList.toggle('hide', !!st.profile);
    $('c-active-l').classList.toggle('hide', !st.profile); $('c-active').checked = p.active !== 0 && p.active !== false;
    $('leave-row').classList.toggle('hide', !st.profile); $('b-prof').textContent = st.profile ? 'Save my profile' : 'Continue';
    $('setup-h').textContent = editing ? 'Your profile.' : 'Meet people who want the same life.';
    $('setup-lead').classList.toggle('hide', !!editing); $('how').classList.toggle('hide', !!editing);
    $('prof-back').classList.toggle('hide', !editing); $('minor').classList.toggle('hide', st.adult); $('f-prof').classList.toggle('hide', !st.adult);
  }
  $('f-prof').onsubmit = async ev => { ev.preventDefault(); const E = $('e-prof'); E.textContent = '';
    if (!picked('gender') || !picked('seeking')) return E.textContent = 'Choose who you are and who you want to meet.';
    if (!st.halia_on && !$('c-halia').checked) return E.textContent = 'Tick the first box so HALIA can use your answers.';
    if (!st.profile && !$('c-show').checked) return E.textContent = 'Tick the box to be shown to other people.';
    $('b-prof').disabled = true;
    try {
      if (!st.halia_on) await api('/api/halia/consent', 'POST', { consent: true, daily_optin: false });
      const first = !st.profile;
      await api('/api/match/profile', 'PUT', { display_name: $('p-name').value.trim(), gender: picked('gender'), seeking: picked('seeking'), age_min: +$('p-min').value, age_max: +$('p-max').value,
        city: $('p-city').value.trim(), intent: picked('intent'), bio: $('p-bio').value.trim(), consent: true, active: first ? true : $('c-active').checked });
      st = await api('/api/match/profile');
      first || st.answers.answered === 0 ? questions() : open('deck');
    } catch (e) { E.textContent = e.message; }
    $('b-prof').disabled = false; };
  $('leave').onclick = () => $('leave-yes').classList.remove('hide');
  $('leave-yes').onclick = async () => { try { await api('/api/match/profile', 'DELETE'); location.replace('/report/'); } catch (e) { $('e-prof').textContent = e.message; } };

  // ── the matching questions (the HALIA 'couple' domain) ──
  async function questions() {
    view('q'); $('e-q').textContent = '';
    const [s, n] = await Promise.all([api('/api/halia/state'), api('/api/halia/questions/next?domain=couple')]);
    const cov = s.coverage.find(c => c.domain === 'couple'), q = n.question, FIELDS = cov.of;
    if (!q || cov.answered >= FIELDS || !COUPLE.has(q.field)) return open('deck');
    $('q-count').textContent = `Question ${cov.answered + 1} of ${FIELDS}`; $('q-prog').style.setProperty('--w', (cov.answered / FIELDS * 100) + '%');
    $('q-text').textContent = q.text; $('q-done').classList.toggle('hide', cov.answered < 6);
    $('q-opts').innerHTML = q.options.map(o => `<button data-v="${esc(o.code)}">${esc(o.label)}</button>`).join('');
    const send = body => async () => { try { await api('/api/halia/answers', 'POST', { question_id: q.id, ...body }); questions(); } catch (e) { $('e-q').textContent = e.message; } };
    $('q-opts').querySelectorAll('button').forEach(b => b.onclick = send({ value: b.dataset.v }));
    $('q-skip').onclick = send({ skip: true });
  }
  const COUPLE = new Set(['FAMILY_PLAN', 'MARRIAGE_TIMELINE', 'AMBITION', 'LIVING', 'FAMILY_SETUP', 'TRADITION', 'DIET', 'MONEY_STYLE', 'RISK', 'SOCIAL', 'SCHEDULE', 'CARE_PREF', 'CONFLICT']);
  $('q-done').onclick = () => open('deck'); $('more-q-go').onclick = questions;

  // ── tabs ──
  function open(t) { clearInterval(poll); chat = null;
    if (t === 'me') { setup(true); return view('setup'); }
    view('app'); ['deck', 'list', 'chat'].forEach(x => $('t-' + x).classList.toggle('hide', x !== t));
    document.querySelectorAll('.tabs button').forEach(b => b.setAttribute('aria-selected', b.dataset.t === (t === 'chat' ? 'list' : t)));
    if (t === 'deck') loadDeck(); if (t === 'list') loadList(); }
  $('prof-back').onclick = () => open('deck');
  document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => open(b.dataset.t));

  // ── deck ──
  async function loadDeck() { $('e-deck').textContent = '';
    try { const d = await api('/api/match/deck'); cards = d.cards; left(d.left);
      if (d.answers) { $('more-q').classList.toggle('hide', d.answers.answered >= d.answers.of); $('aq').textContent = `${d.answers.answered} of ${d.answers.of}`; }
      draw(d.hidden); loadCount(); }
    catch (e) { if (e.status === 409 || e.status === 403) { setup(false); view('setup'); } else $('e-deck').textContent = e.message; } }
  const left = l => $('left').textContent = `${l.likes} yeses and ${l.strong} strong yeses left today`;
  function face(c, back) {
    const bars = c.enough ? c.areas.map(a => `<div class="bar"><span>${esc(a.name)}</span><i style="--w:${a.score}%"></i><b>${a.score}</b></div>`).join('') : '';
    return `<article class="pc${back ? ' back' : ''}" data-id="${c.id}"><span class="stamp y">YES</span><span class="stamp n">PASS</span><span class="stamp s">STRONG YES</span>
      <div class="top"><div class="sc">${c.enough ? `<b>${c.score}</b><span>out of 100: how closely your answers agree</span>` : `<b style="font-size:54px;line-height:1">New</b><span>Not enough answers in common yet to give a number</span>`}</div><div class="medal" aria-hidden="true">${esc(c.name[0].toUpperCase())}</div></div>
      <h2>${esc(c.name)}, ${c.age}</h2><p class="meta">${esc(c.city)} · ${esc(c.intent)}</p>${c.keen ? '<span class="keen">Gave you a strong yes</span>' : ''}
      ${c.bio ? `<p class="bio">${esc(c.bio)}</p>` : ''}<div class="bars">${bars}</div></article>`; }
  function draw(hidden) { const D = $('deck'); $('acts').classList.toggle('hide', !cards.length);
    if (!cards.length) return D.innerHTML = `<div class="empty"><div><h2>${hidden ? 'Your profile is hidden.' : 'You have seen everyone for now.'}</h2><p class="lead" style="margin:12px auto 0">${hidden ? 'Turn it back on under Profile to see people again.' : 'New people join every day. Come back soon.'}</p></div></div>`;
    D.innerHTML = (cards[1] ? face(cards[1], true) : '') + face(cards[0]); drag(D.lastElementChild); }
  function drag(el) { let x0, y0, dx = 0, dy = 0, on = false;
    const set = () => { el.style.transform = `translate(${dx}px,${dy}px) rotate(${dx / 18}deg)`;
      el.querySelector('.y').style.opacity = Math.max(0, dx / 90); el.querySelector('.n').style.opacity = Math.max(0, -dx / 90); el.querySelector('.s').style.opacity = Math.abs(dx) < 70 ? Math.max(0, -dy / 110) : 0; };
    el.onpointerdown = e => { if (busy) return; on = true; x0 = e.clientX; y0 = e.clientY; el.setPointerCapture(e.pointerId); el.classList.remove('home'); };
    el.onpointermove = e => { if (!on) return; dx = e.clientX - x0; dy = e.clientY - y0; set(); };
    el.onpointerup = el.onpointercancel = () => { if (!on) return; on = false;
      const a = dx > 90 ? 'like' : dx < -90 ? 'pass' : dy < -110 && Math.abs(dx) < 90 ? 'super' : null;
      if (a) return act(a); dx = dy = 0; el.classList.add('home'); set(); }; }
  async function act(a) { const c = cards[0], el = $('deck').lastElementChild; if (!c || busy || !el.classList.contains('pc')) return; busy = true; $('e-deck').textContent = '';
    let r; try { r = await api('/api/match/swipe', 'POST', { target_id: c.id, action: a }); }
    catch (e) { busy = false; el.classList.add('home'); el.style.transform = ''; el.querySelectorAll('.stamp').forEach(s => s.style.opacity = 0); return $('e-deck').textContent = e.message; }
    el.querySelector(a === 'like' ? '.y' : a === 'pass' ? '.n' : '.s').style.opacity = 1; el.classList.add('go');
    el.style.transform = a === 'like' ? 'translate(120vw,-40px) rotate(24deg)' : a === 'pass' ? 'translate(-120vw,-40px) rotate(-24deg)' : 'translate(0,-120vh)';
    left(r.left); setTimeout(() => { cards.shift(); busy = false; draw(); if (!cards.length) loadDeck(); if (r.matched) won(r); }, still ? 0 : 300); }
  $('acts').querySelectorAll('button').forEach(b => b.onclick = () => act(b.dataset.a));
  addEventListener('keydown', e => { if ($('t-deck').classList.contains('hide') || $('v-app').classList.contains('hide') || /INPUT|TEXTAREA/.test(document.activeElement.tagName)) return;
    const a = { ArrowRight: 'like', ArrowLeft: 'pass', ArrowUp: 'super' }[e.key]; if (a) { e.preventDefault(); act(a); } });
  function won(r) { $('won-t').textContent = `You and ${r.name} both said yes. You can now see where your answers differ and send a message.`;
    const W = $('won'); W.querySelectorAll('i').forEach(i => i.remove());
    if (!still) for (let k = 0; k < 44; k++) { const i = document.createElement('i'), a = Math.random() * 6.283, d = 120 + Math.random() * 300; i.style.setProperty('--x', Math.cos(a) * d + 'px'); i.style.setProperty('--y', Math.sin(a) * d + 'px'); i.style.animationDelay = Math.random() * .25 + 's'; W.appendChild(i); }
    W.classList.remove('hide'); $('won-hi').focus(); $('won-hi').onclick = () => { W.classList.add('hide'); openChat(r.match_id); }; $('won-on').onclick = () => { W.classList.add('hide'); loadCount(); }; }

  // ── matches and messages ──
  async function loadCount() { try { const r = await api('/api/match/matches'); $('m-n').textContent = r.matches.length ? `(${r.matches.length})` : ''; return r; } catch { return { matches: [] }; } }
  async function loadList() { const r = await loadCount();
    $('list').innerHTML = r.matches.map(m => `<button class="mrow" data-m="${m.match_id}"><span class="medal" aria-hidden="true">${esc(m.name[0].toUpperCase())}</span><span><b>${esc(m.name)}, ${m.age}</b><span>${m.last ? (m.last.mine ? 'You: ' : '') + esc(m.last.body) : 'Say hello to ' + esc(m.name)}</span></span>${m.score != null ? `<em>${m.score}</em>` : ''}</button>`).join('')
      || '<div class="empty" style="height:40svh;margin-top:14px"><div><h2>No matches yet.</h2><p class="lead" style="margin:12px auto 0">When someone you said yes to says yes back, they appear here.</p></div></div>';
    $('list').querySelectorAll('[data-m]').forEach(b => b.onclick = () => openChat(+b.dataset.m)); }
  const bubble = m => `<p class="${m.mine ? 'me' : ''}">${esc(m.body)}</p>`;
  async function openChat(id) { open('chat'); chat = id; lastId = 0; $('msgs').innerHTML = ''; $('e-msg').textContent = ''; $('f-rep').classList.add('hide');
    try { const r = await api('/api/match/matches/' + id), p = r.person; chat = { id, person: p.id };
      $('ch-name').textContent = `${p.name}, ${p.age}`; $('ch-meta').textContent = `${p.city} · ${p.intent}${p.enough ? ` · your answers agree ${p.score} out of 100` : ''}`;
      $('ch-talk').classList.toggle('hide', !r.talk_about.length);
      $('ch-talk').innerHTML = '<p><b>Worth talking about</b></p>' + r.talk_about.map(t => `<p>${esc(t.question)}<br>You: ${esc(t.a)} · ${esc(p.name)}: ${esc(t.b)}</p>`).join('');
      add(r.messages); poll = setInterval(async () => { try { add((await api(`/api/match/matches/${id}?after=${lastId}`)).messages); } catch (e) { if (e.status === 404) open('list'); } }, 5000);
    } catch (e) { open('list'); } }
  function add(ms) { if (!ms.length) return; lastId = ms[ms.length - 1].id; $('msgs').insertAdjacentHTML('beforeend', ms.map(bubble).join('')); $('msgs').lastElementChild.scrollIntoView({ block: 'nearest' }); }
  $('f-msg').onsubmit = async ev => { ev.preventDefault(); const t = $('msg').value.trim(); if (!t || !chat) return; $('e-msg').textContent = '';
    try { const m = await api(`/api/match/matches/${chat.id}/messages`, 'POST', { body: t }); $('msg').value = ''; if (m.id > lastId) add([m]); } catch (e) { $('e-msg').textContent = e.message; } };
  $('back').onclick = () => open('list');
  $('unmatch').onclick = async () => { if ($('unmatch').dataset.sure) { await api('/api/match/matches/' + chat.id, 'DELETE').catch(() => {}); delete $('unmatch').dataset.sure; $('unmatch').textContent = 'Unmatch'; open('list'); } else { $('unmatch').dataset.sure = 1; $('unmatch').textContent = 'Tap again to unmatch'; } };
  $('rep').onclick = () => { $('f-rep').classList.remove('hide'); $('rep-why').focus(); };
  $('f-rep').onsubmit = async ev => { ev.preventDefault(); try { await api('/api/match/report', 'POST', { target_id: chat.person, reason: $('rep-why').value }); $('rep-why').value = ''; open('list'); } catch (e) { $('e-msg').textContent = e.message; } };

  (async () => { try { st = await api('/api/match/profile'); if (!st.profile) { setup(false); view('setup'); } else open('deck'); } catch (e) { if (e.status !== 401) $('boot').textContent = e.message; } })();
})();
