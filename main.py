import faulthandler
import logging
import os
from pathlib import Path

from app import create_app

LOG_DIR = Path(__file__).resolve().parent / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)
faulthandler.enable()
try:
    _crash_log = open(LOG_DIR / "ava_crash.log", "a", buffering=1, encoding="utf-8")
    faulthandler.enable(_crash_log)
except OSError:
    _crash_log = None

logging.basicConfig(
    filename=str(LOG_DIR / "ava_server.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(threadName)s %(message)s",
)

app = create_app()

if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
        threaded=True,
        use_reloader=False,
    )
