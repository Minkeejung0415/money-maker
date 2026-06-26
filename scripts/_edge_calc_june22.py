"""WC 2026 — June 22/23 edge calculator"""

def am_to_dec(american):
    if american > 0:
        return american / 100 + 1
    else:
        return 100 / abs(american) + 1

def implied(d): return 1 / d
def edge(mp, d): return mp - implied(d)

games = {
    "NZL vs Egypt": {
        "home_name": "NZL", "away_name": "Egypt",
        "model": {"home": 0.240, "draw": 0.245, "away": 0.515, "o25": 0.451, "u25": 0.549, "btts_y": 0.452, "btts_n": 0.548},
        "market": {
            "home": am_to_dec(500), "draw": am_to_dec(300), "away": am_to_dec(-170),
            "o25": am_to_dec(104), "u25": am_to_dec(-128), "btts_y": None, "btts_n": None,
        },
    },
    "Argentina vs Austria": {
        "home_name": "Argentina", "away_name": "Austria",
        "model": {"home": 0.673, "draw": 0.186, "away": 0.141, "o25": 0.430, "u25": 0.570, "btts_y": 0.387, "btts_n": 0.613},
        "market": {
            "home": am_to_dec(-167), "draw": am_to_dec(300), "away": am_to_dec(475),
            "o25": am_to_dec(-102), "u25": am_to_dec(-114), "btts_y": None, "btts_n": None,
        },
    },
    "France vs Iraq": {
        "home_name": "France", "away_name": "Iraq",
        "model": {"home": 0.831, "draw": 0.120, "away": 0.049, "o25": 0.696, "u25": 0.304, "btts_y": 0.484, "btts_n": 0.516},
        "market": {
            "home": am_to_dec(-1000), "draw": am_to_dec(900), "away": am_to_dec(3300),
            "o25": am_to_dec(-225), "u25": am_to_dec(185), "btts_y": None, "btts_n": None,
        },
    },
    "Norway vs Senegal": {
        "home_name": "Norway", "away_name": "Senegal",
        "model": {"home": 0.459, "draw": 0.267, "away": 0.274, "o25": 0.528, "u25": 0.472, "btts_y": 0.560, "btts_n": 0.440},
        "market": {
            "home": am_to_dec(110), "draw": am_to_dec(230), "away": am_to_dec(250),
            "o25": am_to_dec(-105), "u25": am_to_dec(-115),
            "btts_y": am_to_dec(-140), "btts_n": am_to_dec(115),
        },
    },
    "Jordan vs Algeria": {
        "home_name": "Jordan", "away_name": "Algeria",
        "model": {"home": 0.261, "draw": 0.259, "away": 0.480, "o25": 0.480, "u25": 0.520, "btts_y": 0.494, "btts_n": 0.506},
        "market": {
            "home": am_to_dec(650), "draw": am_to_dec(290), "away": am_to_dec(-209),
            "o25": None, "u25": None, "btts_y": None, "btts_n": None,
        },
    },
    "Portugal vs Uzbekistan": {
        "home_name": "Portugal", "away_name": "Uzbekistan",
        "model": {"home": 0.671, "draw": 0.187, "away": 0.142, "o25": 0.518, "u25": 0.482, "btts_y": 0.464, "btts_n": 0.536},
        "market": {
            "home": am_to_dec(-400), "draw": am_to_dec(550), "away": am_to_dec(800),
            "o25": am_to_dec(-104), "u25": am_to_dec(-126), "btts_y": None, "btts_n": None,
        },
    },
    "England vs Ghana": {
        "home_name": "England", "away_name": "Ghana",
        "model": {"home": 0.834, "draw": 0.118, "away": 0.048, "o25": 0.563, "u25": 0.437, "btts_y": 0.316, "btts_n": 0.684},
        "market": {
            "home": am_to_dec(-300), "draw": am_to_dec(400), "away": am_to_dec(800),
            "o25": am_to_dec(104), "u25": am_to_dec(-134),
            "btts_y": am_to_dec(155), "btts_n": am_to_dec(-190),
        },
    },
    "Panama vs Croatia": {
        "home_name": "Panama", "away_name": "Croatia",
        "model": {"home": 0.190, "draw": 0.215, "away": 0.595, "o25": 0.649, "u25": 0.351, "btts_y": 0.621, "btts_n": 0.379},
        "market": {
            "home": am_to_dec(500), "draw": am_to_dec(300), "away": am_to_dec(-188),
            "o25": am_to_dec(-112), "u25": am_to_dec(-108), "btts_y": None, "btts_n": None,
        },
    },
}

