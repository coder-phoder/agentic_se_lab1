# SG-33: Member photos

Status: ACTIVE
Category: Components

- Each member card contains one `<img>` with a photo, avatar or drawing of the member.
- Every image MUST have a meaningful `alt` text in the format "Photo of <first name>" (or "Avatar of <first name>").
  Empty alt texts are not allowed.
- Images are embedded as data URIs, see the single-file delivery document.
- Photos are displayed as circles with a size of `8rem` × `8rem` and `object-fit: cover`.
- Members who don't want to show a photo use an avatar. This is always fine.
