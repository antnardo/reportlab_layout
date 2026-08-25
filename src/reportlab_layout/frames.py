"""Écriture dans un ``Frame`` reportlab.

Un frame est une boîte à hauteur fixe que l'on remplit de flowables : reportlab
gère le retour à la ligne et arrête d'écrire quand la boîte est pleine. Utile
pour un encadré, un chapeau, une colonne. Ce qui n'a pas tenu est signalé au
lieu de disparaître en silence.
"""

import logging

from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, Frame

__all__ = ["FrameWriter"]

logger = logging.getLogger(__name__)


class FrameWriter:
    """Remplit un ``Frame`` et rapporte le débordement."""

    def __init__(self, canvas: Canvas, frame: Frame) -> None:
        self._canvas = canvas
        self.frame = frame

    def write(self, story: list[Flowable]) -> list[Flowable]:
        """Écrit ``story`` dans le frame et rend les flowables qui n'ont pas tenu.

        La liste passée est consommée par reportlab : ce qui reste dedans après
        l'appel est exactement ce qui a débordé.
        """
        remaining = list(story)
        self.frame.addFromList(remaining, self._canvas)
        if remaining:
            logger.warning("Frame plein : %d élément(s) non inclus", len(remaining))
        return remaining
