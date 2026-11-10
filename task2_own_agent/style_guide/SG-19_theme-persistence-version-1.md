# SG-19: Theme persistence (version 1)

Status: DEPRECATED – replaced by SG-21
Category: Theming

The theme choice of the user is remembered between visits.

- Store the choice in `localStorage` under the key `theme`.
- The stored value is either `light` or `dark`.
- Read the value when the page loads and apply it before the first paint.
