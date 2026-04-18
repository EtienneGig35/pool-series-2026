#!/usr/bin/env python3
"""Fetch NHL data and write nhl-data.json for GitHub Pages."""

import json
import urllib.request
from datetime import datetime

API = "https://api-web.nhle.com/v1"
SEASON = "20252026"

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "PoolSeries2026/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))

def nhl_name(obj):
    if isinstance(obj, str): return obj
    if isinstance(obj, dict): return obj.get("default", obj.get("fr", ""))
    return ""

def main():
    # Bracket first — source of truth for the 16 playoff teams.
    bracket = None
    bracket_abbrevs = []
    try:
        bracket = fetch_json(f"{API}/playoff-bracket/2026")
        seen = set()
        for s in bracket.get("series", []):
            for k in ("topSeedTeam", "bottomSeedTeam"):
                t = s.get(k) or {}
                a = t.get("abbrev")
                if a and a not in seen:
                    seen.add(a)
                    bracket_abbrevs.append(a)
        print(f"Bracket: loaded ({len(bracket_abbrevs)} teams: {bracket_abbrevs})")
    except Exception as e:
        print(f"Bracket: not available ({e})")

    # Standings — used for team metadata (name, wins/losses, gp) and as a
    # fallback when the bracket isn't available yet.
    standings = fetch_json(f"{API}/standings/now")
    all_teams = []
    for t in standings.get("standings", []):
        abbrev = nhl_name(t.get("teamAbbrev", ""))
        if not abbrev: abbrev = t.get("teamAbbrev", "")
        all_teams.append({
            "abbrev": abbrev,
            "name": f"{nhl_name(t.get('placeName',''))} {nhl_name(t.get('teamCommonName',''))}".strip(),
            "wins": t.get("wins", 0), "losses": t.get("losses", 0),
            "gp": t.get("gamesPlayed", 0), "pts": t.get("points", 0),
        })
    standings_by_abbrev = {t["abbrev"]: t for t in all_teams}

    if bracket_abbrevs:
        # Use bracket-determined teams, enriched with standings metadata.
        playoff_teams = []
        for abbrev in bracket_abbrevs:
            meta = standings_by_abbrev.get(abbrev, {})
            playoff_teams.append({
                "abbrev": abbrev,
                "name": meta.get("name", abbrev),
                "wins": meta.get("wins", 0), "losses": meta.get("losses", 0),
                "gp": meta.get("gp", 0), "pts": meta.get("pts", 0),
            })
    else:
        # Fallback: top 16 by points (pre-bracket period).
        all_teams.sort(key=lambda x: x["pts"], reverse=True)
        playoff_teams = all_teams[:16]
    print(f"Teams: {len(all_teams)}, Playoff: {[t['abbrev'] for t in playoff_teams]}")

    # Club stats
    skaters, goalies = [], []
    for team in playoff_teams:
        abbrev = team["abbrev"]
        stats, is_playoff = None, False
        for gt in [3, 2]:
            try:
                s = fetch_json(f"{API}/club-stats/{abbrev}/{SEASON}/{gt}")
                if s.get("skaters") or s.get("goalies"):
                    stats, is_playoff = s, (gt == 3)
                    break
            except: pass
        if not stats:
            print(f"  {abbrev}: no data"); continue
        print(f"  {abbrev}: {len(stats.get('skaters',[]))} skaters, {len(stats.get('goalies',[]))} goalies ({'playoffs' if is_playoff else 'reg'})")

        for p in stats.get("skaters", []):
            skaters.append({
                "name": f"{nhl_name(p.get('firstName',''))} {nhl_name(p.get('lastName',''))}".strip(),
                "team": abbrev, "pos": p.get("positionCode", "C"),
                "gp": p.get("gamesPlayed", 0), "goals": p.get("goals", 0),
                "assists": p.get("assists", 0), "points": p.get("points", 0),
                "headshot": p.get("headshot", ""),
                "regSeason": not is_playoff,
            })
        for g in stats.get("goalies", []):
            goalies.append({
                "name": f"{nhl_name(g.get('firstName',''))} {nhl_name(g.get('lastName',''))}".strip(),
                "team": abbrev, "gp": g.get("gamesPlayed", 0),
                "wins": g.get("wins", 0), "losses": g.get("losses", 0),
                "shutouts": g.get("shutouts", 0),
                "savePct": g.get("savePercentage", 0), "gaa": g.get("goalsAgainstAverage", 0),
                "headshot": g.get("headshot", ""),
                "regSeason": not is_playoff,
            })

    skaters.sort(key=lambda x: x["points"], reverse=True)
    goalies.sort(key=lambda x: x["wins"], reverse=True)
    teams_out = [{"name": t["name"], "abbrev": t["abbrev"], "gp": t["gp"], "wins": t["wins"], "losses": t["losses"]} for t in playoff_teams]

    data = {
        "skaters": skaters, "goalies": goalies, "teams": teams_out,
        "bracket": bracket,
        "lastUpdate": datetime.now().isoformat(),
    }

    with open("nhl-data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    print(f"Written nhl-data.json: {len(skaters)} skaters, {len(goalies)} goalies, {len(teams_out)} teams")

if __name__ == "__main__":
    main()
