"""Replaces image placeholders in an HTML file with embedded base64 data URIs.

Placeholder format (anywhere in the HTML, typically in an <img src="...">):
    {{image:anna.jpg}}

Command line:
    python embed_images.py site/index.html --images content/images [--out site/index.html]

From Python:
    from common.embed_images import embed_images
    html = embed_images(html, images_dir)

Why? A base64-encoded photo is hundreds of thousands of characters. Letting the model
write that would cost a huge number of output tokens and the model would get it wrong.
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
PLACEHOLDER = re.compile(r"\{\{\s*image:\s*([^}\s]+)\s*\}\}")


def image_to_data_uri(path: Path) -> str:
    mime = MIME_TYPES.get(path.suffix.lower())
    if mime is None:
        raise ValueError(f"Unsupported image type: {path.name}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def embed_images(html: str, images_dir: Path) -> str:
    """Replace all {{image:<file>}} placeholders. Raises FileNotFoundError for unknown files."""
    images_dir = Path(images_dir).resolve()

    def replace(match: re.Match) -> str:
        path = (images_dir / match.group(1)).resolve()
        if images_dir not in path.parents:
            raise ValueError(f"Image path escapes the images directory: {match.group(1)}")
        if not path.is_file():
            available = ", ".join(sorted(p.name for p in images_dir.iterdir())) or "none"
            raise FileNotFoundError(f"Image '{match.group(1)}' not found. Available: {available}")
        return image_to_data_uri(path)

    return PLACEHOLDER.sub(replace, html)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("html_file", type=Path)
    parser.add_argument("--images", type=Path, required=True, help="directory containing the images")
    parser.add_argument("--out", type=Path, help="output file (default: overwrite the input file)")
    args = parser.parse_args()

    html = args.html_file.read_text(encoding="utf-8")
    count = len(PLACEHOLDER.findall(html))
    try:
        result = embed_images(html, args.images)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    out = args.out or args.html_file
    out.write_text(result, encoding="utf-8")
    print(f"Embedded {count} image placeholder(s) → {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
