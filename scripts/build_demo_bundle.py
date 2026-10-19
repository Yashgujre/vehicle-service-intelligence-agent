"""Build the demo data bundle for the hosted app (ADR-0091).

    python scripts/build_demo_bundle.py [--out dist/vsia-demo-bundle.tar.gz]

Prints the manifest with the sha256. Publish the file as a GitHub release asset and set VSIA_BUNDLE_URL and
VSIA_BUNDLE_SHA256 in the hosted app's secrets (docs/runbooks/hosted-demo.md).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from vsia import bundle, config


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=config.REPO_ROOT / "dist" / "vsia-demo-bundle.tar.gz")
    a = ap.parse_args()
    m = bundle.build(a.out)
    print(json.dumps({**m, "out": str(a.out)}, indent=2))


if __name__ == "__main__":
    main()
