"""Numérotation « page x sur y ».

Le nombre total de pages n'est connu qu'à la fin. :class:`NumberedCanvas`
mémorise l'état de chaque page, puis les rejoue une fois le total connu pour y
inscrire le folio.

D'après la recette ActiveState 546511, corrigée : la version qui circule ne
fonctionne qu'avec un ``DocTemplate``, qui termine toujours par un ``showPage``.
Utilisée directement comme canvas, elle perd silencieusement la dernière page.
"""

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

__all__ = ["NumberedCanvas"]


def _default_label(page: int, total: int) -> str:
    return f"Page {page} sur {total}"


class NumberedCanvas(canvas.Canvas):
    """Canvas qui inscrit un folio « page x sur y » sur chaque page.

    À passer en ``canvasmaker`` à ``SimpleDocTemplate.build``, ou à utiliser
    directement à la place de ``canvas.Canvas``::

        doc.build(story, canvasmaker=NumberedCanvas)

    La position, la police et le libellé se règlent par attributs de classe ou
    par sous-classe.
    """

    #: Position du folio, en points depuis le coin bas-gauche.
    folio_position: tuple[float, float] = (195 * mm, 10 * mm)
    folio_font: tuple[str, float] = ("Helvetica", 9)
    #: Fonction ``(page, total) -> str`` produisant le libellé.
    folio_label: Callable[[int, int], str] = staticmethod(_default_label)

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self) -> None:  # noqa: N802 - nom imposé par reportlab
        """Mémorise la page au lieu de l'écrire tout de suite."""
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        """Rejoue toutes les pages en y ajoutant le folio, puis écrit le fichier."""
        # Utilisé directement comme canvas — et non via un DocTemplate, qui
        # termine toujours par un showPage — la dernière page n'a pas été
        # mémorisée. `_code` non vide signale qu'il reste des tracés en attente.
        if self._code:
            self._saved_page_states.append(dict(self.__dict__))
        total = len(self._saved_page_states)
        for number, state in enumerate(self._saved_page_states, start=1):
            self.__dict__.update(state)
            self.draw_folio(number, total)
            super().showPage()
        self._saved_page_states.clear()
        super().save()

    def draw_folio(self, page: int, total: int) -> None:
        """Inscrit le folio. À surcharger pour changer la présentation."""
        self.setFont(*self.folio_font)
        self.drawRightString(*self.folio_position, type(self).folio_label(page, total))
