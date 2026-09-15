"""Download the league's standings and every manager's gameweek history into data.json."""
import json, pathlib, time, urllib.request, urllib.parse

LEAGUE_ID = 1661423
BASE = "https://fantasy.premierleague.com/api"
OUT = pathlib.Path(__file__).parent / "data.json"


def get(path, **params):
    url = f"{BASE}/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            time.sleep(0.2)
            return data
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)


boot = get("bootstrap-static/")
players = {e["id"]: e["web_name"] for e in boot["elements"]}
events = [
    {"event": e["id"], "average": e["average_entry_score"], "highest": e["highest_score"],
     "finished": e["finished"], "current": e["is_current"]}
    for e in boot["events"] if e["finished"] or e["is_current"]
]

league, managers, page = None, [], 1
while True:
    d = get(f"leagues-classic/{LEAGUE_ID}/standings/", page_standings=page)
    league = d["league"]
    managers += d["standings"]["results"]
    if not d["standings"]["has_next"]:
        break
    page += 1

out = []
for m in managers:
    h = get(f"entry/{m['entry']}/history/")
    gws = []
    for gw in h["current"]:
        picks = get(f"entry/{m['entry']}/event/{gw['event']}/picks/")
        cap = next((p for p in picks["picks"] if p["is_captain"]), None)
        gws.append({
            "event": gw["event"], "points": gw["points"], "total": gw["total_points"],
            "overall_rank": gw["overall_rank"], "value": gw["value"] / 10, "bank": gw["bank"] / 10,
            "transfers": gw["event_transfers"], "hits": gw["event_transfers_cost"],
            "bench": gw["points_on_bench"], "chip": picks.get("active_chip"),
            "captain": players.get(cap["element"]) if cap else None,
            "captain_mult": cap["multiplier"] if cap else None,
        })
    out.append({
        "entry": m["entry"], "name": m["player_name"], "team": m["entry_name"],
        "rank": m["rank"], "last_rank": m["last_rank"], "total": m["total"],
        "gws": gws, "past": h["past"], "chips": h["chips"],
    })

data = {"league": {"id": league["id"], "name": league["name"], "admin_entry": league["admin_entry"]},
        "events": events, "managers": out,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}
OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False))
print(f"{league['name']}: {len(out)} managers, up to GW{events[-1]['event'] if events else 0}")
