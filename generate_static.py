"""Generate a static, deployable build of the dashboard.

Outputs:
    dist/index.html  - copied from static/index.html
    dist/data.json   - full dashboard payload (fetched via yfinance)

This is what GitHub Actions runs on a schedule and deploys to GitHub Pages.
Locally you can also run it to preview the static site:
    uv run python generate_static.py
    uv run python -m http.server -d dist 8788
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

# Import the shared payload builder (also used by the FastAPI app)
from app import _load_all

HERE = Path(__file__).parent
DIST = HERE / "dist"


def main() -> None:
    DIST.mkdir(parents=True, exist_ok=True)

    print("[build] fetching data via yfinance ...")
    payload = _load_all()

    data_path = DIST / "data.json"
    data_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"[build] wrote {data_path} ({data_path.stat().st_size} bytes)")

    src_html = HERE / "static" / "index.html"
    dst_html = DIST / "index.html"
    shutil.copyfile(src_html, dst_html)
    print(f"[build] copied {src_html} -> {dst_html}")

    print("[build] done. Preview with:")
    print("        uv run python -m http.server -d dist 8788")


if __name__ == "__main__":
    main()
