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

live_event = next((e["event"] for e in events if not e["finished"]), None)

nxt = next((e for e in boot["events"] if e["is_next"]), None)
next_event = {"event": nxt["id"], "deadline": nxt["deadline_time"]} if nxt else None

league, managers, page = None, [], 1
while True:
    d = get(f"leagues-classic/{LEAGUE_ID}/standings/", page_standings=page)
    league = d["league"]
    managers += d["standings"]["results"]
    if not d["standings"]["has_next"]:
        break
    page += 1

live = {}

def points_of(event, pid):
    v = live_points(event).get(pid, 0)
    return v[0] if isinstance(v, (tuple, list)) else v


def live_points(event):
    if event not in live:
        live[event] = {e["id"]: (e["stats"]["total_points"], e["stats"]["minutes"])
                       for e in get(f"event/{event}/live/")["elements"]}
    return live[event]

out = []
for m in managers:
    h = get(f"entry/{m['entry']}/history/")
    gws, picks_by_event = [], {}
    for gw in h["current"]:
        picks = get(f"entry/{m['entry']}/event/{gw['event']}/picks/")
        picks_by_event[gw["event"]] = picks
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
            "captain_id": cap["element"] if cap else None,
            "pos": by_pos,
            "xi": [p["element"] for p in picks["picks"] if p["multiplier"] > 0],
            "cmult": 3 if picks.get("active_chip") == "3xc" else 2,
            "cap": pick_info(eff),
            "best": pick_info(best),
        })
    # Every transfer, with what the player coming in has scored against the player
    # going out since the swap. Free Hit moves are marked: they only last a week.
    played = [g["event"] for g in gws]
    transfers_log = []
    for t in get(f"entry/{m['entry']}/transfers/"):
        if t["event"] not in played:
            continue
        rest = [e for e in played if e >= t["event"]]
        pts_in = sum(points_of(e, t["element_in"]) for e in rest)
        pts_out = sum(points_of(e, t["element_out"]) for e in rest)
        transfers_log.append({
            "event": t["event"],
            "in": {"id": t["element_in"], "name": players.get(t["element_in"]), "cost": t["element_in_cost"] / 10},
            "out": {"id": t["element_out"], "name": players.get(t["element_out"]), "cost": t["element_out_cost"] / 10},
            "pts_in": pts_in, "pts_out": pts_out, "delta": pts_in - pts_out,
            "chip": picks_by_event.get(t["event"], {}).get("active_chip"),
            "weeks": len(rest),
        })
    transfers_log.sort(key=lambda t: t["event"])

    # While a gameweek is being played the league standings update before the manager's
    # history row does, so take the live score from the total instead of the lagging row.
    if live_event and gws and gws[-1]["event"] == live_event:
        prev_total = gws[-2]["total"] if len(gws) > 1 else 0
        gws[-1]["total"] = m["total"]
        gws[-1]["points"] = m["total"] - prev_total + gws[-1]["hits"]
        gws[-1]["live"] = True

    # The squad they carry into the next gameweek (a Free Hit squad reverts).
    squad = []
    if picks_by_event:
        latest_event = max(picks_by_event)
        latest = picks_by_event[latest_event]
        if latest.get("active_chip") == "freehit" and latest_event - 1 in picks_by_event:
            latest = picks_by_event[latest_event - 1]
        squad = [{"id": p["element"], "xi": p["position"] <= 11} for p in latest["picks"]]
    out.append({
        "entry": m["entry"], "name": m["player_name"], "team": m["entry_name"], "squad": squad,
        "rank": m["rank"], "last_rank": m["last_rank"], "total": m["total"],
        "gws": gws, "past": h["past"], "chips": h["chips"], "transfers_log": transfers_log,
    })

# Injury and availability news for every player in the league's current squads, newest first.
teams = {t["id"]: t["short_name"] for t in boot["teams"]}
elements = {e["id"]: e for e in boot["elements"]}
owners = {}
for m in out:
    for p in m["squad"]:
        owners.setdefault(p["id"], []).append({"entry": m["entry"], "xi": p["xi"]})
news = []
for pid, own in owners.items():
    e = elements[pid]
    if not e["news"] and e["status"] == "a":
        continue
    news.append({"name": e["web_name"], "team": teams[e["team"]], "pos": ["GK", "DEF", "MID", "FWD"][e["element_type"] - 1],
                 "status": e["status"], "chance": e["chance_of_playing_next_round"], "news": e["news"],
                 "added": e["news_added"], "owners": own})
news.sort(key=lambda n: n["added"] or "", reverse=True)

# Details for every player someone in the league owns, for the ownership table.
players = {
    str(pid): {"name": elements[pid]["web_name"], "team": teams[elements[pid]["team"]],
               "pos": ["GK", "DEF", "MID", "FWD"][elements[pid]["element_type"] - 1],
               "price": elements[pid]["now_cost"] / 10, "selected": float(elements[pid]["selected_by_percent"]),
               "points": elements[pid]["total_points"]}
    for pid in owners
}

# This gameweek's matches and the players who scored best in them.
gw_news = None
if events:
    cur = events[-1]["event"]
    teams_full = {t["id"]: {"short": t["short_name"], "name": t["name"]} for t in boot["teams"]}
    fixtures = [
        {"home": teams_full[f["team_h"]], "away": teams_full[f["team_a"]],
         "hs": f["team_h_score"], "as": f["team_a_score"], "kickoff": f["kickoff_time"],
         "started": bool(f["started"]), "finished": bool(f["finished"]), "minutes": f["minutes"]}
        for f in get("fixtures/", event=cur)
    ]
    fixtures.sort(key=lambda f: f["kickoff"] or "")
    performers = []
    for e in get(f"event/{cur}/live/")["elements"]:
        st = e["stats"]
        if st["minutes"] == 0:
            continue
        el = elements[e["id"]]
        performers.append({
            "name": el["web_name"], "team": teams_full[el["team"]]["short"],
            "pos": ["GK", "DEF", "MID", "FWD"][el["element_type"] - 1],
            "points": st["total_points"], "goals": st["goals_scored"], "assists": st["assists"],
            "clean": st["clean_sheets"], "bonus": st["bonus"], "minutes": st["minutes"],
            "owners": [o["entry"] for o in owners.get(e["id"], [])],
        })
    performers.sort(key=lambda p: (-p["points"], -p["bonus"], p["name"]))
    gw_news = {"event": cur, "fixtures": fixtures, "performers": performers[:15],
               "average": events[-1]["average"], "highest": events[-1]["highest"],
               "finished": events[-1]["finished"]}

data = {"league": {"id": league["id"], "name": league["name"], "admin_entry": league["admin_entry"]},
        "events": events, "phases": phases, "managers": out, "news": news, "players": players, "gw_news": gw_news, "next_event": next_event,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}
OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False))
print(f"{league['name']}: {len(out)} managers, up to GW{events[-1]['event'] if events else 0}")
