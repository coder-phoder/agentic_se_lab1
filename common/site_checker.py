"""Checks a single-file team website.

Two modes:
  basic – the technical requirements of Task 1
  full  – basic + the rules of the UPB Agentic SE Web Style Guide (Task 2)

Command line:
    python check_site.py site/index.html [--full] [--content ../task1_opencode/content] [--json]

From Python:
    from common.site_checker import check_site
    report = check_site(html_text, mode="full", member_names=["Anna", "Ben"])
    print(report.summary())
    report.passed  -> bool

The failure messages deliberately don't quote the style guide. Look the rules up yourself.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
MAX_FILE_BYTES = 8 * 1024 * 1024


@dataclass
class Element:
    tag: str
    attrs: dict[str, str]
    parent: "Element | None" = None
    children: list["Element"] = field(default_factory=list)
    text: list[str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def iter(self):
        yield self
        for child in self.children:
            yield from child.iter()

    def all_text(self) -> str:
        parts = list(self.text)
        for child in self.children:
            parts.append(child.all_text())
        return " ".join(p for p in parts if p)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#root", {})
        self.stack = [self.root]
        self.styles: list[str] = []
        self.scripts: list[str] = []
        self._raw_target: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        element = Element(tag, {k: (v or "") for k, v in attrs}, parent=self.stack[-1])
        self.stack[-1].children.append(element)
        if "style" in element.attrs:
            self.styles.append(element.attrs["style"])
        if tag not in VOID_TAGS:
            self.stack.append(element)
        if tag == "style":
            self._raw_target = self.styles
            self.styles.append("")
        elif tag == "script" and "src" not in element.attrs:
            self._raw_target = self.scripts
            self.scripts.append("")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._raw_target = None
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._raw_target is not None:
            self._raw_target[-1] += data
        else:
            self.stack[-1].text.append(data.strip())


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    style_guide: bool = False


@dataclass
class CheckReport:
    results: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    def summary(self, only_failures: bool = False) -> str:
        lines = []
        for r in self.results:
            if only_failures and r.passed:
                continue
            status = "PASS" if r.passed else "FAIL"
            lines.append(f"[{status}] {r.name}: {r.message}")
        n_pass = sum(r.passed for r in self.results)
        lines.append(f"{n_pass}/{len(self.results)} checks passed." + (" All good!" if self.passed else ""))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "results": [r.__dict__ for r in self.results]}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def check_site(
    html: str,
    mode: str = "basic",
    member_names: list[str] | None = None,
    file_size: int | None = None,
) -> CheckReport:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    root = builder.root
    css = "\n".join(builder.styles)
    js = "\n".join(builder.scripts)
    elements = list(root.iter())
    by_tag: dict[str, list[Element]] = {}
    for el in elements:
        by_tag.setdefault(el.tag, []).append(el)
    body_text = _norm(root.all_text())

    results: list[CheckResult] = []

    def add(name, passed, ok_msg, fail_msg, style_guide=False):
        results.append(CheckResult(name, bool(passed), ok_msg if passed else fail_msg, style_guide))

    # ------------------------------------------------------------------ basic
    size = file_size if file_size is not None else len(html.encode("utf-8"))
    add("file size", size <= MAX_FILE_BYTES, f"{size / 1024:.0f} KB",
        f"{size / 1024 / 1024:.1f} MB is larger than the {MAX_FILE_BYTES // 1024 // 1024} MB limit (images too large?)")

    external = []
    resource_attrs = {"script": ["src"], "link": ["href"], "img": ["src", "srcset"], "source": ["src", "srcset"],
                      "iframe": ["src"], "video": ["src", "poster"], "audio": ["src"], "embed": ["src"],
                      "object": ["data"], "input": ["src"]}
    for tag, attrs in resource_attrs.items():
        for el in by_tag.get(tag, []):
            for attr in attrs:
                value = el.attrs.get(attr, "")
                if value and not value.startswith(("data:", "#")) and not (tag == "link" and "canonical" in el.attrs.get("rel", "")):
                    external.append(f"<{tag} {attr}=\"{value[:60]}\">")
    for match in re.finditer(r"url\(\s*['\"]?(?!data:|#)([^'\")]+)", css):
        external.append(f"url({match.group(1)[:60]})")
    for match in re.finditer(r"@import\s+[^;]+", css):
        external.append(match.group(0)[:60])
    for match in re.finditer(r"""\b(?:fetch|import)\s*\(\s*['"](https?:)?//""", js):
        external.append(match.group(0)[:60])
    add("no external resources", not external, "everything is inside the file",
        "file loads external resources: " + ", ".join(external[:5]))

    viewport = any("viewport" in el.attrs.get("name", "") for el in by_tag.get("meta", []))
    add("viewport meta tag", viewport, "present", "missing <meta name=\"viewport\" ...> (needed for mobile)")

    media_query = re.search(r"@media[^{]*(max|min)-width", css)
    add("responsive CSS", media_query, "width-based media query found", "no width-based @media query found")

    has_control = bool(by_tag.get("button") or by_tag.get("input"))
    theme_js = re.search(r"dark|night|theme", js, re.I)
    add("day/night toggle", has_control and theme_js, "button + theme switching script found",
        "no toggle found (needs a button/input and JavaScript that switches the theme)")

    images = by_tag.get("img", [])
    min_images = len(member_names) if member_names else 1
    not_embedded = [el.attrs.get("src", "")[:40] for el in images if not el.attrs.get("src", "").startswith("data:image/")]
    leftover = "{{image:" in html
    add("embedded images",
        len(images) >= min_images and not not_embedded and not leftover,
        f"{len(images)} images, all embedded as data URIs",
        f"found {len(images)} <img> (need at least {min_images}); not embedded: {not_embedded[:3]}"
        + ("; unresolved {{image:...}} placeholders left" if leftover else ""))

    if member_names:
        missing = [n for n in member_names if n.lower() not in body_text.lower()]
        add("all members present", not missing, f"all {len(member_names)} members mentioned",
            f"members not mentioned on the page: {missing}")

    if mode != "full":
        return CheckReport(results)

    # ------------------------------------------------------------ style guide
    html_el = (by_tag.get("html") or [Element("html", {})])[0]
    titles = by_tag.get("title", [])
    title = _norm(titles[0].all_text()) if titles else ""
    add("page title", re.fullmatch(r"Team \S.* \| Agentic SE Lab", title), f"'{title}'",
        f"page title '{title}' does not follow the style guide format", True)

    add("document language", html_el.attrs.get("lang", "").lower() == "en", "lang set correctly",
        "the language attribute of the page does not follow the style guide", True)

    css_lower = css.lower()
    add("day mode colors", "#fff8e7" in css_lower and "#1d1d1f" in css_lower, "day palette found",
        "day mode background/text colors are not the ones from the style guide", True)
    add("night mode colors", "#14142b" in css_lower and "#f4f1de" in css_lower, "night palette found",
        "night mode background/text colors are not the ones from the style guide", True)
    add("accent color", re.search(r"--accent\s*:\s*#e4007c", css_lower), "accent variable found",
        "the accent color is not defined as required by the style guide", True)

    theme_attr = "data-theme" in js and "data-theme" in css
    add("theme mechanism", theme_attr, "theme switched via the required attribute",
        "the theme is not switched the way the style guide requires (check both CSS and JavaScript)", True)
    add("theme persistence", "localstorage" in js.lower() and re.search(r"""['"]upb-theme['"]""", js),
        "theme choice is persisted", "the theme choice is not persisted as required by the style guide", True)

    toggle = next((el for el in elements if el.attrs.get("id") == "theme-toggle"), None)
    add("toggle control", toggle is not None and toggle.tag == "button" and toggle.attrs.get("aria-label", "").strip(),
        "toggle control follows the style guide", "the toggle control does not follow the style guide", True)

    cards = [el for el in by_tag.get("article", []) if "member-card" in el.classes]
    expected_cards = len(member_names) if member_names else None
    cards_ok = len(cards) >= 2 if expected_cards is None else len(cards) == expected_cards
    add("member cards", cards_ok, f"{len(cards)} member cards",
        f"found {len(cards)} member cards in the required markup"
        + (f", expected {expected_cards}" if expected_cards else ""), True)

    cards_without_badge = sum(1 for card in cards if not any("hot-take" in el.classes for el in card.iter()))
    add("hot take badges", cards and cards_without_badge == 0, "every member card has its badge",
        f"{cards_without_badge} of {len(cards)} member cards are missing a required element", True)

    missing_alt = sum(1 for el in images if not el.attrs.get("alt", "").strip())
    add("image alt texts", images and missing_alt == 0, "all images have alt text",
        f"{missing_alt} images do not follow the photo rules of the style guide", True)

    footers = by_tag.get("footer", [])
    footer_text = _norm(" ".join(f.all_text() for f in footers))
    add("footer", "Built by an agent, supervised by humans." in footer_text, "footer text correct",
        "the footer does not follow the style guide", True)

    add("breakpoint", re.search(r"@media[^{]*max-width\s*:\s*700px", css), "mobile breakpoint correct",
        "the mobile breakpoint does not follow the style guide", True)

    px_fonts = re.findall(r"font-size\s*:\s*[\d.]+px", css)
    add("font size units", not px_fonts, "font sizes use the required unit",
        f"{len(px_fonts)} font-size declarations use a unit the style guide does not allow", True)
    add("font family", re.search(r"font-family\s*:\s*system-ui", css), "font stack correct",
        "the font family does not follow the style guide", True)

    ids = {el.attrs.get("id") for el in elements}
    add("page sections", {"team", "future-of-se"} <= ids, "required sections present",
        "the required page sections are missing or have the wrong ids", True)

    h1_count = len(by_tag.get("h1", []))
    add("heading hierarchy", h1_count == 1, "exactly one h1",
        f"found {h1_count} h1 elements; check the heading rules of the style guide", True)

    uses_motion = re.search(r"\b(animation|transition)\s*:", css)
    add("reduced motion", not uses_motion or "prefers-reduced-motion" in css,
        "motion rules respected" if uses_motion else "no animations used",
        "the page uses animations/transitions but ignores the motion rules of the style guide", True)

    return CheckReport(results)


def member_names_from_content(content_dir: Path) -> list[str]:
    return sorted(p.stem.capitalize() for p in content_dir.glob("*.md") if not p.name.startswith("_"))


def main(default_mode: str = "basic") -> None:
    parser = argparse.ArgumentParser(description="Check a single-file team website.")
    parser.add_argument("html_file", type=Path)
    parser.add_argument("--full", action="store_true", help="also check the style guide rules (Task 2)")
    parser.add_argument("--basic", action="store_true", help="only the basic checks")
    parser.add_argument("--content", type=Path, help="content directory with <firstname>.md files")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    mode = "full" if args.full else "basic" if args.basic else default_mode
    html = args.html_file.read_text(encoding="utf-8")
    names = member_names_from_content(args.content) if args.content else None
    report = check_site(html, mode=mode, member_names=names, file_size=args.html_file.stat().st_size)
    print(json.dumps(report.to_dict(), indent=2) if args.json else report.summary())
    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
