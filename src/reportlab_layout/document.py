"""Document PDF à curseur : assemble géométrie, curseur, styles et tracés.

:class:`PDFMaker` pilote un ``canvas`` reportlab avec un curseur qui descend
dans la page à mesure qu'on y dépose des éléments — le confort d'un document à
flux, sans renoncer au positionnement absolu quand on en a besoin.

Deux modes de placement cohabitent, et chaque méthode ``draw_*`` accepte les
deux :

* **flux** (défaut) : ni ``x`` ni ``y``, l'élément se pose sous le précédent et
  le curseur descend d'autant ;
* **absolu** (``absolute=True``) : ``x`` et ``y`` sont des coordonnées canvas en
  **points**, le curseur n'est pas touché.

Entre les deux, donner ``x`` et/ou ``y`` sans ``absolute`` les interprète en
``unit`` (millimètres par défaut), ``y`` étant une profondeur depuis le haut de
la page.
"""

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TypeAlias

from reportlab.lib.styles import StyleSheet1
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Flowable, Frame, Image, Paragraph, Spacer, Table, TableStyle

from reportlab_layout.boxes import Box
from reportlab_layout.colors import ColorLike, to_color
from reportlab_layout.cursor import Cursor
from reportlab_layout.frames import FrameWriter
from reportlab_layout.geometry import PageGeometry
from reportlab_layout.images import ImageSpec, load_image
from reportlab_layout.metrics import TextMetrics
from reportlab_layout.shapes import ShapePainter
from reportlab_layout.styles import STYLES, StyleLike, resolve_style
from reportlab_layout.text import TextPainter

__all__ = ["PDFMaker"]

logger = logging.getLogger(__name__)

TableCommand: TypeAlias = tuple[Any, ...]


