# StudBud web

Next.js 16 App Router frontend for StudBud. See the root [README](../README.md) for setup,
API configuration, and deployment.

```bash
cp .env.example .env.local
npm install
npm run dev        # http://localhost:3000
npm run lint
npm run build
```

`NEXT_PUBLIC_API_BASE_URL` must point at the FastAPI service. The app uses cookie-based
authentication, CSRF double-submit headers, and a client-side light/dark theme toggle
stored in `localStorage`.
