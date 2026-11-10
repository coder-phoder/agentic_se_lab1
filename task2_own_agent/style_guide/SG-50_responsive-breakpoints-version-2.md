# SG-50: Responsive breakpoints (version 2)

Status: ACTIVE (version 2)
Category: Responsive

Team websites use exactly one layout breakpoint.

- The breakpoint MUST be written as `@media (max-width: 700px)`.
  The earlier, smaller breakpoint made cards too narrow on large phones.
- Below the breakpoint:
  - member cards are shown in one column
  - the header content is stacked vertically
  - side padding is reduced to 1rem
- The page MUST include `<meta name="viewport" content="width=device-width, initial-scale=1">`.
- Test your page at 375 px and 1280 px width. There must be no horizontal scrolling.
