"""Run every automated check: the pytest suite, then the end-to-end smoke run.

    cd backend
    python run_detailed_self_test.py

Both use temporary databases - your real data is never touched.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def main() -> int:
    print("== pytest ==")
    code = subprocess.call([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=HERE)
    if code != 0:
        return code
    print("\n== end-to-end smoke run ==")
    return subprocess.call([sys.executable, "full_verification.py"], cwd=HERE)


if __name__ == "__main__":
    sys.exit(main())
