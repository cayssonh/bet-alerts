"""
Live game alerts for Caysson's open bets -> push notifications on your phone.

Polls ESPN's free scoreboard every 45 seconds while games are on and pings
your phone (via the free ntfy app) when:
  - a game you have a bet on kicks off, hits halftime, or goes final
  - a game you're tracking becomes close late (4th quarter, within 8)
  - a scoring play happens in a game you have a bet on (optional)

SETUP (one time, about 5 minutes)
  1. Install Python 3 (python.org) if you don't have it.
  2. In a terminal:   pip install requests
  3. Install the "ntfy" app on your phone (iPhone or Android, free).
     In the app, tap + and subscribe to a topic name only you know,
     e.g.  caysson-bets-7f3k2   (anyone who knows the name can read it).
  4. Put that same topic name in NTFY_TOPIC below.
  5. Edit MY_GAMES below on game day (team abbreviations or school names).
  6. Run it:   python live_alerts.py
     Leave the laptop awake and plugged in (turn off sleep) while games are on.
     Ctrl+C stops it.

Nothing here places bets or logs into any sportsbook. It only reads scores.
"""
import time, requests, datetime as dt, os, json

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "caysson-bets-7f9bf7d1")   # same name you subscribed to in the ntfy app
POLL_SECONDS = 45
SCORING_ALERTS = True                   # set False if it gets too noisy

# Games you have money on. Use NFL abbreviations (NE, CHI, KC...) or a piece
# of the college school name ("Texas", "Tennessee"). Add a note to remind yourself.
MY_GAMES = {
    "nfl": {"NE": "Patriots +3.5 (Kalshi)", "CHI": ""},
    "college-football": {"Texas": "Texas -3.5", "Tennessee": ""},
}
if os.environ.get("MY_GAMES"):          # in GitHub, set this as a secret (JSON)
    MY_GAMES = json.loads(os.environ["MY_GAMES"])

FEEDS = {
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "college-football": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=300",
}

def push(title, msg, priority="default"):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"),
                      headers={"Title": title, "Priority": priority, "Tags": "football"}, timeout=10)
    except Exception as e:
        print("push failed:", e)
    print(f"[{dt.datetime.now():%H:%M:%S}] {title} | {msg}")

def matches(event, watch):
    comp = event["competitions"][0]
    names = []
    for c in comp["competitors"]:
        t = c["team"]
        names += [t.get("abbreviation", ""), t.get("displayName", ""), t.get("shortDisplayName", ""), t.get("location", "")]
    for key, note in watch.items():
        if any(key.lower() == n.lower() or (len(key) > 3 and key.lower() in n.lower()) for n in names):
            return note or key
    return None

def line_for(event):
    comp = event["competitions"][0]
    away = next(c for c in comp["competitors"] if c["homeAway"] == "away")
    home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
    a, h = away["team"]["abbreviation"], home["team"]["abbreviation"]
    return f"{a} {away.get('score','0')} - {h} {home.get('score','0')}", int(away.get("score") or 0), int(home.get("score") or 0)

STATE_FILE = os.environ.get("STATE_FILE", "state.json")
try:
    seen = json.load(open(STATE_FILE))   # carries over between cloud runs so alerts don't repeat
except Exception:
    seen = {}  # event id -> dict of what we already alerted
upcoming_soon = False

def check(league):
    data = requests.get(FEEDS[league], timeout=15).json()
    global upcoming_soon
    live_any = False
    for ev in data.get("events", []):
        note = matches(ev, MY_GAMES.get(league, {}))
        if not note:
            continue
        st = ev["status"]["type"]
        state, detail = st["state"], st.get("shortDetail", "")
        period = ev["status"].get("period", 0)
        score, a_pts, h_pts = line_for(ev)
        s = seen.setdefault(ev["id"], {"state": None, "half": False, "close": False, "score": None})
        if state == "in":
            live_any = True
        if state == "pre":
            start = dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            if start - dt.datetime.now(dt.timezone.utc) < dt.timedelta(hours=6):
                upcoming_soon = True
        if state != s["state"]:
            if state == "in" and s["state"] is not None:
                push("Kickoff", f"{ev['shortName']} is on. Your bet: {note}")
            if state == "post":
                push("FINAL", f"{score} ({detail}). Your bet: {note}", "high")
            s["state"] = state
        if state == "in" and "Half" in detail and not s["half"]:
            push("Halftime", f"{score}. Your bet: {note}")
            s["half"] = True
        if state == "in" and period >= 4 and abs(a_pts - h_pts) <= 8 and not s["close"]:
            push("Close late", f"{score}, {detail}. Your bet: {note}", "high")
            s["close"] = True
        if SCORING_ALERTS and state == "in" and s["score"] not in (None, score):
            push("Score", f"{score}, {detail}")
        s["score"] = score
    return live_any

if __name__ == "__main__":
    if "CHANGE-ME" in NTFY_TOPIC:
        raise SystemExit("Set NTFY_TOPIC first (see the setup notes at the top).")
    cloud = bool(os.environ.get("GITHUB_ACTIONS"))
    deadline = time.time() + 5.75 * 3600   # GitHub caps a run at 6 hours
    if not cloud:
        push("Live alerts on", "Watching: " + ", ".join(k for g in MY_GAMES.values() for k in g))
    while True:
        live = False
        upcoming_soon = False
        for lg in FEEDS:
            try:
                live = check(lg) or live
            except Exception as e:
                print(lg, "error:", e)
        json.dump(seen, open(STATE_FILE, "w"))
        if cloud and (time.time() > deadline or not (live or upcoming_soon)):
            print("Nothing live or starting soon, exiting.")
            break
        time.sleep(POLL_SECONDS if live else 300)  # slow down when nothing is live
