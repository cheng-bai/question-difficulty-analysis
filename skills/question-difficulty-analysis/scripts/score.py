"""Standalone CLI entry point for the bundled scoring engine."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from question_difficulty.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
