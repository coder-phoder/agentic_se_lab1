# SG-20: Theme switching mechanics

Status: ACTIVE
Category: Theming

The theme is controlled by one attribute on the root element.

- The `<html>` element MUST carry the attribute `data-theme` with the value `light` or `dark`.
- JavaScript switches the theme by changing this attribute, not by toggling classes on the body.
- The CSS MUST define the colors for each theme with attribute selectors, for example
  `[data-theme="light"] { ... }` and `[data-theme="dark"] { ... }`.
- Components use CSS custom properties (for example `var(--bg)`), so they don't need theme-specific rules.
