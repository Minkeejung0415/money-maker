"""Save today's NBA picks (props + moneyline) to data/picks_YYYY-MM-DD.txt"""
import os
import re
from datetime import date

# ── Parse props output ───────────────────────────────────────────────────────
props_file = r"C:\Users\justi\AppData\Local\Temp\claude\C--Users-justi-Documents-money-maker\tasks\b7xr42v7p.output"

with open(props_file, encoding="utf-8") as f:
    props_text = f.read()

blocks = re.split(r"\n(?=#\d+\s+EV:)", props_text)
combos = []
for b in blocks:
    m_rank  = re.match(r"#(\d+)", b)
    m_ev    = re.search(r"EV: ([\d.]+)%", b)
    m_edge  = re.search(r"Edge: ([\d.]+)%", b)
    m_odds  = re.search(r"Odds: ([\d.]+)x", b)
    m_mp    = re.search(r"Model Prob: ([\d.]+)%", b)
    m_mkt   = re.search(r"Market Implied: ([\d.]+)%", b)
    m_stake = re.search(r"Stake: \$([\d.]+)", b)
    m_conf  = re.search(r"Confidence: (.+)", b)
    legs    = re.findall(r"• (.+)", b)
    if not m_rank or not m_mp:
        continue
    combos.append({
        "model_prob": float(m_mp.group(1)),
        "ev":    float(m_ev.group(1))    if m_ev    else 0,
        "edge":  float(m_edge.group(1))  if m_edge  else 0,
        "odds":  float(m_odds.group(1))  if m_odds  else 0,
        "mkt":   float(m_mkt.group(1))   if m_mkt   else 0,
        "stake": float(m_stake.group(1)) if m_stake else 0,
        "conf":  m_conf.group(1).strip() if m_conf  else "",
        "legs":  legs,
    })

combos.sort(key=lambda x: x["model_prob"], reverse=True)