class PDFMaker:
    """Un document PDF construit page à page, avec un curseur de flux.

    :param path: fichier de sortie.
    :param pagesize: nom (``"A4"``, ``"letter"``…) ou couple ``(largeur, hauteur)``
        en points.
    :param landscape: bascule le format en paysage.
    :param unit: unité des coordonnées passées aux méthodes ``draw_*``
        (``reportlab.lib.units.mm`` par défaut).
    :param left, right, top, bottom: marges, exprimées en ``unit``.
    :param font_size: corps de référence, utilisé par :meth:`add_space`.
    :param stylesheet: feuille de styles ; par défaut la feuille partagée
        :data:`reportlab_layout.styles.STYLES`.
    :param auto_page_break: saute à la page suivante quand un élément déborde de
        la marge basse.
    :param show_boundaries: trace la boîte de chaque élément posé — pour mettre
        au point une mise en page.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        pagesize: str | tuple[float, float] = "A4",
        landscape: bool = False,
        unit: float = mm,
        left: float = 15,
        right: float = 15,
        top: float = 15,
        bottom: float = 15,
        font_size: float = 12,
        stylesheet: StyleSheet1 | None = None,
        auto_page_break: bool = False,
        show_boundaries: bool = False,
    ) -> None:
        self.geometry = PageGeometry.build(
            pagesize=pagesize,
            landscape=landscape,
            unit=unit,
            left=left,
            right=right,
            top=top,
            bottom=bottom,
        )
        self.canvas = pdfcanvas.Canvas(str(path), pagesize=(self.geometry.width, self.geometry.height))
        self.unit = unit
        self.font_size = font_size
        self.stylesheet = stylesheet if stylesheet is not None else STYLES
        self.auto_page_break = auto_page_break
        self.show_boundaries = show_boundaries

        self.cursor = Cursor(self.geometry.margins.top, self.geometry.bottom_depth)
        self.shapes = ShapePainter(self.canvas)
        self.text = TextPainter(self.canvas, self.stylesheet)

        #: Hauteur ajoutée par :meth:`add_space` sans argument, en corps.
        self.default_space = 1.0
        self.header: list[Flowable] = []
        self.footer: list[Flowable] = []
        self.active_frame: Frame | None = None
        self.page = 1

        self._export_geometry()
        self.canvas.setFontSize(self.font_size)

    def _export_geometry(self) -> None:
        """Recopie les grandeurs de page en attributs, pour la lisibilité.

        Ce sont des instantanés modifiables, pas des propriétés : un document
        dérivé peut les ajuster sans que la géométrie de référence bouge.
        """
        geometry = self.geometry
        self.width = geometry.width
        self.height = geometry.height
        self.left = geometry.margins.left
        self.right = geometry.margins.right
        self.top = geometry.margins.top
        self.bottom = geometry.margins.bottom
        self.content_width = geometry.content_width
        self.content_height = geometry.content_height
        self.x_left = geometry.x_left
        self.x_right = geometry.x_right
        self.y_top = geometry.y_top
        self.y_bottom = geometry.y_bottom
        self.bottom_depth = geometry.bottom_depth

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def __enter__(self) -> "PDFMaker":
        return self

    def __exit__(self, exc_type: type | None, exc: BaseException | None, tb: object) -> None:
        if exc_type is None:
            self.save()

    def set_metadata(self, author: str = "", title: str = "", subject: str = "") -> None:
        """Renseigne les métadonnées du PDF."""
        self.canvas.setAuthor(author)
        self.canvas.setTitle(title)
        self.canvas.setSubject(subject)

    def new_page(self) -> int:
        """Termine la page courante — en-tête et pied compris — et en ouvre une neuve."""
        self.draw_header_footer()
        self.canvas.showPage()
        self.page += 1
        logger.debug("Nouvelle page [%d]", self.page)
        self.cursor.reset()
        return self.page

    def save(self) -> None:
        """Écrit l'en-tête et le pied de la dernière page, puis le fichier."""
        self.draw_header_footer()
        self.canvas.save()

    # ------------------------------------------------------------------
    # Curseur
    # ------------------------------------------------------------------
    @property
    def remaining_height(self) -> float:
        """Hauteur disponible sous le curseur, en points."""
        return self.cursor.remaining

    @property
    def cursor_y(self) -> float:
        """Ordonnée canvas de la position courante du curseur, en points."""
        return self.geometry.depth_to_y(self.cursor.depth)

    @property
    def cursor_point(self) -> tuple[float, float]:
        """Position courante du curseur en coordonnées canvas ``(x, y)``."""
        return (self.left, self.cursor_y)

    def reset_cursor(self) -> float:
        """Ramène le curseur en haut de la zone de contenu."""
        return self.cursor.reset()

    def advance(self, height: float) -> float:
        """Descend le curseur de ``height`` **points**."""
        return self.cursor.advance(height)

    def add_space(self, space: float | None = None) -> float:
        """Descend le curseur de ``space`` corps de référence."""
        if space is None:
            space = self.default_space
        return self.cursor.advance(space * self.font_size)

    # ------------------------------------------------------------------
    # Fabriques de flowables
    # ------------------------------------------------------------------
    def make_paragraph(self, text: str, style: StyleLike = None) -> Paragraph:
        """Construit un ``Paragraph`` avec le style demandé."""
        return Paragraph(text, style=resolve_style(style, self.stylesheet))

    def make_spacer(self, space: float = 1) -> Spacer:
        """Construit un ``Spacer`` de ``space`` corps de référence."""
        return Spacer(self.content_width, space * self.font_size)

    def make_table(
        self,
        data: list[list[object]],
        col_widths: float | list[float] | None = None,
        row_heights: float | list[float] | None = None,
    ) -> Table:
        """Construit un ``Table``.

        ``col_widths`` non fourni répartit la largeur de contenu à parts égales.
        Un scalaire s'applique à toutes les colonnes.
        """
        if not data or not data[0]:
            raise ValueError("Un tableau demande au moins une ligne non vide")
        columns = len(data[0])
        if col_widths is None:
            col_widths = [self.content_width / columns] * columns
        elif not isinstance(col_widths, list | tuple):
            col_widths = [col_widths] * columns
        return Table(data, colWidths=list(col_widths), rowHeights=row_heights)

    def make_image(
        self,
        spec: ImageSpec | str | Path,
        width: float | None = None,
        height: float | None = None,
        scale: float | None = None,
    ) -> Image:
        """Construit un flowable ``Image`` dimensionné en points."""
        return load_image(spec, width=width, height=height, scale=scale)

    # ------------------------------------------------------------------
    # Placement
    # ------------------------------------------------------------------
    def _wrap_size(self, width: float | None, height: float | None) -> tuple[float, float]:
        """Encombrement maximal proposé au flowable pour son calcul de retour à la ligne."""
        return (
            self.content_width if width is None else width,
            self.height if height is None else height,
        )

    def _anchor(
        self,
        x: float | None,
        y: float | None,
        height: float,
        before: float,
        space_before: float,
        halign: str,
        wscale: float,
    ) -> tuple[float, float]:
        """Coin bas-gauche, en points, d'un élément de hauteur ``height``.

        ``x`` et ``y`` sont en ``unit`` ; ``y`` est une profondeur depuis le haut
        de la page. ``None`` signifie « marge gauche » pour ``x`` et « position
        courante du curseur » pour ``y``.
        """
        x = self.left if x is None else x * self.unit
        free = (1 - wscale) * self.content_width
        if halign == "right":
            x += free
        elif halign == "center":
            x += free / 2
        elif halign != "left":
            raise ValueError(f"halign doit valoir 'left', 'center' ou 'right', reçu {halign!r}")
        depth = self.cursor.depth + before * self.unit if y is None else y * self.unit
        return x, self.geometry.depth_to_y(depth) - height - space_before

    def draw(
        self,
        flowable: Flowable,
        *,
        x: float | None = None,
        y: float | None = None,
        width: float | None = None,
        height: float | None = None,
        before: float = 0,
        absolute: bool = False,
        halign: str = "left",
        valign: str = "bottom",
        wscale: float = 1.0,
        page_break: bool | None = None,
        show_boundary: bool | None = None,
    ) -> Box:
        """Pose un flowable et rend la boîte qu'il occupe.

        Le curseur ne descend que si l'élément a été posé en flux, c'est-à-dire
        si ``y`` vaut ``None`` et ``absolute`` est faux.

        ``valign`` ne s'applique qu'en mode absolu et dit ce que désigne ``y`` :
        le bas de l'élément (``"bottom"``, défaut), son milieu (``"middle"``) ou
        son sommet (``"top"``).

        ``page_break`` à ``None`` suit le réglage ``auto_page_break`` du
        document ; ``True`` ou ``False`` le forcent pour cet appel.
        """
        flow = y is None and not absolute
        allow_break = self.auto_page_break if page_break is None else page_break

        box = self._place(flowable, x, y, width, height, before, absolute, halign, valign, wscale)
        if flow and allow_break and box.y < self.bottom:
            self.new_page()
            box = self._place(flowable, x, y, width, height, before, absolute, halign, valign, wscale)

        flowable.drawOn(self.canvas, box.x, box.y)
        outline = self.show_boundaries if show_boundary is None else show_boundary
        if outline:
            self.shapes.rect(*box)
        if flow:
            self.cursor.advance(
                box.height + before * self.unit + flowable.getSpaceBefore() + flowable.getSpaceAfter()
            )
        return box

    def _place(
        self,
        flowable: Flowable,
        x: float | None,
        y: float | None,
        width: float | None,
        height: float | None,
        before: float,
        absolute: bool,
        halign: str,
        valign: str,
        wscale: float,
    ) -> Box:
        """Calcule la boîte d'un flowable sans le dessiner."""
        wrap_width, wrap_height = self._wrap_size(width, height)
        actual_width, actual_height = flowable.wrapOn(self.canvas, wrap_width, wrap_height)
        if absolute:
            if x is None or y is None:
                raise ValueError("absolute=True demande x et y explicites, en points")
            offset = {"bottom": 0.0, "middle": actual_height / 2, "top": actual_height}[valign]
            return Box(x, y - offset, actual_width, actual_height)
        anchor_x, anchor_y = self._anchor(
            x, y, actual_height, before, flowable.getSpaceBefore(), halign, wscale
        )
        return Box(anchor_x, anchor_y, actual_width, actual_height)

    # ------------------------------------------------------------------
    # Tracés à flux
    # ------------------------------------------------------------------
    def draw_paragraph(self, text: str, style: StyleLike = None, **kwargs: Any) -> Box:
        """Pose un paragraphe. Les mots-clés sont ceux de :meth:`draw`."""
        return self.draw(self.make_paragraph(text, style), **kwargs)

    def draw_table(
        self,
        data: list[list[object]],
        col_widths: float | list[float] | None = None,
        row_heights: float | list[float] | None = None,
        style: Iterable[TableCommand] | TableStyle | None = None,
        **kwargs: Any,
    ) -> Box:
        """Pose un tableau.

        ``style`` est une suite de commandes reportlab
        (``("GRID", (0, 0), (-1, -1), 0.5, colors.black)``) ou un ``TableStyle``
        déjà construit. Par défaut, les cellules sont centrées verticalement.
        """
        table = self.make_table(data, col_widths=col_widths, row_heights=row_heights)
        if style is None:
            style = [("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
        table.setStyle(style if isinstance(style, TableStyle) else TableStyle(list(style)))
        return self.draw(table, **kwargs)

    def draw_image(
        self,
        spec: ImageSpec | str | Path,
        width: float | None = None,
        height: float | None = None,
        scale: float | None = None,
        **kwargs: Any,
    ) -> Box:
        """Pose une image. ``width``, ``height`` et ``scale`` sont en points."""
        return self.draw(self.make_image(spec, width=width, height=height, scale=scale), **kwargs)

    def draw_centered_line(self, y: float | None = None, wscale: float = 1.0, **kwargs: Any) -> Box:
        """Trace un filet horizontal centré sur la largeur de contenu.

        ``y`` est une profondeur en ``unit`` ; sans ``y``, le filet se place à la
        position du curseur, qui descend ensuite d'un espacement.
        """
        if y is None:
            depth = self.cursor.depth - self.font_size / 2
            self.add_space()
        else:
            depth = y * self.unit
        line_y = self.geometry.depth_to_y(depth)
        x1 = self.left + (1 - wscale) * self.content_width / 2
        return self.shapes.line(x1, line_y, x1 + wscale * self.content_width, line_y, **kwargs)

    # ------------------------------------------------------------------
    # En-tête et pied de page
    # ------------------------------------------------------------------
    def set_header(self, content: Flowable | Iterable[Flowable] | None) -> None:
        """Fixe l'en-tête redessiné sur chaque page."""
        self.header = self._as_flowables(content)

    def set_footer(self, content: Flowable | Iterable[Flowable] | None) -> None:
        """Fixe le pied de page redessiné sur chaque page."""
        self.footer = self._as_flowables(content)

    @staticmethod
    def _as_flowables(content: Flowable | Iterable[Flowable] | None) -> list[Flowable]:
        if content is None:
            return []
        if isinstance(content, Flowable):
            return [content]
        return list(content)

    def draw_header_footer(self) -> None:
        """Dessine en-tête et pied sur la page courante.

        Appelée automatiquement par :meth:`new_page` et :meth:`save`.
        """
        for flowable in self._as_flowables(self.footer):
            self.draw(flowable, y=self.bottom_depth / self.unit, page_break=False)
        for flowable in self._as_flowables(self.header):
            self.draw(flowable, y=self.top / self.unit, page_break=False)

    # ------------------------------------------------------------------
    # Frames
    # ------------------------------------------------------------------
    def new_frame(
        self,
        x: float | None = None,
        y: float | None = None,
        height: float | None = None,
        wscale: float = 1.0,
        before: float = 0,
        halign: str = "left",
        show_boundary: bool = False,
    ) -> Frame:
        """Ouvre un frame à la position du curseur et l'y fait descendre.

        ``height`` est en points ; sans valeur, il vaut un corps de référence.
        """
        if height is None:
            height = self.font_size
        anchor_x, anchor_y = self._anchor(x, y, height, before, 0, halign, wscale)
        logger.debug("Nouveau frame en (%.1f, %.1f)", anchor_x, anchor_y)
        self.active_frame = Frame(
            anchor_x, anchor_y, wscale * self.content_width, height, showBoundary=show_boundary
        )
        self.cursor.advance(height + before * self.unit)
        return self.active_frame

    def draw_frame(self, story: list[Flowable], space: float = 0) -> list[Flowable]:
        """Écrit ``story`` dans le frame courant et rend ce qui n'a pas tenu."""
        if self.active_frame is None:
            raise RuntimeError("Aucun frame actif : appeler new_frame() d'abord")
        if space > 0:
            story = [*story, self.make_spacer(space)]
        return FrameWriter(self.canvas, self.active_frame).write(story)

    def frame_paragraph(self, text: str, style: StyleLike = None, space: float = 0) -> list[Flowable]:
        """Écrit un paragraphe dans le frame courant."""
        return self.draw_frame([self.make_paragraph(text, style)], space)

    def frame_space(self, space: float = 1) -> list[Flowable]:
        """Ajoute un espacement dans le frame courant."""
        return self.draw_frame([], space)

    def frame_image(
        self,
        spec: ImageSpec | str | Path,
        width: float = 50 * mm,
        space: float = 0,
        halign: str = "CENTER",
    ) -> list[Flowable]:
        """Écrit une image dans le frame courant. ``width`` est en points."""
        image = self.make_image(spec, width=width)
        image.hAlign = halign
        return self.draw_frame([image], space)

    # ------------------------------------------------------------------
    # Tracés directs
    # ------------------------------------------------------------------
    def metrics(self, style: StyleLike = None, scale: float = 1.0) -> TextMetrics:
        """Métriques du style demandé, à l'échelle demandée."""
        return TextMetrics(resolve_style(style, self.stylesheet), scale)

    def apply_style(
        self, style: StyleLike = None, scale: float = 1.0, color: ColorLike = None
    ) -> TextMetrics:
        """Arme la police et la couleur du canvas pour un tracé direct.

        Utile avant d'appeler soi-même ``document.canvas.drawString``. Les
        méthodes ``draw_string*`` le font déjà.
        """
        metrics = self.metrics(style, scale)
        self.canvas.setFont(metrics.font_name, metrics.font_size)
        if color is not None:
            self.canvas.setFillColor(to_color(color))
        return metrics

    def draw_string(self, text: str, x: float, y: float, **kwargs: Any) -> Box:
        """Trace une chaîne ancrée en ``(x, y)``, coordonnées canvas en points.

        Mots-clés : ``style``, ``scale``, ``color``, ``halign``
        (``left``/``center``/``right``), ``valign``
        (``baseline``/``middle``/``cap``/``top``/``bottom``), ``angle``, ``dx``,
        ``dy``.
        Voir :meth:`reportlab_layout.text.TextPainter.draw`.
        """
        return self.text.draw(text, x, y, **kwargs)

    def draw_line(self, x1: float, y1: float, x2: float, y2: float, **kwargs: Any) -> Box:
        """Trace un segment, coordonnées canvas en points."""
        return self.shapes.line(x1, y1, x2, y2, **kwargs)

    def draw_rect(self, x: float, y: float, width: float, height: float, **kwargs: Any) -> Box:
        """Trace un rectangle, coordonnées canvas en points."""
        return self.shapes.rect(x, y, width, height, **kwargs)

    def draw_round_rect(self, x: float, y: float, width: float, height: float, **kwargs: Any) -> Box:
        """Trace un rectangle à coins arrondis, coordonnées canvas en points."""
        return self.shapes.round_rect(x, y, width, height, **kwargs)
