# SG-03: Single-file delivery

Status: ACTIVE
Category: Structure

Team websites are delivered as exactly one HTML file.

- All CSS MUST be inside `<style>` elements, all JavaScript inside `<script>` elements.
- The page MUST NOT load anything from the network: no CDNs, no web fonts, no external images, no analytics.
- Images MUST be embedded as data URIs (base64).
- The file SHOULD stay below 8 MB. Compress photos before embedding them (around 400 × 400 pixels is enough).
- The page MUST work when opened directly from the file system (file://).
