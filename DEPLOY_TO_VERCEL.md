# AVA — Vercel deployment

This package is prepared for Vercel's Python/Flask runtime.

## Deploy

1. Extract this folder.
2. Open PowerShell in the extracted folder.
3. Run:

```powershell
npx vercel login
npx vercel --prod
```

When prompted, accept the default project settings. Vercel will print the public `https://...vercel.app` URL.

## Important

- Vercel runs Flask as a serverless function; it is not the same as running `py main.py` locally.
- Runtime state is stored under `/tmp` on Vercel and is therefore not durable across function instances. This is suitable for the current demo, not long-term production persistence.
- Heavy AVA operations are executed directly on Vercel rather than relying on the local in-process worker pool, because serverless instances are not durable background workers.
- The Vercel function is configured for up to 60 seconds. If a specific heavy demo action exceeds the platform's plan/runtime limit, use the lighter dashboard interactions or move the heavy job processing to a durable worker later.
