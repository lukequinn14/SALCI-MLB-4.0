#!/usr/bin/env python3
"""
SALCI Backfill Script
======================
Run this ONCE to generate reflections for past days where predictions exist.
Useful when you're setting up the new system and want history immediately.

Usage:
  python scripts/backfill_reflections.py 7     # last 7 days
  python scripts/backfill_reflections.py 30    # last 30 days
"""

import os
import sys
import subprocess
from datetime import datetime, timedelta

REPO_ROOT        = os.path.join(os.path.dirname(__file__), "..")
PREDICTIONS_DIR  = os.path.join(REPO_ROOT, "data", "predictions")
REFLECTIONS_DIR  = os.path.join(REPO_ROOT, "data", "reflections")

GENERATE_SCRIPT  = os.path.join(os.path.dirname(__file__), "generate_reflection.py")


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    print(f"Backfilling reflections for the last {days} days …\n")

    generated = 0
    skipped   = 0
    missing   = 0

    for i in range(1, days + 1):
        date_str = (datetime.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        pred_path = os.path.join(PREDICTIONS_DIR, f"{date_str}.json")
        refl_path = os.path.join(REFLECTIONS_DIR, f"{date_str}.json")

        if os.path.exists(refl_path):
            print(f"  {date_str}  ✅ reflection already exists — skipping")
            skipped += 1
            continue

        if not os.path.exists(pred_path):
            print(f"  {date_str}  ⚠️  no predictions found — skipping")
            missing += 1
            continue

        print(f"  {date_str}  🔄 generating reflection …")
        result = subprocess.run(
            [sys.executable, GENERATE_SCRIPT, date_str],
            capture_output=False,
        )
        if result.returncode == 0:
            generated += 1
        else:
            print(f"  {date_str}  ❌ generation failed")

    print(f"\n{'─'*40}")
    print(f"Generated : {generated}")
    print(f"Skipped   : {skipped}  (already existed)")
    print(f"Missing   : {missing}  (no predictions to compare against)")


if __name__ == "__main__":
    main()
