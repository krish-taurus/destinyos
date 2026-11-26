// The free readings on the report page: numerology and the Vedic chart, calculated step by step on screen.
// Every figure shown comes from the same rules as the server; the final numbers are checked against the server's.
(() => {
  const $ = id => document.getElementById(id), D = () => window.DOS, esc = s => D().esc(s);
  const AZ = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', PY = Object.fromEntries([...AZ].map((c, i) => [c, i % 9 + 1]));
  const CH = { A: 1, B: 2, C: 3, D: 4, E: 5, F: 8, G: 3, H: 5, I: 1, J: 1, K: 2, L: 3, M: 4, N: 5, O: 7, P: 8, Q: 1, R: 2, S: 3, T: 4, U: 6, V: 6, W: 6, X: 5, Y: 1, Z: 7 };
  const MEAN = { 1: 'Initiation', 2: 'Cooperation', 3: 'Expression', 4: 'Foundation', 5: 'Change', 6: 'Harmony', 7: 'Introspection', 8: 'Achievement', 9: 'Completion', 11: 'Illumination', 22: 'Master building', 33: 'Master teaching' };
  const SIGNS = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo', 'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces'];
  const ORD = [['Ketu', 7], ['Venus', 20], ['Sun', 6], ['Moon', 10], ['Mars', 7], ['Rahu', 18], ['Jupiter', 16], ['Saturn', 19], ['Mercury', 17]];
  let run = 0;                                                            // bumping this cancels an animation in progress
  const sleep = (ms, id) => new Promise((res, rej) => setTimeout(() => id === run ? res() : rej(new Error('stopped')), D().still ? 0 : ms));
  const log = html => { const li = document.createElement('li'); li.innerHTML = html; $('calc-log').appendChild(li); };
  const chain = (n, keep) => { const s = [n]; while (n > 9 && !(keep && [11, 22, 33].includes(n))) { n = String(n).split('').reduce((a, b) => a + +b, 0); s.push(n); } return s; };
  const last = (n, keep) => chain(n, keep).pop(), show = (n, keep) => chain(n, keep).join(' → ');
  const dms = x => `${Math.floor(x)}°${String(Math.floor((x % 1) * 60)).padStart(2, '0')}′`;
  const dt = s => new Date(s + 'T00:00:00Z').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });

  function open(title, sub) { run++; $('calc').classList.remove('hide'); $('calc-h').textContent = title; $('calc-sub').textContent = sub;
    $('calc-stage').innerHTML = ''; $('calc-log').innerHTML = ''; $('calc-out').innerHTML = ''; $('calc').scrollIntoView({ behavior: D().still ? 'auto' : 'smooth', block: 'start' }); return run; }

  // ── numerology ──
  async function numerology() {
    const me = D().me(), id = open('Your numerology.', 'Chaldean values in gold, Pythagorean in grey, under each letter of your name.');
    $('calc-again').onclick = numerology;
    const name = me.name.toUpperCase(), srv = me.numerology;
    $('calc-stage').innerHTML = `<div class="letters">${[...name].map(c => PY[c] ? `<div class="lt"><b>${c}</b><i>${CH[c]}</i><u>${PY[c]}</u></div>` : '<div class="lt sp"></div>').join('')}</div>
      <div class="sum"><div><span>Chaldean total</span><b id="s-ch">0</b></div><div><span>Pythagorean total</span><b id="s-py">0</b></div></div>`;
    try {
      await sleep(500, id); let a = 0, b = 0;
      for (const t of $('calc-stage').querySelectorAll('.lt:not(.sp)')) { t.classList.add('on'); a += +t.children[1].textContent; b += +t.children[2].textContent; $('s-ch').textContent = a; $('s-py').textContent = b; await sleep(170, id); }
      const L = [...name].filter(c => PY[c]), V = L.filter(c => 'AEIOU'.includes(c)), C = L.filter(c => !'AEIOU'.includes(c)), sum = (arr, T) => arr.reduce((x, c) => x + T[c], 0);
      $('s-ch').textContent = show(a, true); $('s-py').textContent = show(b, true);
      log(`Name total, Chaldean: <b>${show(a, true)}</b>. The compound number ${a} is kept in Chaldean reading.`); await sleep(650, id);
      log(`Name total, Pythagorean: <b>${show(b, true)}</b>`); await sleep(650, id);
      log(`Vowels only (${esc(V.join(' ')) || 'none'}): Chaldean <b>${show(sum(V, CH), true)}</b>, Pythagorean <b>${show(sum(V, PY), true)}</b>`); await sleep(650, id);
      log(`Consonants only: Chaldean <b>${show(sum(C, CH), true)}</b>, Pythagorean <b>${show(sum(C, PY), true)}</b>`); await sleep(650, id);
      const [y, m, d] = me.dob.split('-').map(Number), yr = new Date().getFullYear();
      log(`Born ${d}-${m}-${y}: day <b>${show(d, true)}</b>, month <b>${show(m, true)}</b>, year <b>${show(y, true)}</b>`); await sleep(650, id);
      const lp = last(d, true) + last(m, true) + last(y, true);
      log(`Life Path: ${last(d, true)} + ${last(m, true)} + ${last(y, true)} = <b>${show(lp, true)}</b>`); await sleep(650, id);
      log(`Personal Year ${yr}: ${last(d)} + ${last(m)} + ${last(yr)} = <b>${show(last(d) + last(m) + last(yr))}</b>`); await sleep(500, id);
      const c = srv.chaldean, p = srv.pythagorean, tile = (n, t, extra, big) => `<div class="${big ? 'big' : ''}"><b>${esc(n)}</b><span>${t}</span><small>${esc(MEAN[n] || '')}${extra ? ' · ' + extra : ''}</small></div>`;
      $('calc-out').innerHTML = `<h3 class="res-h">Chaldean</h3><div class="res">${tile(c.expression, 'Name number', 'compound ' + c.expressionCompound, 1)}${tile(c.soulUrge, 'Soul urge')}${tile(c.personality, 'Personality')}</div>
        <h3 class="res-h">Pythagorean</h3><div class="res">${tile(p.lifePath, 'Life Path', '', 1)}${tile(p.expression, 'Expression', 'compound ' + p.expressionCompound)}${tile(p.soulUrge, 'Soul urge')}${tile(p.personality, 'Personality')}${tile(p.birthNumber, 'Birth number')}${tile(p.personalYear, 'Personal year ' + yr)}</div>
        <p class="cap" style="margin-top:16px;max-width:44em">${c.expression === p.expression ? 'Both systems give your name the same number, which tradition reads as a strong signature.' : `The two systems give your name different numbers (${c.expression} and ${p.expression}). Chaldean weighs the sound of the name; Pythagorean follows the alphabet in order.`} What a number means is a matter of tradition, offered for reflection. <a class="gold" href="/methods/#chaldean">How the two systems differ</a></p>`;
    } catch { /* another reading was opened */ }
  }

  // ── Vedic chart ──
  const P = (r, deg) => { const a = (180 - deg) * Math.PI / 180; return [200 + r * Math.cos(a), 200 - r * Math.sin(a)]; };   // 0° Aries at the left, anticlockwise
  const arc = (r, a, b) => { const [x1, y1] = P(r, a), [x2, y2] = P(r, b); return `M${x1.toFixed(1)} ${y1.toFixed(1)}A${r} ${r} 0 ${b - a > 180 ? 1 : 0} 0 ${x2.toFixed(1)} ${y2.toFixed(1)}`; };
  async function chart() {
    const me = D().me(), id = open('Your Vedic chart.', `The sky over ${me.city} on ${dt(me.dob)}${me.birth_time ? ' at ' + me.birth_time : ''}.`);
    $('calc-again').onclick = chart;
    let c; try { c = await D().api('/api/chart'); } catch (e) { $('calc-out').innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
    if (id !== run) return;
    const order = ['Sun', 'Moon', 'Mars', 'Mercury', 'Jupiter', 'Venus', 'Saturn', 'Rahu', 'Ketu'], col = { Sun: '#F6D99A', Moon: '#F3E9D6', Mars: '#E0694E', Mercury: '#8FD08A', Jupiter: '#E7B45A', Venus: '#F0C6D8', Saturn: '#9FB4D8', Rahu: '#A39680', Ketu: '#A39680' };
    let svg = `<svg viewBox="0 0 400 400" role="img" aria-label="Your birth chart wheel"><circle cx="200" cy="200" r="186" fill="none" stroke="#3A2E20" stroke-width="1.5"/><circle cx="200" cy="200" r="152" fill="none" stroke="#3A2E20" stroke-width="1.5"/><circle cx="200" cy="200" r="60" fill="none" stroke="#2A2117"/>`;
    for (let i = 0; i < 12; i++) { const [x1, y1] = P(152, i * 30), [x2, y2] = P(186, i * 30), [tx, ty] = P(169, i * 30 + 15);
      svg += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#3A2E20" stroke-width="1.5"/><text class="sg" x="${tx}" y="${ty}">${SIGNS[i].slice(0, 3)}</text>`; }
    svg += `<path id="k-nak" class="arc" d="" fill="none" stroke="#E7B45A" stroke-width="7" stroke-linecap="butt" opacity="0"/><line id="k-asc" x1="200" y1="200" x2="200" y2="200" stroke="#C8442B" stroke-width="2" opacity="0"/><text id="k-asc-t" class="pl" opacity="0" style="fill:#F0A794"></text>`;
    // planets that sit close together are stepped inwards so their labels do not collide
    const placed = [];
    for (const k of order) { const lon = c.natal[k].longitude; let r = 134; while (placed.some(q => Math.abs(((q.lon - lon + 540) % 360) - 180) < 13 && q.r === r)) r -= 19; placed.push({ k, lon, r });
      const [x, y] = P(r, lon); svg += `<g class="dot" data-k="${k}" opacity="0" style="transform:translate(${200 - x}px,${200 - y}px)"><circle cx="${x}" cy="${y}" r="5.5" fill="${col[k]}"/><text class="pl" x="${x}" y="${y - 11}">${k.slice(0, 2)}</text></g>`; }
    $('calc-stage').innerHTML = `<div class="sky">${svg}</svg><div><div class="facts" id="k-facts"></div></div></div>`;
    const fact = (l, v) => $('k-facts').insertAdjacentHTML('beforeend', `<div><span>${l}</span><b>${esc(v)}</b></div>`);
    try {
      await sleep(400, id);
      if (c.place) log(`Place: ${esc(c.place.city)} at <b>${Math.abs(c.place.lat).toFixed(2)}°${c.place.lat >= 0 ? 'N' : 'S'}, ${Math.abs(c.place.lon).toFixed(2)}°${c.place.lon >= 0 ? 'E' : 'W'}</b>, time zone ${esc(c.place.tz)}`);
      await sleep(700, id); log('Planet positions from the Swiss Ephemeris, shifted to the sidereal zodiac (Lahiri)'); await sleep(700, id);
      for (const k of order) { const n = c.natal[k], g = $('calc-stage').querySelector(`[data-k=${k}]`); g.setAttribute('opacity', 1); g.style.transform = 'none';
        log(`${k}: <b>${dms(n.degree)} ${esc(n.sign)}</b>${n.retrograde ? ' (retrograde)' : ''}${n.house ? ', house ' + n.house : ''}`); await sleep(430, id); }
      const moon = c.natal.Moon, span = 360 / 27, ni = Math.floor(moon.longitude / span), nk = $('k-nak');
      nk.setAttribute('d', arc(143, ni * span, (ni + 1) * span)); nk.setAttribute('opacity', .9);
      log(`Moon at ${moon.longitude.toFixed(2)}° falls in nakshatra ${ni + 1} of 27: <b>${esc(moon.nakshatra)}</b>`); fact('Moon sign (Rashi)', moon.sign); fact('Birth nakshatra', moon.nakshatra); await sleep(800, id);
      const t = c.tithi; log(`Tithi: the Moon is ${t.angle.toFixed(1)}° ahead of the Sun. ${t.angle.toFixed(1)} ÷ 12 gives lunar day ${t.number}: <b>${esc(t.label)}</b>`);
      fact('Tithi', t.label); fact('Moon lit', Math.round(t.lit * 100) + '%'); await sleep(800, id);
      if (c.lagna) { const [x, y] = P(186, c.lagna.longitude), [tx, ty] = P(197, c.lagna.longitude), L = $('k-asc'); L.setAttribute('x2', x); L.setAttribute('y2', y); L.setAttribute('opacity', 1);
        const T = $('k-asc-t'); T.setAttribute('x', tx); T.setAttribute('y', ty); T.textContent = 'Asc'; T.setAttribute('opacity', 1);
        log(`Rising on the eastern horizon at your birth time: <b>${dms(c.lagna.degree)} ${esc(c.lagna.sign)}</b>. This is your Lagna.`); fact('Lagna (rising sign)', c.lagna.sign); }
      else { log('No birth time given, so the rising sign is left out and not guessed.'); fact('Lagna (rising sign)', 'Needs birth time'); }
      fact('Sun sign (sidereal)', c.natal.Sun.sign); await sleep(800, id);
      const d = c.dasha, lord = ORD.find(o => o[0] === d.mahadasha.lord), start = ORD.indexOf(lord);
      log(`${esc(moon.nakshatra)} is ruled by ${ORD[ni % 9][0]}, so your Dasha sequence began in its period. Today you are in <b>${esc(d.mahadasha.lord)}</b>, ${dt(d.mahadasha.start)} to ${dt(d.mahadasha.end)}`);
      await sleep(700, id);
      $('calc-out').innerHTML = `<h3 class="res-h">Your ${esc(d.mahadasha.lord)} Mahadasha, ${lord[1]} years</h3><div class="dstrip">${ORD.map((_, k) => { const o = ORD[(start + k) % 9]; return `<i style="flex:${o[1]}" class="${d.antardasha && o[0] === d.antardasha.lord ? 'now' : ''}">${o[0]}</i>`; }).join('')}</div>
        <p class="cap" style="margin-top:8px">${d.antardasha ? `The outlined block is your sub-period now: ${esc(d.mahadasha.lord)}–${esc(d.antardasha.lord)}, ${dt(d.antardasha.start)} to ${dt(d.antardasha.end)}. ` : ''}Next comes ${esc(d.next_mahadasha.lord)}, from ${dt(d.next_mahadasha.start)}.</p>
        ${(c.notes || []).map(n => `<p class="note">${esc(n)}</p>`).join('')}
        <p class="cap" style="margin-top:14px;max-width:44em">These positions are exact astronomy. What they mean is a matter of tradition, offered for reflection and not as a prediction. <a class="gold" href="/methods/">How each part is worked out</a></p>`;
    } catch { /* another reading was opened */ }
  }

  function wire() { if (!window.DOS) return setTimeout(wire, 60);
    document.querySelectorAll('[data-calc]').forEach(b => b.onclick = () => ({ num: numerology, chart, halia: () => { run++; $('calc').classList.add('hide'); D().halia(); } })[b.dataset.calc]()); }
  wire();
})();
