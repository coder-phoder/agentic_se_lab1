# SG-21: Theme persistence (version 2)

Status: ACTIVE (version 2)
Category: Theming

The theme choice of the user is remembered between visits.

- The choice MUST be stored in `localStorage` under the key `upb-theme`.
  The old key was too generic and collided with other local files.
- The stored value is either `light` or `dark`.
- On page load, read the stored value. If there is none, follow the operating system preference.
- Apply the theme as early as possible to avoid a flash of the wrong theme.
