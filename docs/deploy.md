# Deploying the public demo

The demo runs as one Docker container on **Render's free plan**. FastAPI
serves both the API and the static Next.js export. It needs no credentials:
routing uses the offline rail network and the catalogue is baked into the
image.

## One-time setup (about 5 minutes)

1. Sign in at [render.com](https://render.com) with GitHub. The free plan
   needs no card.
2. **New → Blueprint**, pick `wenhaoyay/along-sg`, branch `main`. Render reads
   `render.yaml` and proposes one web service, `along-sg`.
3. Apply. The first build takes several minutes: it installs the frontend,
   builds the export, installs the pinned Python packages and builds the
   catalogue.
4. When `/health` answers, the demo is at `https://along-sg.onrender.com`. If
   that name is taken, Render adds a suffix; use the URL it shows.
5. If the URL differs, set the build variable `NEXT_PUBLIC_SITE_URL` to it (so
   link previews point at the right place), then update the README's demo
   link.

Every push to `main` redeploys automatically.

## What to expect on the free plan

- **Waking up.** The service sleeps after 15 idle minutes and takes about a
  minute to wake. The page asks `/health` as soon as it loads, to start that
  early. If an example is clicked before the server answers, the saved run of
  that example appears after 2.5 seconds, labelled as saved. The live answer
  replaces it when it arrives. Refresh the saved runs after a change to
  scoring or data:

  ```powershell
  cd backend
  .venv\Scripts\python.exe tools\export_examples.py --departure 2026-10-26T10:00:00+08:00
  ```

  Shop times come from `config.py` unless a local `.env` overrides them, so
  check that your `.env` sets no `DWELL_*` values before exporting.

- **Region.** `render.yaml` asks for Singapore. If the free plan is not offered
  there, pick the nearest region; only latency changes.

- **Rate limits.** These are per client: 10 plans in a burst, then 12 a
  minute. They read the client address from Render's proxy
  (`FORWARDED_ALLOW_IPS`). On the first deploy, check from two networks that
  one visitor's limit does not throttle the other.

- **Times are estimates.** The app bar says "Sample times" whenever the
  offline router is in use.

## Live routing (optional, not needed for the demo)

Live routing needs a free OneMap account. Set `ONEMAP_MOCK=false`,
`ONEMAP_EMAIL` and `ONEMAP_PASSWORD` as secret variables in Render. OneMap
tokens last three days; the backend refreshes them itself. Bus arrivals
additionally need `LTA_ACCOUNT_KEY` with `DATAMALL_MOCK=false`.
