"""Predict each manager's points for the next three gameweeks and add them to data.json.

Run after fetch.py. `python3 predict.py --backtest` instead scores the model on gameweeks
already played, using only the data that was available before each one.
"""
import json, os, pathlib, random, sys, time, urllib.request
from itertools import product
from statistics import mean

BASE = "https://fantasy.premierleague.com/api"
HERE = pathlib.Path(__file__).parent
CACHE = os.environ.get("FPL_CACHE")  # optional folder that caches API responses while developing

HORIZON = 3
PRIOR_MINUTES = 900  # last season's scoring rate counts as this many minutes of this season
DEFAULT_PTS90 = {1: 3.3, 2: 3.3, 3: 3.8, 4: 3.8}  # players with no useful history, by position
FDR_FACTOR = {1: 1.25, 2: 1.12, 3: 1.0, 4: 0.88, 5: 0.76}
HOME, AWAY = 1.04, 0.96
GONE = {"u", "n"}  # left the club or not in the league: no minutes at all
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def get(path):
    cached = pathlib.Path(CACHE) / (path.strip("/").replace("/", "_").replace("?", "_") + ".json") if CACHE else None
    if cached and cached.exists():
        return json.loads(cached.read_text())
    req = urllib.request.Request(f"{BASE}/{path}", headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)
    time.sleep(0.12)
    if cached:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(data))
    return data


class Model:
    def __init__(self, boot, fixtures):
        self.el = {e["id"]: e for e in boot["elements"]}
        self.team_short = {t["id"]: t["short_name"] for t in boot["teams"]}
        self.fx = {}  # (team, event) -> [(is_home, difficulty, opponent)]
        for f in fixtures:
            if f["event"] is None:
                continue
            self.fx.setdefault((f["team_h"], f["event"]), []).append((True, f["team_h_difficulty"], f["team_a"]))
            self.fx.setdefault((f["team_a"], f["event"]), []).append((False, f["team_a_difficulty"], f["team_h"]))
        self.summaries = {}

    def summary(self, pid):
        if pid not in self.summaries:
            self.summaries[pid] = get(f"element-summary/{pid}/")
        return self.summaries[pid]

    def xp(self, pid, event, upto, live=False):
        """Expected points for a player in `event`, using only gameweeks up to `upto`.

        live=True also applies today's injury and suspension news, which only exists for the future.
        """
        e, s = self.el[pid], self.summary(pid)
        rows = [h for h in s["history"] if h["round"] <= upto]
        pts, mins = sum(h["total_points"] for h in rows), sum(h["minutes"] for h in rows)
        past = s["history_past"][-1] if s["history_past"] else None
        prior = past["total_points"] / past["minutes"] * 90 if past and past["minutes"] >= 600 else DEFAULT_PTS90[e["element_type"]]
        pts90 = (pts + prior * PRIOR_MINUTES / 90) / ((mins + PRIOR_MINUTES) / 90)

        recent = [h["minutes"] for h in rows if h["round"] > upto - 3]
        xmins = mean(recent) if recent else 45
        if live:
            chance = e["chance_of_playing_next_round"]
            if e["status"] in GONE:
                xmins = 0
            elif chance is not None and chance < 100:
                # The percentage is for the next gameweek; assume half the gap closes each week after.
                weeks_after = event - (upto + 1)
                xmins *= 1 - (1 - chance / 100) * 0.5 ** weeks_after

        per_fixture = pts90 * xmins / 90
        return sum(per_fixture * FDR_FACTOR[d] * (HOME if home else AWAY) for home, d, _ in self.fx.get((e["team"], event), []))

    def opponents(self, pid, event):
        e = self.el[pid]
        return [f"{self.team_short[opp]} ({'H' if home else 'A'})" for home, _, opp in self.fx.get((e["team"], event), [])]


def best_xi(squad):
    """squad: list of (pid, position, xp). Returns (points with captain, xi, captain)."""
    by = {t: sorted((p for p in squad if p[1] == t), key=lambda p: -p[2]) for t in POS}
    best = None
    for d, m, f in product(range(3, 6), range(2, 6), range(1, 4)):
        if d + m + f != 10 or not by[1] or len(by[2]) < d or len(by[3]) < m or len(by[4]) < f:
            continue
        xi = by[1][:1] + by[2][:d] + by[3][:m] + by[4][:f]
        total = sum(p[2] for p in xi)
        if best is None or total > best[0]:
            best = (total, xi)
    if best is None:
        return 0.0, [], None
    total, xi = best
    captain = max(xi, key=lambda p: p[2])
    return total + captain[2], xi, captain


def squad_at(entry, event):
    """The 15 players a manager will carry forward after `event` (a Free Hit squad reverts)."""
    picks = get(f"entry/{entry}/event/{event}/picks/")
    if picks.get("active_chip") == "freehit" and event > 1:
        picks = get(f"entry/{entry}/event/{event - 1}/picks/")
    return [p["element"] for p in picks["picks"]]


