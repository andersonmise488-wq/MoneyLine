# Deploy MoneyLine to Render.com

## Prerequisites

- GitHub repo with this project (Render deploys from Git)
- [Render](https://render.com) account
- Telegram bot token and chat IDs for alerts

## One-click blueprint

1. Push the latest code to GitHub (`main` branch).
2. In Render Dashboard → **New** → **Blueprint** → connect the repo.
3. Render reads `render.yaml` at the repo root (Docker web service on port 8080).

## Environment variables (set in Render → Service → Environment)

| Variable | Required | Notes |
|----------|----------|-------|
| `TELEGRAM_BOT_TOKEN` | Yes | Bot for alerts + `/subscribe` |
| `TELEGRAM_CHAT_ID` | Yes | Admin alert group(s), comma-separated |
| `TELEGRAM_ADMIN_CHAT_IDS` | Optional | Overrides admin routing |
| `WEB_ADMIN_TOKEN` | Recommended | Protects admin WS `scan` command |
| `WEB_ALLOWED_ORIGINS` | Recommended | e.g. `https://moneyline.onrender.com` |
| `STANBIC_*` | For billing | Client ID, secret, bill account, callback URL |

Scan tuning is pre-set in `render.yaml` (full 72h window, no stale cache).

## After deploy

- Public dashboard: `https://<your-service>.onrender.com/`
- Admin: `https://<your-service>.onrender.com/admin`
- Health: `https://<your-service>.onrender.com/health`
- Payment callback: `https://<your-service>.onrender.com/stanbic/callback`

Set `STANBIC_CALLBACK_URL` to that callback URL and `WEB_ALLOWED_ORIGINS` to your Render URL.

## Stanbic go-live (real M-Pesa → your bank account)

Sandbox (`STANBIC_ENV=sandbox`) uses test M-Pesa — money does **not** credit your live account.

For production collections into `STANBIC_BILL_ACCOUNT_REF`:

1. Complete sandbox testing on [sandbox.stanbicbank.co.ke](https://sandbox.stanbicbank.co.ke).
2. Email **kilele@stanbic.com** for production API credentials (separate Client Key/Secret).
3. On Render, set:
   - `STANBIC_ENV=production`
   - `STANBIC_CLIENT_ID` / `STANBIC_CLIENT_SECRET` (production)
   - `STANBIC_BILL_ACCOUNT_REF=0100011077913` (your settlement account)
   - `STANBIC_CALLBACK_URL=https://moneyline.onrender.com/stanbic/callback`
   - Clear `STANBIC_TOKEN_URL` and `STANBIC_STK_URL` (auto: `connect.stanbicbank.co.ke/api/production/...`)
   - `SUBSCRIPTION_DEMO_MODE=false`
4. Redeploy.

API shape matches Stanbic Swagger `STKPushRequest`: `dbsReferenceId`, `billAccountRef`, `amount` (e.g. `400.00`), `mobileNumber` (`2547...`).

## BangBet circuit breaker

If a book was paused after an old bug, redeploy clears ephemeral disk **or** wait 15 minutes. On startup the app prunes expired cooldowns automatically.

## Manual deploy trigger

Render Dashboard → your **moneyline** service → **Manual Deploy** → Deploy latest commit.
