"""Bitmap images: reading their size and scaling them.

``reportlab.platypus.Image`` can load a file but will not preserve its aspect
ratio when given only one dimension. :class:`ImageSpec` reads the pixel size
once and works the other dimension out.
"""

from dataclasses import dataclass
from pathlib import Path

import PIL.Image as PILImage
from reportlab.platypus import Image

__all__ = ["ImageSpec", "image_spec", "load_image"]


@dataclass(frozen=True, slots=True)
class ImageSpec:
    """An image's path and its size in pixels."""

    path: Path
    width: int
    height: int

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


def image_spec(path: str | Path) -> ImageSpec:
    """Read the pixel size of the image at ``path``."""
    path = Path(path)
    with PILImage.open(path) as image:
        width, height = image.size
    return ImageSpec(path=path, width=width, height=height)


def load_image(
    spec: ImageSpec | str | Path,
    width: float | None = None,
    height: float | None = None,
    scale: float | None = None,
) -> Image:
    """Return an ``Image`` flowable sized in points.

    ``spec`` may be an :class:`ImageSpec` already read, or just a path.
    """
    if not isinstance(spec, ImageSpec):
        spec = image_spec(spec)
    draw_width, draw_height = spec.scaled(width=width, height=height, scale=scale)
    image = Image(str(spec.path))
    image.drawWidth = draw_width
    image.drawHeight = draw_height
    return image
