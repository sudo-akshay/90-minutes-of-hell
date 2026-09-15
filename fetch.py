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
positions = {e["id"]: e["element_type"] for e in boot["elements"]}  # 1 GK, 2 DEF, 3 MID, 4 FWD
phases = [{"name": p["name"], "start": p["start_event"], "stop": p["stop_event"]}
          for p in boot["phases"] if p["name"] != "Overall"]
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

live = {}

def live_points(event):
    if event not in live:
        live[event] = {e["id"]: (e["stats"]["total_points"], e["stats"]["minutes"])
                       for e in get(f"event/{event}/live/")["elements"]}
    return live[event]

out = []
for m in managers:
    h = get(f"entry/{m['entry']}/history/")
    gws = []
    for gw in h["current"]:
        picks = get(f"entry/{m['entry']}/event/{gw['event']}/picks/")
        cap = next((p for p in picks["picks"] if p["is_captain"]), None)
        # Multipliers already reflect auto-subs, captaincy and Bench Boost, so this sums to the GW score.
        pts = live_points(gw["event"])
        by_pos = [0, 0, 0, 0]
        for p in picks["picks"]:
            by_pos[positions[p["element"]] - 1] += pts.get(p["element"], (0, 0))[0] * p["multiplier"]
        # Captain regret: the captain who actually scored the bonus against the best pick in the final XI.
        vice = next((p for p in picks["picks"] if p["is_vice_captain"]), None)
        eff = cap
        if cap and pts.get(cap["element"], (0, 0))[1] == 0 and vice and pts.get(vice["element"], (0, 0))[1] > 0:
            eff = vice
        xi = [p for p in picks["picks"] if p["multiplier"] > 0]
        best = max(xi, key=lambda p: pts.get(p["element"], (0, 0))[0]) if xi else None
        pick_info = lambda p: {"name": players.get(p["element"]), "pts": pts.get(p["element"], (0, 0))[0]} if p else None
        gws.append({
            "event": gw["event"], "points": gw["points"], "total": gw["total_points"],
            "overall_rank": gw["overall_rank"], "value": gw["value"] / 10, "bank": gw["bank"] / 10,
            "transfers": gw["event_transfers"], "hits": gw["event_transfers_cost"],
            "bench": gw["points_on_bench"], "chip": picks.get("active_chip"),
            "captain": players.get(cap["element"]) if cap else None,
            "captain_mult": cap["multiplier"] if cap else None,
            "pos": by_pos,
            "cmult": 3 if picks.get("active_chip") == "3xc" else 2,
            "cap": pick_info(eff),
            "best": pick_info(best),
        })
    out.append({
        "entry": m["entry"], "name": m["player_name"], "team": m["entry_name"],
        "rank": m["rank"], "last_rank": m["last_rank"], "total": m["total"],
        "gws": gws, "past": h["past"], "chips": h["chips"],
    })

data = {"league": {"id": league["id"], "name": league["name"], "admin_entry": league["admin_entry"]},
        "events": events, "phases": phases, "managers": out,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}
OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False))
print(f"{league['name']}: {len(out)} managers, up to GW{events[-1]['event'] if events else 0}")