def rank(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def spearman(a, b):
    ra, rb = rank(a), rank(b)
    ma, mb = mean(ra), mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else 0.0


def backtest(model, last, groups):
    print(f"{'group':<12}{'from':>5}{'GW':>4}{'n':>4}  {'model MAE':>9} {'bias':>6} {'rank r':>7}   {'avg-so-far MAE':>14} {'rank r':>7}")
    totals = {}
    for name, entries in groups.items():
        histories = {e: {x["event"]: x["points"] for x in get(f"entry/{e}/history/")["current"]} for e in entries}
        for t in range(1, last):
            for h in range(1, HORIZON + 1):
                g = t + h
                if g > last:
                    break
                pred, base, act = [], [], []
                for e in entries:
                    hist = histories[e]
                    if g not in hist or not all(x in hist for x in range(1, t + 1)):
                        continue
                    squad = squad_at(e, t)
                    xp = [(pid, model.el[pid]["element_type"], model.xp(pid, g, t)) for pid in squad]
                    pred.append(best_xi(xp)[0])
                    base.append(mean(hist[x] for x in range(1, t + 1)))
                    act.append(hist[g])
                if len(act) < 3:
                    continue
                mae = mean(abs(p - a) for p, a in zip(pred, act))
                bmae = mean(abs(p - a) for p, a in zip(base, act))
                bias = mean(p - a for p, a in zip(pred, act))
                r, br = spearman(pred, act), spearman(base, act)
                print(f"{name:<12}{t:>5}{g:>4}{len(act):>4}  {mae:>9.1f} {bias:>+6.1f} {r:>7.2f}   {bmae:>14.1f} {br:>7.2f}")
                agg = totals.setdefault(name, {"n": 0, "mae": 0, "bmae": 0, "r": [], "br": []})
                agg["n"] += len(act); agg["mae"] += mae * len(act); agg["bmae"] += bmae * len(act)
                agg["r"].append(r); agg["br"].append(br)
    print("\n3-gameweek totals (predicted after GW1, actual GW2–4):")
    for name, entries in groups.items():
        if last < 1 + HORIZON:
            break
        pred, base, act = [], [], []
        for e in entries:
            hist = {x["event"]: x["points"] for x in get(f"entry/{e}/history/")["current"]}
            weeks = range(2, 2 + HORIZON)
            if 1 not in hist or not all(g in hist for g in weeks):
                continue
            squad = squad_at(e, 1)
            pred.append(sum(best_xi([(pid, model.el[pid]["element_type"], model.xp(pid, g, 1)) for pid in squad])[0] for g in weeks))
            base.append(hist[1] * HORIZON)
            act.append(sum(hist[g] for g in weeks))
        if len(act) >= 3:
            print(f"  {name:<10} n={len(act):>3}  model MAE {mean(abs(p - a) for p, a in zip(pred, act)):.1f}, rank r {spearman(pred, act):.2f}"
                  f"   | GW1 x3 MAE {mean(abs(p - a) for p, a in zip(base, act)):.1f}, rank r {spearman(base, act):.2f}")
    print()
    for name, a in totals.items():
        print(f"{name:<12} predictions={a['n']:>4}  model MAE {a['mae'] / a['n']:.1f} (rank r {mean(a['r']):.2f})   "
              f"avg-so-far MAE {a['bmae'] / a['n']:.1f} (rank r {mean(a['br']):.2f})")


def forecast(model, data):
    if not data["events"]:
        return None
    # Start from the latest gameweek whose deadline has passed, even if its matches are still going.
    last = data["events"][-1]["event"]
    events = [g for g in range(last + 1, min(38, last + HORIZON) + 1) if any(k[1] == g for k in model.fx)]
    if not events:
        return None
    out = {}
    for m in data["managers"]:
        squad = squad_at(m["entry"], last)
        weeks = []
        for g in events:
            xp = [(pid, model.el[pid]["element_type"], model.xp(pid, g, last, live=True)) for pid in squad]
            total, xi, cap = best_xi(xp)
            top = sorted(xi, key=lambda p: -p[2])[:3]
            weeks.append({
                "event": g,
                "pts": round(total, 1),
                "captain": model.el[cap[0]]["web_name"] if cap else None,
                "captain_xp": round(cap[2] * 2, 1) if cap else 0,
                "captain_vs": ", ".join(model.opponents(cap[0], g)) if cap else "",
                "top": [{"name": model.el[p[0]]["web_name"], "xp": round(p[2], 1)} for p in top],
            })
        flags = []
        for pid in squad:
            e = model.el[pid]
            if e["status"] in GONE or (e["chance_of_playing_next_round"] is not None and e["chance_of_playing_next_round"] < 100):
                flags.append({"name": e["web_name"], "chance": 0 if e["status"] in GONE else e["chance_of_playing_next_round"], "news": e["news"]})
        out[str(m["entry"])] = {"gws": weeks, "total": round(sum(w["pts"] for w in weeks), 1), "flags": flags}
    return {"from_event": last, "events": events, "managers": out,
            "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}


def main():
    boot = get("bootstrap-static/")
    model = Model(boot, get("fixtures/"))
    path = HERE / "data.json"
    data = json.loads(path.read_text())
    if "--backtest" in sys.argv:
        last = max(e["event"] for e in data["events"] if e["finished"])
        groups = {"league": [m["entry"] for m in data["managers"]]}
        for arg in sys.argv:
            if arg.startswith("--random="):
                rng = random.Random(7)
                picked = []
                for entry in rng.sample(range(1, 11_000_000), int(arg.split("=", 1)[1])):
                    try:
                        if any(x["event"] == 1 for x in get(f"entry/{entry}/history/")["current"]):
                            picked.append(entry)
                    except Exception:
                        pass
                groups["random"] = picked
            if arg.startswith("--sample-pages="):
                for page in arg.split("=", 1)[1].split(","):
                    res = get(f"leagues-classic/314/standings/?page_standings={page}")["standings"]["results"]
                    groups[f"rank~{res[0]['rank'] // 1000}k"] = [r["entry"] for r in res]
        backtest(model, last, groups)
        return
    data["predictions"] = forecast(model, data)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    p = data["predictions"]
    if p:
        print(f"Predicted GW{p['events'][0]}–{p['events'][-1]} for {len(p['managers'])} managers")
    else:
        print("No gameweeks left to predict")


if __name__ == "__main__":
    main()
