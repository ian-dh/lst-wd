# Les Schwab Winter Weather Monitor

A deliberately small GitHub Pages dashboard that broadly screens Les Schwab operating markets for winter-weather signals, then points users to nearby corridors and official DOT/511 sources.

**Seeded markets:** 104 market/city entries derived from the winter activation tracker created for this project.

## What it does

- Screens every market in `data/markets.json`
- Uses the National Weather Service API for hourly forecasts and active alerts
- Sorts markets into **ACTIVATE → PREPARE → WATCH → CLEAR**
- Shows what changed since the prior automated run
- Links to NWS, state DOT/511 and Les Schwab store pages
- Auto-refreshes the browser view every 5 minutes, while GitHub Actions refreshes source weather data four times daily
- Requires no API keys and no JavaScript framework

## Status logic

- **ACTIVATE**: Blizzard Warning, Ice Storm Warning, Winter Storm Warning or Snow Squall Warning
- **PREPARE**: Winter Weather Advisory / freezing-rain advisory, or meaningful winter precipitation within ~24 hours
- **WATCH**: Winter Storm/Blizzard Watch, or a meaningful winter-precipitation signal within 72 hours
- **CLEAR**: no meaningful winter-weather signal

This is decision support, not an automated external communications trigger. Confirm DOT/511 conditions before outreach.

## Deploy

1. Create a **public GitHub repository**.
2. Upload everything in this folder to the repo root.
3. In **Settings → Pages**, set **Source** to **GitHub Actions**.
4. Open **Actions → Refresh weather and deploy Pages → Run workflow** once.
5. After the workflow completes, the Pages URL will appear in the deployment.

The scheduled workflow runs at approximately **5:35 AM, 9:35 AM, 1:35 PM and 5:35 PM Pacific Time**.

> GitHub notes that scheduled workflows in public repositories can be disabled after 60 days with no repository activity. If that happens, re-enable the workflow or make a small repo update.

## Files

```text
/
  index.html
  styles.css
  app.js
  data/
    markets.json
    weather.json
  scripts/
    update_weather.py
  .github/
    workflows/
      weather.yml
```

## Editing markets

`data/markets.json` is the source of truth. Each entry includes:

- market/city
- state
- baseline priority
- nearby winter corridors
- media market(s)
- DOT / 511 source(s)
- Les Schwab store/source link(s)

The updater geocodes a market the first time it runs, then reuses the saved latitude/longitude from the prior `weather.json`.

## Important MVP limitation

Road status is **linked, not automatically parsed**. State DOT/511 systems differ significantly. The dashboard screens weather broadly first, then gives the team the correct road-condition links for flagged markets. Automatic DOT parsing can be added state-by-state later without changing the front-end architecture.

## Data sources

- National Weather Service API: `api.weather.gov`
- Open-Meteo geocoding API for first-run city coordinate lookup
- State DOT / 511 links stored in the market master

## Optional Slack alerts

If you want team pings, add a repository secret named `SLACK_WEBHOOK_URL` containing an incoming Slack webhook URL. The updater will send a compact notification only when a market **changes into PREPARE or ACTIVATE**. If the secret is absent, everything still runs normally.

This avoids pinging the team for routine WATCH/CLEAR refreshes.

## Slack notifications

Slack is optional and uses an incoming webhook. The updater already sends a Slack message only when a market changes **into PREPARE or ACTIVATE**, which avoids routine noise.

1. In Slack, create an **Incoming Webhook** for the channel you want to use.
2. In GitHub, open **Settings → Secrets and variables → Actions → New repository secret**.
3. Name the secret exactly `SLACK_WEBHOOK_URL`.
4. Paste the Slack webhook URL as the value and save it.
5. Run **Refresh weather and deploy Pages** manually once to test.

The workflow passes that secret to `scripts/update_weather.py`. If no webhook secret exists, the weather refresh works normally and simply skips Slack.

For email alerts, a separate SMTP or email-service credential would be required. Slack is the simplest no-database option for this MVP.

## Local store references

Each card now calls out the **local Les Schwab market** and the relevant media market. Where the source data has a city/store-specific Les Schwab URL, the button is labeled **Local store**. Otherwise it remains a **Store locator** link. Exact store pages can be enriched over time in `data/markets.json` without changing the app.
