"""Bitmap images: reading their size and scaling them, in the flow or inside a line.

``reportlab.platypus.Image`` can load a file but will not preserve its aspect
ratio when given only one dimension. :class:`ImageSpec` reads the pixel size
once and works the other dimension out.

Inside a line of text, reportlab takes an ``<img/>`` tag in a paragraph's markup,
but stands the image on a point of its own: 0.2 em below the baseline by default,
wherever the image's own baseline is. That is right for an icon, wrong for text
turned into an image -- a formula typeset by TeX, a word in another script --
which has to sit on the baseline of the line around it, its depth below.
:func:`inline_image` writes the tag that does that. The line has to make room
for the image, which takes ``autoLeading="max"`` on the paragraph's style, and
an :class:`~reportlab_layout.InlineParagraph` when the image may land on the
first line.

An image needs no file: raw bytes, an open binary file and a Pillow image all
work, and their transparency survives. A page recompressed in memory, or a
stamp tinted on a transparent ground, never has to be written to disk first.
"""

import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TypeAlias
from xml.sax.saxutils import quoteattr

import PIL.Image as PILImage
from reportlab.platypus import Image

__all__ = ["ImageLike", "ImageSpec", "image_spec", "inline_image", "load_image"]

#: Anything this package can draw as an image: a path, the bytes of an encoded
#: image, an open binary file, or a Pillow image.
ImageLike: TypeAlias = "str | os.PathLike[str] | bytes | IO[bytes] | PILImage.Image | ImageSpec"


@dataclass(frozen=True, slots=True)
class ImageSpec:
    """Where an image comes from, and its size in pixels.

    It holds either a ``path`` or the encoded ``data``, never both. An image
    read from a file is kept as a path, so reportlab can inline a JPEG as it
    stands instead of re-encoding it.
    """

    path: Path | None
    width: int
    height: int
    data: bytes | None = None

    @property
    def aspect(self) -> float:
        """Height over width."""
        return self.height / self.width

    def scaled(
        self,
        width: float | None = None,
        height: float | None = None,
        scale: float | None = None,
    ) -> tuple[float, float]:
        """Drawing size in points, derived from a single constraint.

        Exactly one of the three must be given -- unless ``width`` and
        ``height`` are given together, in which case the aspect ratio is not
        preserved, which is sometimes what you want.
        """
        if scale is not None:
            if width is not None or height is not None:
                raise ValueError("scale is exclusive of width and height")
            return self.width * scale, self.height * scale
        if width is not None and height is not None:
            return float(width), float(height)
        if width is not None:
            return float(width), width * self.aspect
        if height is not None:
            return height / self.aspect, float(height)
        raise ValueError("Give one of width, height or scale")


def image_spec(source: ImageLike) -> ImageSpec:
    """Read an image's pixel size, from wherever it comes.

    A path is kept as a path. Bytes and an open binary file are kept as they
    are. A Pillow image is encoded to PNG, which is lossless and carries an
    alpha channel, since reportlab reads an encoded image rather than a Pillow
    one.
    """
    if isinstance(source, ImageSpec):
        return source
    if isinstance(source, str | os.PathLike):
        path = Path(source)
        with PILImage.open(path) as image:
            width, height = image.size
        return ImageSpec(path=path, width=width, height=height)
    if isinstance(source, PILImage.Image):
        buffer = io.BytesIO()
        source.save(buffer, "PNG")
        return ImageSpec(path=None, width=source.width, height=source.height, data=buffer.getvalue())
    data = source if isinstance(source, bytes) else source.read()
    with PILImage.open(io.BytesIO(data)) as image:
        width, height = image.size
    return ImageSpec(path=None, width=width, height=height, data=data)


def load_image(
    spec: ImageLike,
    width: float | None = None,
    height: float | None = None,
    scale: float | None = None,
) -> Image:
    """Return an ``Image`` flowable sized in points.

    ``spec`` may be an :class:`ImageSpec` already read, or anything
    :func:`image_spec` accepts. An image held in memory is handed to reportlab
    through a fresh buffer each call, so the same spec can be drawn many times.
    Transparency is kept: reportlab's default mask reads the alpha channel.
    """
    spec = image_spec(spec)
    draw_width, draw_height = spec.scaled(width=width, height=height, scale=scale)
    image = Image(io.BytesIO(spec.data) if spec.data is not None else str(spec.path))
    image.drawWidth = draw_width
    image.drawHeight = draw_height
    return image


def inline_image(
    spec: ImageSpec | str | Path,
    width: float | None = None,
    height: float | None = None,
    scale: float | None = None,
    *,
    depth: float = 0.0,
) -> str:
    """The ``<img/>`` tag of an image set on the baseline, for a paragraph's markup.

    ``width``, ``height`` and ``scale`` are in points, as for :func:`load_image`;
    with both ``width`` and ``height`` given, the file is not even opened.
    ``depth`` is how far the image reaches below the baseline, in points: 0
    stands it on the baseline like a capital, the depth TeX reports for a
    formula puts the formula's own baseline on the line's.

    The style of the paragraph needs ``autoLeading="max"``, or a tall image
    overprints the line above; see :class:`~reportlab_layout.InlineParagraph`
    for the first line.
    """
    if width is None or height is None or scale is not None:
        if not isinstance(spec, ImageSpec):
            spec = image_spec(spec)
        width, height = spec.scaled(width=width, height=height, scale=scale)
    spec = image_spec(spec)
    if spec.path is None:
        raise ValueError(
            "inline_image needs an image on disk: a paragraph's <img/> tag takes a file name, "
            "not bytes. Write it to a file, or draw it with draw_image."
        )
    path = spec.path
    size = f'width="{width:.3f}" height="{height:.3f}"'
    return f'<img src={quoteattr(str(path))} {size} valign="{0.0 - depth:.3f}"/>'
