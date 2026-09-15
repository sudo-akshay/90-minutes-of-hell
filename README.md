# 90 Minutes of Hell

Dashboard for the *90 Minutes of Hell* Fantasy Premier League mini-league (league 1661423): the table, the race for first, week-by-week scores and previous seasons.

**Live:** https://sudo-akshay.github.io/90-minutes-of-hell/

## Refreshing the data

The page is a snapshot. To update it after a gameweek:

1. Open the **Actions** tab → **Refresh data** → **Run workflow**.
2. The workflow pulls fresh data from the FPL API, rebuilds `index.html` and commits it. The site updates a minute or two later.

## Running locally

```sh
python3 fetch.py   # writes data.json
python3 build.py   # writes index.html
open index.html
```

No dependencies beyond Python 3. Edit `template.html` to change the page; `build.py` embeds `data.json` into it.
