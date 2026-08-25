"""Images bitmap : lecture des dimensions et mise à l'échelle.

``reportlab.platypus.Image`` sait charger un fichier mais pas conserver son
rapport d'aspect si on ne lui donne qu'une dimension. :class:`ImageSpec` lit la
taille en pixels une fois pour toutes et calcule l'autre dimension.
"""

from dataclasses import dataclass
from pathlib import Path

import PIL.Image as PILImage
from reportlab.platypus import Image

__all__ = ["ImageSpec", "image_spec", "load_image"]


@dataclass(frozen=True, slots=True)
class ImageSpec:
    """Chemin d'une image et ses dimensions en pixels."""

    path: Path
    width: int
    height: int

    @property
    def aspect(self) -> float:
        """Rapport hauteur / largeur."""
        return self.height / self.width

    def scaled(
        self,
        width: float | None = None,
        height: float | None = None,
        scale: float | None = None,
    ) -> tuple[float, float]:
        """Dimensions de tracé en points, à partir d'une seule contrainte.

        Exactement une des trois contraintes doit être fournie — sauf si
        ``width`` et ``height`` sont données ensemble, auquel cas le rapport
        d'aspect n'est pas conservé, ce qui est parfois voulu.
        """
        if scale is not None:
            if width is not None or height is not None:
                raise ValueError("scale est exclusif de width et height")
            return self.width * scale, self.height * scale
        if width is not None and height is not None:
            return float(width), float(height)
        if width is not None:
            return float(width), width * self.aspect
        if height is not None:
            return height / self.aspect, float(height)
        raise ValueError("Fournir width, height ou scale")


def image_spec(path: str | Path) -> ImageSpec:
    """Lit les dimensions en pixels de l'image ``path``."""
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
    """Rend un flowable ``Image`` dimensionné en points.

    ``spec`` peut être un :class:`ImageSpec` déjà lu ou un simple chemin.
    """
    if not isinstance(spec, ImageSpec):
        spec = image_spec(spec)
    draw_width, draw_height = spec.scaled(width=width, height=height, scale=scale)
    image = Image(str(spec.path))
    image.drawWidth = draw_width
    image.drawHeight = draw_height
    return image
