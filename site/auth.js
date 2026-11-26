// Sign in and sign up share one flow: phone, code, then birth details only when the number is new.
(() => {
  const API = window.DESTINY_API || '';
  const $ = id => document.getElementById(id);
  const mode = document.body.dataset.mode;
  const next = () => { const n = new URLSearchParams(location.search).get('next'); return n && /^\/[a-z0-9\-\/#?=&]*$/i.test(n) && !n.startsWith('//') ? n : '/report/'; };
  const src = (new URLSearchParams(location.search).get('src') || '').slice(0, 40);
  let phone = '', token = '', timer = 0;

  async function api(path, body) {
    let res;
    try { res = await fetch(API + path, { method: body ? 'POST' : 'GET', credentials: 'include', headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined }); }
    catch { throw new Error('No connection. Check your internet and try again.'); }
    const data = await res.json().catch(() => null);
    if (!res.ok) { const d = data && data.detail; throw Object.assign(new Error(typeof d === 'string' ? d : 'Something went wrong. Please try again.'), { status: res.status }); }
    return data;
  }
  function show(stage) {
    ['phone', 'code', 'details'].forEach((s, i) => { $('s-' + s).classList.toggle('hide', s !== stage); });
    const n = ['phone', 'code', 'details'].indexOf(stage);
    [...$('lamps').children].forEach((d, i) => d.classList.toggle('lit', i <= n));
    $('lamps').setAttribute('aria-label', `Step ${n + 1} of 3`);
    const first = $('s-' + stage).querySelector('input'); if (first) first.focus({ preventScroll: true });
    scrollTo(0, 0);
  }
  async function busy(btn, label, fn) {
    const was = btn.textContent; btn.disabled = true; btn.textContent = label;
    try { await fn(); } finally { btn.disabled = false; btn.textContent = was; }
  }
  function countdown() {
    let s = 30; clearInterval(timer); $('resend').disabled = true; $('resend').textContent = `Send a new code in ${s}s`;
    timer = setInterval(() => { s--; if (s <= 0) { clearInterval(timer); $('resend').disabled = false; $('resend').textContent = 'Send a new code'; } else $('resend').textContent = `Send a new code in ${s}s`; }, 1000);
  }
  async function sendCode() {
    const raw = $('phone').value.replace(/[^\d+]/g, '');
    const full = raw.startsWith('+') ? raw : raw.length === 10 ? '+91' + raw : raw.length === 12 && raw.startsWith('91') ? '+' + raw : '';
    if (!full) throw new Error('Enter your 10-digit mobile number.');
    const r = await api('/api/auth/otp', { phone: full });
    phone = r.phone; $('sent-to').textContent = phone.replace(/^(\+\d{2})(\d{5})(\d+)$/, '$1 $2 $3');
    $('dev-note').classList.toggle('hide', !r.dev_mode); $('dev-wa').href = window.DESTINY_WHATSAPP || 'https://wa.me/917975554666';
    $('code').value = ''; $('e-code').textContent = ''; show('code'); countdown();
  }

  $('f-phone').onsubmit = ev => { ev.preventDefault(); $('e-phone').textContent = '';
    busy($('b-phone'), 'Sending…', sendCode).catch(e => $('e-phone').textContent = e.message); };
  $('resend').onclick = () => sendCode().catch(e => $('e-code').textContent = e.message);
  $('change').onclick = () => show('phone');
  $('code').oninput = () => { $('code').value = $('code').value.replace(/\D/g, ''); if ($('code').value.length === 6) $('f-code').requestSubmit(); };

  $('f-code').onsubmit = ev => { ev.preventDefault(); $('e-code').textContent = '';
    if (!/^\d{6}$/.test($('code').value)) return $('e-code').textContent = 'Enter the 6 digits from the text message.';
    busy($('b-code'), 'Checking…', async () => {
      const r = await api('/api/auth/verify', { phone, code: $('code').value });
      if (!r.needs_registration) return location.replace(next());
      token = r.signup_token;
      if (mode === 'in') $('details-lead').textContent = 'This number is new here. Add your birth details and your free report is written straight away.';
      show('details');
    }).catch(e => $('e-code').textContent = e.message); };

  $('f-details').onsubmit = ev => { ev.preventDefault(); const E = $('e-details'); E.textContent = '';
    const name = $('name').value.trim(), dob = $('dob').value, city = $('city').value.trim();
    if (name.length < 2) return E.textContent = 'Enter your full name as given at birth.';
    if (!dob) return E.textContent = 'Choose your date of birth.';
    if (city.length < 2) return E.textContent = 'Enter the city you were born in.';
    if (!$('consent').checked) return E.textContent = 'Tick the consent box to continue.';
    busy($('b-details'), 'Creating your account…', async () => {
      await api('/api/auth/register', { signup_token: token, name, dob, birth_time: $('time').value || null, city, consent: true,
        whatsapp_optin: $('wa').checked, source: src || 'website', language: document.querySelector('input[name=lang]:checked').value });
      try { sessionStorage.removeItem('dos_pre'); } catch {}
      location.replace(next());
    }).catch(e => { E.textContent = e.message; if (e.status === 400) { show('phone'); $('e-phone').textContent = 'That took a little long. Request a new code to finish.'; } });
  };

  // details typed for the chart preview on the homepage carry over
  try { const p = JSON.parse(sessionStorage.getItem('dos_pre') || 'null'); if (p) { $('name').value = p.name || ''; $('dob').value = p.dob || ''; $('time').value = p.time || ''; $('city').value = p.city || ''; } } catch {}
  $('dob').max = new Date().toISOString().slice(0, 10);
  api('/api/auth/consent-text').then(r => { if (r && r.text) $('consent-text').textContent = r.text; }).catch(() => {});
  api('/api/me').then(() => location.replace(next())).catch(() => {});   // already signed in
})();