print("=" * 80)
print(f"{'WC 2026 — EDGE CALCULATOR  |  June 22-23 (Pacific)':^80}")
print("=" * 80)

all_edges = []

for game_name, gd in games.items():
    mkt = gd["market"]
    mod = gd["model"]
    home = gd["home_name"]
    away = gd["away_name"]
    labels = {
        "home": f"{home} Win", "draw": "Draw", "away": f"{away} Win",
        "o25": "O2.5", "u25": "U2.5", "btts_y": "BTTS Yes", "btts_n": "BTTS No",
    }
    print(f"\n  {game_name}")
    print(f"  {'Bet':<20} {'Model':>7} {'Implied':>8} {'Edge':>7} {'Odds':>8}")
    print(f"  {'-'*54}")
    for key in ["home", "draw", "away", "o25", "u25", "btts_y", "btts_n"]:
        dec = mkt.get(key)
        if dec is None:
            continue
        mp = mod[key]
        imp = implied(dec)
        e = edge(mp, dec)
        flag = "  << STRONG" if e >= 0.08 else ("  < edge" if e >= 0.03 else "")
        print(f"  {labels[key]:<20} {mp:>6.1%}  {imp:>7.1%}  {e:>+6.1%}  {dec:>7.2f}x{flag}")
        all_edges.append((e, game_name, labels[key], dec, mp))

print("\n")
print("=" * 80)
print("  POSITIVE EDGE SUMMARY  (sorted, edge >= 2%)")
print("=" * 80)
positives = [(e, gn, lbl, dec, mp) for e, gn, lbl, dec, mp in all_edges if e >= 0.02]
positives.sort(reverse=True)
print(f"\n  {'Game':<26} {'Bet':<20} {'Model':>7} {'Implied':>8} {'Edge':>7} {'Odds':>8}")
print(f"  {'-'*74}")
for e, gn, lbl, dec, mp in positives:
    flag = "  ★★" if e >= 0.08 else ("  ★" if e >= 0.05 else "")
    print(f"  {gn:<26} {lbl:<20} {mp:>6.1%}  {1/dec:>7.1%}  {e:>+6.1%}  {dec:>7.2f}x{flag}")

print("\n")
print("=" * 80)
print("  TOP SGP COMBINATIONS  (joint model prob vs standalone price product)")
print("  * Actual SGP quote will be lower due to correlation discount")
print("=" * 80)
sgp = [
    ("France vs Iraq",      "France Win + O2.5",     0.631, am_to_dec(-1000)*am_to_dec(-225)),
    ("England vs Ghana",    "ENG Win + BTTS No",     0.605, am_to_dec(-300)*am_to_dec(-190)),
    ("England vs Ghana",    "ENG Win + O2.5",        0.529, am_to_dec(-300)*am_to_dec(104)),
    ("Panama vs Croatia",   "O2.5 + BTTS Yes",       0.525, am_to_dec(-112)*am_to_dec(110)),
    ("Argentina vs Austria","ARG Win + U2.5",        0.486, am_to_dec(-167)*am_to_dec(-114)),
    ("Argentina vs Austria","ARG Win + BTTS No",     0.450, am_to_dec(-167)*am_to_dec(100)),
    ("Panama vs Croatia",   "CRO Win + O2.5",        0.438, am_to_dec(-188)*am_to_dec(-112)),
]
print(f"\n  {'Game':<26} {'Legs':<26} {'Joint':>6} {'ProdOdds':>9} {'Impl':>7} {'Edge':>7}")
print(f"  {'-'*78}")
for game, legs, jp, prod in sgp:
    imp = implied(prod)
    e = jp - imp
    flag = "  ★" if e >= 0.05 else ""
    print(f"  {game:<26} {legs:<26} {jp:>5.1%}  {prod:>8.2f}x  {imp:>6.1%}  {e:>+6.1%}{flag}")

print()
