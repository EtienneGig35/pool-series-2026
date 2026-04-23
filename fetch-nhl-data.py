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

    # Club stats — UNION of playoff (gameType=3) + regular-season (gameType=2).
    # Players who've played in the playoffs get real stats and regSeason=false.
    # Players who are on the regular-season roster but haven't played a
    # playoff game yet (e.g. injured, healthy scratch like Roope Hintz during
    # DAL's round 1) are included with ZERO stats and regSeason=true, so they
    # still show up in drafts and in Détails Poolers with their team logo and
    # headshot. As soon as they play a playoff game, the next cron cycle
    # promotes them to regSeason=false with real stats.
    def player_key(p):
        # Headshot URL contains the NHL player ID — most reliable unique key.
        # Fall back to full name + position if the headshot is missing.
        hs = p.get("headshot") or ""
        if hs:
            return hs
        return (
            nhl_name(p.get("firstName", "")).lower() + "|" +
            nhl_name(p.get("lastName", "")).lower() + "|" +
            (p.get("positionCode") or "")
        )

    skaters, goalies = [], []
    for team in playoff_teams:
        abbrev = team["abbrev"]
        stats_playoff = {"skaters": [], "goalies": []}
        stats_reg = {"skaters": [], "goalies": []}
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

        n_po_sk = len(stats_playoff.get("skaters", []))
        n_po_go = len(stats_playoff.get("goalies", []))
        n_rg_sk = len(stats_reg.get("skaters", []))
        n_rg_go = len(stats_reg.get("goalies", []))
        if not (n_po_sk or n_po_go or n_rg_sk or n_rg_go):
            print(f"  {abbrev}: no data"); continue

        played_keys_sk = set()
        added_sk = 0
        for p in stats_playoff.get("skaters", []):
            played_keys_sk.add(player_key(p))
            skaters.append({
                "name": f"{nhl_name(p.get('firstName',''))} {nhl_name(p.get('lastName',''))}".strip(),
                "team": abbrev, "pos": p.get("positionCode", "C"),
                "gp": p.get("gamesPlayed", 0),
                "goals": p.get("goals", 0),
                "assists": p.get("assists", 0),
                "points": p.get("points", 0),
                "headshot": p.get("headshot", ""),
                "regSeason": False,
            })
            added_sk += 1
        for p in stats_reg.get("skaters", []):
            if player_key(p) in played_keys_sk:
                continue  # already covered by playoff stats
            skaters.append({
                "name": f"{nhl_name(p.get('firstName',''))} {nhl_name(p.get('lastName',''))}".strip(),
                "team": abbrev, "pos": p.get("positionCode", "C"),
                "gp": 0, "goals": 0, "assists": 0, "points": 0,
                "headshot": p.get("headshot", ""),
                "regSeason": True,
            })
            added_sk += 1

        played_keys_go = set()
        added_go = 0
        for g in stats_playoff.get("goalies", []):
            played_keys_go.add(player_key(g))
            goalies.append({
                "name": f"{nhl_name(g.get('firstName',''))} {nhl_name(g.get('lastName',''))}".strip(),
                "team": abbrev,
                "gp": g.get("gamesPlayed", 0),
                "wins": g.get("wins", 0),
                "losses": g.get("losses", 0),
                "shutouts": g.get("shutouts", 0),
                "savePct": g.get("savePercentage", 0),
                "gaa": g.get("goalsAgainstAverage", 0),
                "headshot": g.get("headshot", ""),
                "regSeason": False,
            })
            added_go += 1
        for g in stats_reg.get("goalies", []):
            if player_key(g) in played_keys_go:
                continue
            goalies.append({
                "name": f"{nhl_name(g.get('firstName',''))} {nhl_name(g.get('lastName',''))}".strip(),
                "team": abbrev,
                "gp": 0, "wins": 0, "losses": 0, "shutouts": 0,
                "savePct": 0, "gaa": 0,
                "headshot": g.get("headshot", ""),
                "regSeason": True,
            })
            added_go += 1

        print(f"  {abbrev}: {added_sk} skaters, {added_go} goalies "
              f"(playoff: {n_po_sk}sk/{n_po_go}go, reg-only extras: "
              f"{added_sk - n_po_sk}sk/{added_go - n_po_go}go)")

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
