# destinyos

Everything served at https://destinyos.in.

```
site/                 web root (nginx serves /var/www/destinyos/frontend)
  index.html          homepage
  app/                customer panel: sign in, free report, Destiny Plus, add-ons, account
  business/           brand naming and business numerology services
  free-report/        the link you share: /free-report/?src=instagram (source is saved on sign-up)
  config.js           DESTINY_SIGNUP_OPEN switch (false = "Free report" buttons open WhatsApp)
server/backend/       FastAPI (destinyos-api.service, 127.0.0.1:8100)
  main.py             report, guidance engines, access rules
  auth.py             phone OTP (MSG91) and sessions
  billing.py          Razorpay subscription, add-ons, webhook
  reports.py          one free report per number; open vs locked sections
  daily_whatsapp.py   7:00 IST WhatsApp guidance + manifestation practice
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
