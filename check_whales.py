"""
Whale sighting alerts — polls the Acartia data cooperative for new whale
sightings within a configured radius and sends an SMS via Twilio.

Designed to run on a schedule (e.g., GitHub Actions every 15 min).
State is kept in seen_ids.json so we don't re-alert on the same sighting.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from twilio.rest import Client

# ---------- CONFIG (via environment variables / GitHub Secrets) ----------

# Your home location (defaults to downtown Seattle if unset)
HOME_LAT = float(os.environ.get("HOME_LAT") or "47.65017449949859")
HOME_LON = float(os.environ.get("HOME_LON") or "-122.33102146225346")

# How far you'll drive. ~20 min in Seattle traffic = roughly 12 miles as
# the crow flies. Tune to taste.
RADIUS_MILES = float(os.environ.get("RADIUS_MILES") or "500")

# Only alert on sightings that are this fresh. Sightings older than this
# are skipped (they're stale by the time we'd drive there).
MAX_AGE_MINUTES = int(os.environ.get("MAX_AGE_MINUTES", "90"))

# Acartia credentials — register at acartia.io to get an access token
ACARTIA_TOKEN = os.environ["ACARTIA_TOKEN"]

# Twilio credentials
TWILIO_SID = os.environ["TWILIO_SID"]
TWILIO_AUTH = os.environ["TWILIO_AUTH"]
TWILIO_FROM = os.environ["TWILIO_FROM"]   # your Twilio number
TWILIO_TO = os.environ["TWILIO_TO"]       # your phone number

# Which species trigger alerts. Acartia uses common names like "Orca",
# "Gray Whale", "Humpback Whale", "Minke Whale". Match is case-insensitive
# substring, so "whale" would match all of them.
SPECIES_KEYWORDS = [
    s.strip().lower()
    for s in os.environ.get(
        "SPECIES",
        "orca,killer whale,gray whale,humpback,minke",
    ).split(",")
]

STATE_FILE = Path(__file__).parent / "seen_ids.json"

# ---------- HELPERS ----------


def haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points, in miles."""
    R = 3958.8  # Earth radius in miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def species_matches(name):
    if not name:
        return False
    n = name.lower()
    return any(kw in n for kw in SPECIES_KEYWORDS)


def parse_timestamp(ts):
    """Acartia timestamps are ISO 8601. Be forgiving about format."""
    if not ts:
        return None
    try:
        # Handle trailing Z
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def load_seen():
    if not STATE_FILE.exists():
        return set()
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        # Prune entries older than 7 days to keep file small
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        return {sid for sid, seen_at in data.items() if seen_at > cutoff}
    except (json.JSONDecodeError, OSError):
        return set()


def save_seen(seen_ids):
    now = datetime.now(timezone.utc).isoformat()
    data = {sid: now for sid in seen_ids}
    # Merge with existing timestamps so we keep accurate "first seen" times
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                existing = json.load(f)
            for sid, ts in existing.items():
                if sid in seen_ids and sid not in data:
                    data[sid] = ts
                elif sid in seen_ids:
                    data[sid] = existing.get(sid, now)
        except (json.JSONDecodeError, OSError):
            pass
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def fetch_sightings():
    """Get current sightings from Acartia."""
    url = "https://acartia.io/api/v1/sightings/current"
    headers = {"Authorization": f"Bearer {ACARTIA_TOKEN}"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def send_sms(client, body):
    msg = client.messages.create(body=body, from_=TWILIO_FROM, to=TWILIO_TO)
    print(f"  -> SMS sent: {msg.sid}")


def format_alert(sighting, distance):
    species = sighting.get("type") or sighting.get("species") or "Whale"
    count = sighting.get("no_sighted") or sighting.get("count") or "?"
    where = (
        sighting.get("location") or sighting.get("name") or "unspecified location"
    )
    lat = sighting.get("latitude")
    lon = sighting.get("longitude")
    when = sighting.get("created") or sighting.get("timestamp") or ""

    # Trim timestamp to HH:MM if we can
    parsed = parse_timestamp(when)
    if parsed:
        when_str = parsed.astimezone().strftime("%-I:%M %p")
    else:
        when_str = when

    maps_url = f"https://maps.google.com/?q={lat},{lon}" if lat and lon else ""

    return (
        f"🐋 {species} ({count}) ~{distance:.1f} mi away at {where}"
        f" ({when_str}). {maps_url}"
    ).strip()


# ---------- MAIN ----------


def main():
    print(f"Checking sightings within {RADIUS_MILES} mi of "
          f"({HOME_LAT}, {HOME_LON})...")

    seen = load_seen()
    print(f"  {len(seen)} sightings already alerted recently")

    try:
        sightings = fetch_sightings()
    except requests.HTTPError as e:
        print(f"Acartia API error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  Acartia returned {len(sightings)} current sightings")

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=MAX_AGE_MINUTES)
    twilio = Client(TWILIO_SID, TWILIO_AUTH)
    new_alerts = []
    new_seen = set(seen)

    for s in sightings:
        sid = s.get("ssemmi_id") or s.get("id")
        if not sid or sid in seen:
            continue

        species = s.get("type") or s.get("species") or ""
        if not species_matches(species):
            continue

        try:
            lat = float(s.get("latitude"))
            lon = float(s.get("longitude"))
        except (TypeError, ValueError):
            continue

        dist = haversine_miles(HOME_LAT, HOME_LON, lat, lon)
        if dist > RADIUS_MILES:
            continue

        ts = parse_timestamp(s.get("created") or s.get("timestamp"))
        if ts and ts < cutoff:
            # Too old to bother
            new_seen.add(sid)  # mark so we don't re-check
            continue

        msg = format_alert(s, dist)
        print(f"  ALERT: {msg}")
        try:
            send_sms(twilio, msg)
            new_alerts.append(sid)
            new_seen.add(sid)
        except Exception as e:
            print(f"  SMS failed: {e}", file=sys.stderr)

    # Always update state so we remember everything we've evaluated
    for s in sightings:
        sid = s.get("ssemmi_id") or s.get("id")
        if sid:
            new_seen.add(sid)

    save_seen(new_seen)
    print(f"Done. {len(new_alerts)} alerts sent.")


if __name__ == "__main__":
    main()
