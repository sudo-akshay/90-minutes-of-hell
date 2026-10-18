# 90 Minutes of Hell

Dashboard for the *90 Minutes of Hell* Fantasy Premier League mini-league (league 1661423): the table, the race for first, week-by-week scores and previous seasons.

**Live:** https://sudo-akshay.github.io/90-minutes-of-hell/

## Refreshing the data

The site refreshes itself **every Tuesday at 12:00 IST** (06:30 UTC) via the `Refresh data` workflow.

To refresh it by hand at any time:

1. Open the **Actions** tab → **Refresh data** → **Run workflow**.
2. The workflow pulls fresh data from the FPL API, rebuilds `index.html` and commits it. The site updates a minute or two later.

Or from a terminal: `gh workflow run refresh.yml -R sudo-akshay/90-minutes-of-hell`.

Note: GitHub pauses scheduled workflows in repositories with no activity for 60 days. It emails first, and re-enabling is one click in the Actions tab.

## Running locally

```sh
python3 fetch.py     # writes data.json
python3 predict.py   # adds next-3-gameweek projections to data.json
python3 build.py     # writes index.html
open index.html
```

No dependencies beyond Python 3. Edit `template.html` to change the page; `build.py` embeds `data.json` into it.

## Projections

`predict.py` projects each manager's next three gameweeks from their current squad, assuming no transfers or chips. Each player's expected points combine their points per 90 this season (weighted with last season's rate), average minutes over their last three matches, FPL's injury and suspension percentages, and fixture difficulty. Each manager's projection is their best valid XI with the top player captained.

To check the model against gameweeks already played:

```sh
python3 predict.py --backtest --random=260   # your league plus ~200 random managers
```

Tested after GW4 of 2026/27 on 206 random managers, three-week projections missed by 32 pts on average (against 59 for "GW1 score × 3") and ranked managers with a correlation of 0.60.
