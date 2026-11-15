"""A flowable of your own, drawn with the package's painters.

A flowable that reportlab does not have -- a row of bars, a legend whose
entries are drawn shapes -- is written by subclassing ``Flowable``: ``wrap``
says how big it is, ``draw`` draws it on ``self.canv``. And there the bare
canvas is back, with what this package exists to spare: strings centred by
hand on ``0.35 × size``, a fill colour or a text render mode left behind for
the next call, ``drawImage`` and its readers.

:class:`PaintedFlowable` hands ``paint`` the same painters a document has --
``self.text``, ``self.shapes`` and :meth:`~PaintedFlowable.image` -- bound to
the flowable's own canvas, its origin at the flowable's lower-left corner.
Each call isolates its state and returns its :class:`~reportlab_layout.Box`,
as on a page. Sizing stays reportlab's: ``wrap`` is written as for any
flowable, and the metrics of :class:`~reportlab_layout.TextMetrics` measure
what it will hold.
"""

from reportlab.lib.styles import StyleSheet1
from reportlab.platypus import Flowable

from reportlab_layout.boxes import Box
from reportlab_layout.images import ImageLike, load_image
from reportlab_layout.shapes import ShapePainter
from reportlab_layout.text import TextPainter

__all__ = ["PaintedFlowable"]


class PaintedFlowable(Flowable):
    """A flowable drawn in :meth:`paint` with ``self.text``, ``self.shapes`` and ``self.image``.

    Subclass it, write ``wrap`` as for any flowable, and draw in ``paint``.
    The painters exist while ``paint`` runs; ``stylesheet``, at class or
    instance level, is the one ``self.text`` resolves style names against,
    reportlab_layout's shared sheet when left to ``None``.
    """

    stylesheet: StyleSheet1 | None = None
    text: TextPainter
    shapes: ShapePainter

    def draw(self) -> None:
        self.text = TextPainter(self.canv, self.stylesheet)
        self.shapes = ShapePainter(self.canv)
        self.paint()

    def paint(self) -> None:
        """Draw the flowable, in its own coordinates; override it."""
        raise NotImplementedError(f"{type(self).__name__} has to define paint()")

    def image(
        self,
        spec: ImageLike,
        x: float,
        y: float,
        width: float | None = None,
        height: float | None = None,
        scale: float | None = None,
    ) -> Box:
        """Draw an image, its lower-left corner at ``(x, y)``, sized as :func:`load_image` sizes it.

        A path, bytes, an open file or a Pillow image, transparency kept.
        """
        image = load_image(spec, width=width, height=height, scale=scale)
        image.drawOn(self.canv, x, y)
        return Box(x, y, image.drawWidth, image.drawHeight)
