# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

## [1.0.2] — 2026-08-25

### Fixed

- **Text no longer inherits the canvas fill colour.** `draw_string` and
  `apply_style` only set the fill when given an explicit colour, so a string
  drawn right after a filled shape came out in that shape's colour — white on
  white where the shape was a white background, which made the text vanish
  entirely. Both now default to black; pass `color=None` to deliberately keep
  the current colour.

  This is a regression against the module this package grew out of, whose
  `set_style` reset the fill to black on every call. It is worth checking any
  document produced with 1.0.0 or 1.0.1 that draws text over filled shapes.

## [1.0.1] — 2026-08-25

A documentation release. Nothing executable changed: same behaviour, same API,
same output. What changed is everything you read around it.

### Changed

- Documentation, docstrings and comments are now in English throughout — the
  reference, the changelog, the examples, the scripts and everything `help()`
  and an IDE will show you.
- `examples/attestation.py` is now `examples/certificate.py`.
- The two centring figures are replaced by a single
  `docs/img/centering.png`, reproducible from `scripts/centering_proof.py`
  alone. The one it replaced was generated from a private module and could not
  be rebuilt from this repository.

### Fixed

- Links and the figure on the package page. The 1.0.0 README used repository
  paths relative to itself, which PyPI does not resolve, so they rendered dead.
  They are absolute now.
- The version is declared in one place only, `reportlab_layout.__version__`, and
  read from there by the build. It used to be repeated in `pyproject.toml`,
  where it could drift from the tag the publish workflow checks against.

## [1.0.0] — 2026-08-25

First published release. `pdf_maker`, until now a private local module, is split
up, corrected and renamed `reportlab_layout`. The API moves to `snake_case`: a
deliberate break, with the full mapping in
[`docs/DOC.md`](docs/DOC.md#migrating-from-pdf_maker).

### Fixed

- **Vertical text centring.** The anchor was worked out as `y - height/2` with
  `height = ascent - descent`. Since the descent is negative, text dropped by
  `|descent|` too much, roughly 20% of the type size. The correct offset is
  `(ascent + descent)/2`.
- **Metrics ignoring the drawing scale.** `drawStringCenterHV` and
  `drawStringLeftCenterV` read the height at the style's nominal size while the
  text was drawn at `fontSize × size`; `drawStringCenterH` measured the width
  the same way. At `size=0.5` the centring was wrong by a factor of two, both
  horizontally and vertically. `TextMetrics` now carries the scale and every
  metric accounts for it.
- **`before` read in two different units.** It was converted to `unit` to place
  the element, but added to the cursor in points, shifting everything after it.
- **`drawParagraph`'s `valign="top"`.** The height, in points, was added to an
  ordinate expressed in `unit`. Replaced by `valign` on `draw()`, applied in
  absolute mode.
- **`drawTable`'s `addstyle`.** `TableStyle.add(list)` pushed the list on as a
  single command, which made rendering the table fail with
  `ValueError: not enough values to unpack`. Extra commands now go through
  `style=`.
- **`frameParagraph` raised `TypeError`.** It forwarded `fontsize=` to
  `getParagraph`, which took no such parameter.
- **`get_image` raised `TypeError` without a width.** The `hauteur` and `scale`
  parameters were declared but ignored. `ImageSpec.scaled` handles them and
  refuses an unconstrained request outright.
- **`drawParagraph` returned `(paragraph, box)`**, out of step with the other
  drawing methods, which broke callers unpacking four values. Every method now
  returns a `Box`.
- **`NumberedCanvas` lost the last page** when used as a standalone canvas,
  without a `DocTemplate`.
- **Canvas state leaking.** Colours, line width and rotation were not restored
  after a drawing and contaminated the next one.
- **Style collisions.** The `styles` sheet was a shared module-level object: two
  modules defining the same style name raised `KeyError` at import time.
- **Printing to standard output.** `newFrame` and `drawFrame` always wrote to
  `stdout`; the package now goes through `logging`.

### Added

- `Box`, the named 4-tuple every drawing call returns.
- `TextMetrics`, a style's metrics at a given scale, with the anchors.
- `PageGeometry` and `Cursor`, the sole owners of coordinate conversion.
- `draw_string`, one method replacing the four string-drawing variants, with
  `halign`, `valign`, `angle`, `dx`, `dy`.
- The `valign="cap"` anchor, centring on the cap box: on a short label the ink
  lands within a tenth of a point of the middle of its box, and a row of labels
  shares one baseline whatever their descenders. `TextMetrics.cap_height` rests
  on `STANDARD_CAP_HEIGHTS`, a table taken from Adobe's AFM files that reportlab
  does not expose; `scripts/cap_height_probe.py` checks it by rasterisation.
- `ImageSpec`, replacing the dictionary with French keys.
- `make_stylesheet()` and `add_style()`, for isolated stylesheets.
- Context-manager support: the output is only written if the block succeeds.
- `cursor_y`, `cursor_point`, `remaining_height`, `Cursor.fits`.
- Support for page-size names (`"A4"`, `"letter"`) and for colours given as hex
  or CSS names.
- Type annotations across the public API, with `py.typed`.
- 131 tests, run on Python 3.11 to 3.14 and reportlab 4.x and 5.x.
