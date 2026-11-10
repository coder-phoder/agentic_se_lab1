# SG-18: Dark mode philosophy

Status: ACTIVE
Category: Theming

Users choose their theme, but we start with a sensible default.

- If the user has never chosen a theme, the page SHOULD follow the operating system preference (`prefers-color-scheme`).
- As soon as the user clicks the toggle, their choice wins and is remembered, see the theme persistence document.
- Switching the theme MUST NOT reload the page.