# ── Moneyline data ────────────────────────────────────────────────────────────
moneyline = [
    {"rank":1,  "ev":200.6,"edge":5.5,  "odds":36.81,"mp":8.2,  "mkt":2.7,  "stake":140.03, "legs":["Utah Jazz ML (6.30x) model: 27.0%","Houston Rockets ML (2.68x) model: 47.3%","Minnesota Timberwolves ML (2.18x) model: 63.9%"]},
    {"rank":2,  "ev":193.5,"edge":7.6,  "odds":25.37,"mp":11.6, "mkt":3.9,  "stake":198.44, "legs":["Toronto Raptors ML (1.85x) model: 67.0%","Utah Jazz ML (6.30x) model: 27.0%","Minnesota Timberwolves ML (2.18x) model: 63.9%"]},
    {"rank":3,  "ev":175.1,"edge":5.5,  "odds":31.59,"mp":8.7,  "mkt":3.2,  "stake":143.11, "legs":["Orlando Magic ML (2.30x) model: 50.5%","Utah Jazz ML (6.30x) model: 27.0%","Minnesota Timberwolves ML (2.18x) model: 63.9%"]},
    {"rank":4,  "ev":167.2,"edge":5.4,  "odds":31.19,"mp":8.6,  "mkt":3.2,  "stake":138.47, "legs":["Toronto Raptors ML (1.85x) model: 67.0%","Utah Jazz ML (6.30x) model: 27.0%","Houston Rockets ML (2.68x) model: 47.3%"]},
    {"rank":5,  "ev":154.1,"edge":6.2,  "odds":24.83,"mp":10.2, "mkt":4.0,  "stake":161.68, "legs":["Orlando Magic ML (2.30x) model: 50.5%","Toronto Raptors ML (1.85x) model: 67.0%","Houston Rockets ML (2.68x) model: 47.3%","Minnesota Timberwolves ML (2.18x) model: 63.9%"]},
    {"rank":6,  "ev":144.6,"edge":5.4,  "odds":26.77,"mp":9.1,  "mkt":3.7,  "stake":140.28, "legs":["Orlando Magic ML (2.30x) model: 50.5%","Toronto Raptors ML (1.85x) model: 67.0%","Utah Jazz ML (6.30x) model: 27.0%"]},
    {"rank":7,  "ev":136.9,"edge":10.0, "odds":13.73,"mp":17.3, "mkt":7.3,  "stake":268.87, "legs":["Utah Jazz ML (6.30x) model: 27.0%","Minnesota Timberwolves ML (2.18x) model: 63.9%"]},
    {"rank":8,  "ev":118.8,"edge":11.0, "odds":10.79,"mp":20.3, "mkt":9.3,  "stake":303.36, "legs":["Toronto Raptors ML (1.85x) model: 67.0%","Houston Rockets ML (2.68x) model: 47.3%","Minnesota Timberwolves ML (2.18x) model: 63.9%"]},
    {"rank":9,  "ev":115.8,"edge":6.9,  "odds":16.88,"mp":12.8, "mkt":5.9,  "stake":182.20, "legs":["Utah Jazz ML (6.30x) model: 27.0%","Houston Rockets ML (2.68x) model: 47.3%"]},
    {"rank":10, "ev":110.7,"edge":9.5,  "odds":11.64,"mp":18.1, "mkt":8.6,  "stake":260.08, "legs":["Toronto Raptors ML (1.85x) model: 67.0%","Utah Jazz ML (6.30x) model: 27.0%"]},
    {"rank":11, "ev":105.2,"edge":7.8,  "odds":13.44,"mp":15.3, "mkt":7.4,  "stake":211.36, "legs":["Orlando Magic ML (2.30x) model: 50.5%","Houston Rockets ML (2.68x) model: 47.3%","Minnesota Timberwolves ML (2.18x) model: 63.9%"]},
    {"rank":12, "ev":100.3,"edge":10.8, "odds":9.26, "mp":21.6, "mkt":10.8, "stake":303.50, "legs":["Orlando Magic ML (2.30x) model: 50.5%","Toronto Raptors ML (1.85x) model: 67.0%","Minnesota Timberwolves ML (2.18x) model: 63.9%"]},
    {"rank":13, "ev":97.5, "edge":6.7,  "odds":14.49,"mp":13.6, "mkt":6.9,  "stake":180.69, "legs":["Orlando Magic ML (2.30x) model: 50.5%","Utah Jazz ML (6.30x) model: 27.0%"]},
    {"rank":14, "ev":82.4, "edge":7.2,  "odds":11.39,"mp":16.0, "mkt":8.8,  "stake":198.30, "legs":["Orlando Magic ML (2.30x) model: 50.5%","Toronto Raptors ML (1.85x) model: 67.0%","Houston Rockets ML (2.68x) model: 47.3%"]},
    {"rank":15, "ev":76.7, "edge":13.1, "odds":5.84, "mp":30.2, "mkt":17.1, "stake":395.97, "legs":["Houston Rockets ML (2.68x) model: 47.3%","Minnesota Timberwolves ML (2.18x) model: 63.9%"]},
    {"rank":16, "ev":72.5, "edge":18.0, "odds":4.03, "mp":42.8, "mkt":24.8, "stake":500.00, "legs":["Toronto Raptors ML (1.85x) model: 67.0%","Minnesota Timberwolves ML (2.18x) model: 63.9%"]},
    {"rank":17, "ev":61.7, "edge":12.3, "odds":5.01, "mp":32.3, "mkt":19.9, "stake":384.51, "legs":["Orlando Magic ML (2.30x) model: 50.5%","Minnesota Timberwolves ML (2.18x) model: 63.9%"]},
    {"rank":18, "ev":57.1, "edge":11.5, "odds":4.95, "mp":31.7, "mkt":20.2, "stake":361.29, "legs":["Toronto Raptors ML (1.85x) model: 67.0%","Houston Rockets ML (2.68x) model: 47.3%"]},
    {"rank":19, "ev":47.3, "edge":7.7,  "odds":6.16, "mp":23.9, "mkt":16.2, "stake":228.85, "legs":["Orlando Magic ML (2.30x) model: 50.5%","Houston Rockets ML (2.68x) model: 47.3%"]},
    {"rank":20, "ev":43.8, "edge":10.3, "odds":4.25, "mp":33.8, "mkt":23.5, "stake":337.02, "legs":["Orlando Magic ML (2.30x) model: 50.5%","Toronto Raptors ML (1.85x) model: 67.0%"]},
]

# ── Write file ────────────────────────────────────────────────────────────────
today = date.today().isoformat()
os.makedirs("data", exist_ok=True)
out_path = f"data/picks_{today}.txt"

with open(out_path, "w", encoding="utf-8") as f:
    f.write(f"NBA PICKS — {today}\n")
    f.write("=" * 65 + "\n\n")

    # Props
    f.write("SECTION 1: PLAYER PROPS — Top 50 sorted by Model Probability\n")
    f.write("-" * 65 + "\n\n")
    for i, c in enumerate(combos, 1):
        f.write(
            f"#{i}  Model: {c['model_prob']:.1f}%  |  EV: {c['ev']:.1f}%  |  "
            f"Edge: {c['edge']:.1f}%  |  Odds: {c['odds']:.2f}x  |  Stake: ${c['stake']:.2f}\n"
        )
        if c["conf"]:
            f.write(f"    Confidence: {c['conf']}\n")
        for leg in c["legs"]:
            f.write(f"      • {leg}\n")
        f.write("\n")

    # Moneyline
    f.write("\nSECTION 2: MONEYLINE PARLAYS — Top 20 sorted by EV\n")
    f.write("-" * 65 + "\n\n")
    for m in moneyline:
        f.write(
            f"#{m['rank']}  Model: {m['mp']:.1f}%  |  EV: {m['ev']:.1f}%  |  "
            f"Edge: {m['edge']:.1f}%  |  Odds: {m['odds']:.2f}x  |  Stake: ${m['stake']:.2f}\n"
        )
        f.write(f"    Market Implied: {m['mkt']:.1f}%\n")
        for leg in m["legs"]:
            f.write(f"      • {leg}\n")
        f.write("\n")

print(f"Saved {len(combos)} prop combos + {len(moneyline)} ML parlays -> {out_path}")
