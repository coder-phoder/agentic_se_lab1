# SG-55: Motion and animation

Status: ACTIVE
Category: Accessibility

Animations are allowed, but they must respect the user's settings.

- Transitions SHOULD be short (at most 300 ms). A smooth color transition when switching the theme is nice.
- If the page uses any `animation` or `transition`, it MUST include a `@media (prefers-reduced-motion: reduce)` block
  that disables them.
- No autoplaying videos, no blinking or flashing elements.
