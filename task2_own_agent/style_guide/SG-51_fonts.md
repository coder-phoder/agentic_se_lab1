# SG-51: Fonts

Status: ACTIVE
Category: Typography

Team websites use the system font of the device. No web fonts.

- The body font MUST be declared starting with `system-ui`:
  `font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;`
- Code snippets use `ui-monospace, "SF Mono", Consolas, monospace`.
- Don't load fonts from Google Fonts or other services, see the single-file delivery document.
