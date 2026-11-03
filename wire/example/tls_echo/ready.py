"""Ready check: exit 0 once the server log says it is listening."""

import sys
from pathlib import Path

log = Path(sys.argv[1])
sys.exit(0 if log.exists() and "listening on" in log.read_text() else 1)
