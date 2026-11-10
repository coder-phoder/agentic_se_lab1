# SG-22: Theme toggle control

Status: ACTIVE
Category: Theming

- The toggle MUST be a `<button>` element with the id `theme-toggle`.
- It MUST have an `aria-label` describing the action, for example `aria-label="Switch to night mode"`.
  Update the label when the theme changes.
- It SHOULD show a sun symbol in night mode and a moon symbol in day mode.
- It SHOULD be placed in the top right corner of the header.
- Don't use a checkbox for the toggle.
