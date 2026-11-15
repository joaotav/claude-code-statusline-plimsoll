#!/usr/bin/env python3
"""Write every test payload to fixtures/*.json for manual preview.

The payloads live in tests/payloads.py; this only dumps them with reset times
relative to now, so `./statusline.py < fixtures/full.json` shows today's
formatting. fixtures/ is generated output and is not tracked.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.payloads import all_payloads  # noqa: E402

OUT = ROOT / "fixtures"


def main():
    OUT.mkdir(exist_ok=True)
    for name, payload in all_payloads(time.time()).items():
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
