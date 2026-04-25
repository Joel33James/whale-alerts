# Whale Alerts

Sends you an SMS when a whale is reported within driving distance of your
location, using sightings data from the [Acartia](https://acartia.io)
cooperative (which aggregates Orca Network and other Salish Sea sources).

Runs entirely free on GitHub Actions. Only cost is Twilio SMS (~$0.008
per text; trial credit covers a lot).

## Setup (one-time, ~20 minutes)

### 1. Get an Acartia API token

1. Go to https://acartia.io/register and create an account.
2. Once logged in, find the dashboard and generate an API access token.
3. Copy it — you'll paste it in step 4.

### 2. Get a Twilio account

1. Sign up at https://twilio.com (free trial includes credit).
2. Get a Twilio phone number (free with trial).
3. Verify your real phone number as a "verified caller ID" — required
   on the trial plan to receive texts.
4. From the Twilio Console, copy:
   - Account SID
   - Auth Token
   - Your Twilio phone number (the `+1...` one)

### 3. Fork or upload this repo to GitHub

Push these files to a new GitHub repo (can be private).

### 4. Configure secrets and variables

In the repo: **Settings → Secrets and variables → Actions**

Add these as **secrets** (sensitive):

| Name | Value |
| --- | --- |
| `ACARTIA_TOKEN` | Your Acartia API token |
| `TWILIO_SID` | Twilio Account SID |
| `TWILIO_AUTH` | Twilio Auth Token |
| `TWILIO_FROM` | Your Twilio number, e.g. `+12065551234` |
| `TWILIO_TO` | Your phone, e.g. `+12065559999` |

Add these as **variables** (not sensitive):

| Name | Value | Default |
| --- | --- | --- |
| `HOME_LAT` | Your latitude | 47.6062 (Seattle) |
| `HOME_LON` | Your longitude | -122.3321 |
| `RADIUS_MILES` | Alert radius in miles | 15 |
| `SPECIES` | Comma-separated keywords | `orca,killer whale,gray whale,humpback,minke` |

To find your lat/lon: right-click your home on Google Maps and click
the coordinates that appear at the top.

### 5. Enable Actions and test

1. Go to the **Actions** tab in your repo. Enable workflows if prompted.
2. Click **Check for whales** in the sidebar.
3. Click **Run workflow** to fire it manually.
4. Watch the run log. If something is misconfigured, the error will be
   obvious.
5. If a whale happens to be near you and the run sends an SMS, you'll
   know it works. Otherwise, temporarily set `RADIUS_MILES` to something
   huge like `500` to force a test alert.

After confirming it works, set `RADIUS_MILES` back to your real value.
The workflow will then run automatically every 15 minutes during
daylight hours.

## Tuning

- **Too many alerts?** Lower `RADIUS_MILES` or narrow `SPECIES`.
- **Too few?** Raise the radius. Remember orcas pass through Puget Sound
  unpredictably; some weeks have nothing.
- **Want quiet hours?** Edit the cron in `.github/workflows/check.yml`.
- **Want push notifications instead of SMS?** Swap the Twilio call in
  `check_whales.py` for Pushover or ntfy.sh — both have simpler APIs and
  ntfy is free.

## How it works

1. Every 15 min, GitHub Actions runs `check_whales.py`.
2. Script fetches current sightings from `acartia.io/api/v1/sightings/current`.
3. Filters to: matching species, within radius, fresher than 90 min,
   not already alerted.
4. Sends SMS via Twilio for each match.
5. Records sighting IDs in `seen_ids.json` so they aren't re-alerted.

## Caveats

- Acartia data depends on volunteer reporting. Sightings can lag 5–30
  minutes from when the whales are actually visible — by the time you
  get the text and drive over, they may have moved on. Still better
  than nothing.
- Some sightings come in without precise coordinates and will be
  skipped silently.
- The first run on a fresh repo will mark everything currently in
  Acartia as "seen" without alerting, so you start clean.
