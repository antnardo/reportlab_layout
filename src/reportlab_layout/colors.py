"""Coercing colours into the type reportlab expects."""

from typing import TypeAlias, overload

from reportlab.lib.colors import Color, HexColor, toColor

__all__ = ["ColorLike", "to_color"]

#: Anything that can name a colour in this package. ``None`` means "leave the
#: canvas colour alone".
ColorLike: TypeAlias = Color | str | tuple[float, ...] | list[float] | None


@overload
def to_color(value: None) -> None: ...
@overload
def to_color(value: Color | str | tuple[float, ...] | list[float]) -> Color: ...
def to_color(value: ColorLike) -> Color | None:
    """Normalise a colour into a ``reportlab.lib.colors.Color``.

    Accepts a ``Color``, a CSS name, a hexadecimal string -- ``"#rrggbb"``,
    ``"#rrggbbaa"`` with its opacity, or the short ``"#rgb"`` and ``"#rgba"`` --
    and 3- or 4-tuples of floats in ``[0, 1]``, the fourth being the opacity.
    ``None`` passes through: it means "do not touch the current colour". A
    type checker knows it: anything but ``None`` gives a ``Color``, so a colour
    constant needs no ``assert``.

    So neither ``HexColor`` nor ``Color`` needs importing to name a colour, and
    an opacity below 1 makes whatever is painted with it transparent.
    """
    if value is None or isinstance(value, Color):
        return value
    if isinstance(value, str):
        return _hex(value) if value.startswith("#") else toColor(value)
    if isinstance(value, tuple | list):
        if len(value) == 3:
            return Color(*value)
        if len(value) == 4:
            return Color(value[0], value[1], value[2], alpha=value[3])
        raise ValueError(f"A colour tuple needs 3 or 4 components, got {len(value)}")
    raise TypeError(f"Cannot convert to a colour: {value!r}")


def _hex(value: str) -> Color:
    """A ``#`` colour of 3, 4, 6 or 8 digits.

    reportlab's ``HexColor`` reads the digits as one number: ``"#abc"`` comes
    out as a dark blue, ``0x000abc``, and ``"#rrggbbaa"`` as some other colour,
    both without a word. The short forms are spelled out here, and the opacity
    passed on.
    """
    digits = value[1:]
    if len(digits) in (3, 4):
        digits = "".join(digit * 2 for digit in digits)
    if len(digits) not in (6, 8) or any(digit not in "0123456789abcdefABCDEF" for digit in digits):
        raise ValueError(f"Not a hexadecimal colour: {value!r}")
    return HexColor("#" + digits, hasAlpha=len(digits) == 8)
