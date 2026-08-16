import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
webui_dir = str(ROOT_DIR / "webui")
if webui_dir not in __path__:
    __path__.append(webui_dir)

if str(ROOT_DIR) not in sys.path or sys.path[0] != str(ROOT_DIR):
    sys.path.insert(0, str(ROOT_DIR))
