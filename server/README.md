# Destiny OS — Beta

Public beta: real Vedic charts (Swiss Ephemeris, Lahiri), Pythagorean + Chaldean numerology,
AI daily brief, Ask Destiny chat, Food Lens and Life Compass. No payments or accounts yet —
each user's profile lives in their own browser.

```
frontend/   static site → Vercel   (index.html, app.js, base.css, extra.css, config.js)
backend/    FastAPI     → Render   (main.py, astro.py)
render.yaml Render blueprint
```

## 1. Deploy the API on Render (~10 min)
1. Push this folder to a private GitHub repo.
2. Render → New → Blueprint → pick the repo. It reads `render.yaml`
   (Singapore region, Starter plan — the free plan sleeps and the first request takes ~50 s).
3. Set environment variables:
   - `ANTHROPIC_API_KEY` — from console.anthropic.com (set a monthly spend limit there)
   - `ALLOWED_ORIGINS` — `https://destinyos.ai,https://www.destinyos.ai` plus your `*.vercel.app` URL
4. Check `https://<your-service>.onrender.com/api/health` returns `{"ok":true}`.

Railway instead: New Project → Deploy from repo → root `backend`, start command
`uvicorn main:app --host 0.0.0.0 --port $PORT`, same env vars.

## 2. Deploy the site on Vercel (~5 min)
1. Edit `frontend/config.js` → set `window.DESTINY_API` to your Render URL.
2. Vercel → Add New Project → same repo → Root Directory `frontend`, Framework "Other", no build command.
3. Settings → Domains → add your domain; point DNS as Vercel shows
   (A `76.76.21.21` for the apex, CNAME `cname.vercel-dns.com` for `www`).
4. Add the final domain to `ALLOWED_ORIGINS` on Render and redeploy.

## 3. Run locally
```bash
cd backend && pip install -r requirements.txt
ANTHROPIC_API_KEY=sk-ant-... ALLOWED_ORIGINS=http://localhost:3000 uvicorn main:app --port 8000
# new terminal — set config.js to http://localhost:8000
cd frontend && python3 -m http.server 3000
```

## Costs and limits
- Per-IP hourly limits in `main.py` (`LIMITS`): chart 30, brief 20, chat 40, food 15, compass 6.
  In-memory — fine for one instance; move to Redis before scaling out.
- Daily brief is cached per profile per day. Chat uses the fast model; brief, food and compass use Sonnet.
- Watch spend in the Anthropic console for the first week; tighten `LIMITS` if needed.

## Known beta gaps (next build)
- No login: profile is per browser; clearing storage erases it.
- No wearables yet (Body card shows a "coming soon" state, never fake numbers).
- WhatsApp delivery, Razorpay plans (Awake / Clarity / Vision / Luminary) and server-side storage come in the launch build.
- Before storing any data server-side: DPDP consent records, deletion endpoint, India-region database.
- Nominatim geocoding (OpenStreetMap) is rate-limited to ~1 request/s; common cities are built in.
  Swap to Google Geocoding if signups spike.
