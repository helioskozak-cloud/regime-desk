import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "deploy"))
from api_server import app  # noqa: F401 — re-exported for gunicorn
