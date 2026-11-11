import sys
from pathlib import Path

# Add root directory to sys.path so modules like server, connectors can be resolved
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import app
