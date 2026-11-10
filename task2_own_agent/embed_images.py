"""Image embedding helper. See common/embed_images.py for details.

Usage: python task2_own_agent/embed_images.py site/index.html --images content/images
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.embed_images import main  # noqa: E402

if __name__ == "__main__":
    main()
