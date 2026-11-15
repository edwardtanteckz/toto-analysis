#!/usr/bin/env python3
"""Generate / show pre-draw picks (3 TOTO sets, 3 4D numbers).

    python make_picks.py --show          # show picks for the next draws (creating them if missing)
    python make_picks.py --regenerate    # replace picks for the next draws with new ones
    python make_picks.py --popularity    # show the number-popularity model
"""
from __future__ import annotations

import argparse
from datetime import date

from analysis import picks
from sgpools import db


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--show", action="store_true")
    p.add_argument("--regenerate", action="store_true")
    p.add_argument("--popularity", action="store_true")
    args = p.parse_args()
    conn = db.connect()
    try:
        picks.score_past(conn)
        dates, _ = picks.ensure_next(conn, regenerate=args.regenerate)
        for game, d in dates.items():
            name = "TOTO" if game == "toto" else "4D"
            print(f"\n{name} picks for {d:%a %d %b %Y}")
            for s in picks.get_picks(conn, game, d):
                nums = " ".join(f"{n:2d}" for n in s["numbers"]) if game == "toto" else s["numbers"]
                print(f"  {s['set_no']}. {s['lens']:<26} {nums}")
                print(f"     {s['rationale']}")
        print(f"\nOdds: TOTO jackpot 1 in {picks.TOTO_ODDS:,} per set; any TOTO prize 1 in {1 / picks.P_TOTO_ANY:.0f}; "
              f"any 4D prize (Big) 1 in {1 / picks.P_4D_ANY:.0f}. Same for every set.")
        if args.popularity:
            m = picks.popularity_model(conn)
            order = sorted(range(49), key=lambda i: m["coef"][i])
            print(f"\nPopularity model: source={m['source']} cv_gain={m['cv_gain']} draws={m['n']}")
            print("  least popular:", [i + 1 for i in order[:10]])
            print("  most popular: ", [i + 1 for i in order[::-1][:10]])
    finally:
        conn.close()


if __name__ == "__main__":
    main()
