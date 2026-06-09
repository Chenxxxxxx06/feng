"""Deprecated demo server entry point.

Synthetic in-memory demo responses are disabled for this project. Run the
FastAPI application and import public or measured datasets instead.
"""

from __future__ import annotations


def main() -> None:
    message = (
        "demo_server.py has been disabled because it generated synthetic PHM "
        "data. Start the real backend with `python -m uvicorn app.main:app "
        "--host 0.0.0.0 --port 8000 --reload`, then import real datasets with "
        "`python -m scripts.import_real_datasets ...`."
    )
    raise SystemExit(message)


if __name__ == "__main__":
    main()
