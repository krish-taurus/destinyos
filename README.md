# destinyos

Static pages for destinyos.in that live alongside the Destiny OS app.

| Path | URL | What it is |
| --- | --- | --- |
| `business/index.html` | https://destinyos.in/business | Brand naming and business numerology services, pricing and terms |

## Before going live

Replace `91XXXXXXXXXX` in `business/index.html` with the DestinyOS WhatsApp number (country code, no `+` or spaces).

## One-time server setup (DigitalOcean droplet, nginx)

```bash
# on the droplet
sudo git clone https://github.com/krish-taurus/destinyos /var/www/destinyos
```

Add this inside the `server { ... }` block for destinyos.in, **above** any catch-all `location /` that serves the app:

```nginx
location = /business { return 301 /business/; }
location /business/ {
    alias /var/www/destinyos/business/;
    index index.html;
}
```

Then reload: `sudo nginx -t && sudo systemctl reload nginx`

## Updating

Every change is a commit to `main`. On the droplet run:

```bash
sudo /var/www/destinyos/deploy.sh
```
