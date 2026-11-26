# destinyos

Everything served at https://destinyos.in.

```
site/                 web root (nginx serves /var/www/destinyos/frontend)
  index.html          homepage: the temple story, live chart reveal, how it works, HALIA, pricing, FAQ
  app/                customer panel: sign in, free report, Destiny Plus, add-ons, account
  business/           brand naming and business numerology services
  temple/             redirects to the homepage
  halia/              HALIA: chat, daily question, QR to WhatsApp, compare with a partner or co-founder
  free-report/        the link you share: /free-report/?src=instagram (source is saved on sign-up)
  config.js           DESTINY_SIGNUP_OPEN switch (false = "Free report" buttons open WhatsApp)
server/backend/       FastAPI (destinyos-api.service, 127.0.0.1:8100)
  main.py             report, guidance engines, access rules
  auth.py             phone OTP (MSG91) and sessions
  billing.py          Razorpay subscription, add-ons, webhook
  reports.py          one free report per number; open vs locked sections
  daily_whatsapp.py   7:00 IST WhatsApp guidance + manifestation practice
  halia_engine.py     HALIA: question bank, next-question rules, alignment engine (pure functions)
  halia.py            HALIA API: consent, answers, chat, QR, compare links, job fit, WhatsApp webhook
  halia_daily.py      19:00 IST WhatsApp question to people who opted in
  tests/              every customer scenario; deploy refuses to ship if one fails
deploy/               deploy.sh, rollback.sh, systemd timer
```

## The customer journey
1. Link → register with phone OTP, birth details, DPDP consent, WhatsApp opt-in.
2. One free core report per phone number (12 sections; 5 open, 7 locked with a teaser).
   Locked text never leaves the server for free users. Deleting and re-registering doesn't give a second free report.
3. 3 free Ask Destiny questions, then the paywall.
4. Destiny Plus ₹599/month (Razorpay, UPI AutoPay or card): full report, Ask (30/day fair use), daily brief with
   manifestation practice, Life Compass, Food Lens, 7 am WhatsApp. Cancel keeps access to the end of the paid month;
   a failed renewal keeps access for 3 days while Razorpay retries.
5. Add-ons: consultation ₹2,999 (opens WhatsApp to schedule), compatibility ₹999, annual forecast ₹1,999.

## Deploy (on the droplet, as root)
```
bash /opt/destinyos-src/deploy/deploy.sh          # first time: see below
bash /opt/destinyos-src/deploy/rollback.sh        # undo the last deploy
```
First time: `git clone` needs the deploy key, so run
`GIT_SSH_COMMAND="ssh -i /root/.ssh/destinyos_deploy -o StrictHostKeyChecking=accept-new" git clone git@github.com:krish-taurus/destinyos.git /opt/destinyos-src`
then the deploy script.

## Going live with sign-ups
1. MSG91 keys in /etc/destinyos.env → `systemctl restart destinyos-api`
2. Razorpay keys, plan and webhook (https://destinyos.in/api/billing/webhook) → restart
3. Set `window.DESTINY_SIGNUP_OPEN = true` in site/config.js and deploy
4. WhatsApp: approved template `destiny_daily` + keys → the 7 am job starts sending (test: `systemctl start destinyos-daily`)

## HALIA
HALIA works only from what a person declares. It makes no predictions and uses no birth, numerology or astrology
input; an alignment score says how closely two sets of answers match and is shown only when both sides have
answered enough. Adding a domain (couple, co-founder, candidate-to-job, ...) is a config entry in `halia_engine.DOMAINS`.

- Consent is separate from sign-up (adults only). Withdrawing it deletes answers, chats, invites and links.
- Chat: 3 free chats in total, then HALIA Chat ₹499/month for 25 a day (Plus and Voice include it). Same allowance in the app and on WhatsApp.
- `/api/halia/chat/qr` is a QR code that opens the WhatsApp chat (`WA_NUMBER`), or the web chat until that is set.
- One WhatsApp question a day for people who opted in; replies by number are saved to their profile. STOP pauses it.

To switch on: create the ₹499 plan in Razorpay (`RAZORPAY_PLAN_ID_CHAT`); in Meta set the webhook to
`https://destinyos.in/api/whatsapp/webhook` (`WA_VERIFY_TOKEN`, `WA_APP_SECRET`, `WA_NUMBER`) and get the
`halia_question` template approved (wording in `halia_daily.py`). See `server/backend/.env.example`.
