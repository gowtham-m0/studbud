# Render keepalive Worker

Cloudflare Worker cron that requests Render `/healthz` every 5 minutes.

- Free Workers plan: 288 requests/day.
- Keeps the Render free web service warm, avoiding its 15-minute sleep.
- Render free 750 instance hours covers one always-on service (~720–744 hours/month).

## Deploy

1. Deploy the backend on Render first; copy its URL.
2. Set `HEALTH_URL` in `wrangler.toml`.
3. Login and deploy:

```bash
cd infrastructure/cloudflare/keepalive
npx wrangler login
npx wrangler deploy
```

Alternative without Worker: UptimeRobot or cron-job.org, 5-minute HTTP check against the
same `/healthz` URL.

Do not ping with a request that triggers ingestion. `/healthz` is cheap and checks only the
database.
