"""Site checker for task2_own_agent (default mode: full). See common/site_checker.py for details.

Usage: python task2_own_agent/check_site.py site/index.html [--content path/to/content] [--full|--basic] [--json]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.site_checker import main  # noqa: E402

if __name__ == "__main__":
    main(default_mode="full")
