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

    # Playoff record per team, derived from the bracket (NOT standings, which
    # still shows 82-game regular-season wins/losses). Each series exposes
    # topSeedWins and bottomSeedWins; summed across all of a team's series
    # this gives the playoff wins-losses-gp we actually want in the pool.
    playoff_record = {}  # abbrev -> {"wins": 0, "losses": 0, "gp": 0}
    if bracket:
        for s in bracket.get("series", []):
            top = s.get("topSeedTeam") or {}
            bot = s.get("bottomSeedTeam") or {}
            top_ab = top.get("abbrev")
            bot_ab = bot.get("abbrev")
            top_w = s.get("topSeedWins", 0) or 0
            bot_w = s.get("bottomSeedWins", 0) or 0
            if top_ab:
                rec = playoff_record.setdefault(top_ab, {"wins": 0, "losses": 0, "gp": 0})
                rec["wins"] += top_w
                rec["losses"] += bot_w
                rec["gp"] += top_w + bot_w
            if bot_ab:
                rec = playoff_record.setdefault(bot_ab, {"wins": 0, "losses": 0, "gp": 0})
                rec["wins"] += bot_w
                rec["losses"] += top_w
                rec["gp"] += top_w + bot_w

    if bracket_abbrevs:
        # Use bracket-determined teams, with playoff record (NOT regular season).
        playoff_teams = []
        for abbrev in bracket_abbrevs:
            meta = standings_by_abbrev.get(abbrev, {})
            rec = playoff_record.get(abbrev, {"wins": 0, "losses": 0, "gp": 0})
            playoff_teams.append({
                "abbrev": abbrev,
                "name": meta.get("name", abbrev),
                "wins": rec["wins"], "losses": rec["losses"],
                "gp": rec["gp"], "pts": meta.get("pts", 0),
            })
    else:
        # Fallback: top 16 by points, pre-bracket period. No playoff data yet,
        # so wins/losses/gp are zeroed.
        all_teams.sort(key=lambda x: x["pts"], reverse=True)
        playoff_teams = [{**t, "wins": 0, "losses": 0, "gp": 0} for t in all_teams[:16]]
    playoff_summary = [(t['abbrev'], '{}-{}'.format(t['wins'], t['losses'])) for t in playoff_teams]
    print(f"Teams: {len(all_teams)}, Playoff: {playoff_summary}")

    # Club stats — always prefer playoff stats (gameType=3). If a team has
    # no playoff game played yet, we still want the roster visible so users
    # can see drafted players, but every stat must be ZERO (otherwise we'd
    # be mixing regular-season totals into the pool standings, which makes
    # drafted players look like they already have 100+ points).
    skaters, goalies = [], []
    for team in playoff_teams:
        abbrev = team["abbrev"]
        stats_playoff = None
        stats_reg = None
        try:
            s3 = fetch_json(f"{API}/club-stats/{abbrev}/{SEASON}/3")
            if s3.get("skaters") or s3.get("goalies"):
                stats_playoff = s3
        except: pass
        try:
            s2 = fetch_json(f"{API}/club-stats/{abbrev}/{SEASON}/2")
            if s2.get("skaters") or s2.get("goalies"):
                stats_reg = s2
        except: pass

        if stats_playoff:
            src, has_playoff = stats_playoff, True
        elif stats_reg:
            src, has_playoff = stats_reg, False  # roster only, stats zeroed below
        else:
            print(f"  {abbrev}: no data"); continue
        print(f"  {abbrev}: {len(src.get('skaters',[]))} skaters, {len(src.get('goalies',[]))} goalies ({'playoffs' if has_playoff else 'roster-only (no playoff game yet)'})")

        for p in src.get("skaters", []):
            skaters.append({
                "name": f"{nhl_name(p.get('firstName',''))} {nhl_name(p.get('lastName',''))}".strip(),
                "team": abbrev, "pos": p.get("positionCode", "C"),
                "gp": p.get("gamesPlayed", 0) if has_playoff else 0,
                "goals": p.get("goals", 0) if has_playoff else 0,
                "assists": p.get("assists", 0) if has_playoff else 0,
                "points": p.get("points", 0) if has_playoff else 0,
                "headshot": p.get("headshot", ""),
                "regSeason": not has_playoff,
            })
        for g in src.get("goalies", []):
            goalies.append({
                "name": f"{nhl_name(g.get('firstName',''))} {nhl_name(g.get('lastName',''))}".strip(),
                "team": abbrev,
                "gp": g.get("gamesPlayed", 0) if has_playoff else 0,
                "wins": g.get("wins", 0) if has_playoff else 0,
                "losses": g.get("losses", 0) if has_playoff else 0,
                "shutouts": g.get("shutouts", 0) if has_playoff else 0,
                "savePct": g.get("savePercentage", 0) if has_playoff else 0,
                "gaa": g.get("goalsAgainstAverage", 0) if has_playoff else 0,
                "headshot": g.get("headshot", ""),
                "regSeason": not has_playoff,
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
