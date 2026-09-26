"""Columns: a story flowed over several columns, page after page, level on the last.

platypus sets columns with a page template of frames, which takes the whole page
over. :meth:`~reportlab_layout.PDFMaker.draw_columns` keeps the cursor instead:
the columns start where it stands, fill the rest of the page, carry on over new
pages -- header and footer drawn as usual --, and on the page where the story
ends they are balanced, as LaTeX's ``multicols`` does: the lowest height at which
the rest of the story still fits, so the columns end level rather than one full
and one short. The cursor then moves under them, and the flow carries on across
the full width.

The balanced height is found by trying heights, a dozen times or so. The packing
only wraps and splits flowables: nothing is drawn while trying, so an image is
not loaded a dozen times, and the drawing uses the very same packing.

Between flowables, space before and after is kept as a frame keeps it: none at
the top of a column, and none counted at its bottom. A ``FrameBreak`` in the
story ends its column, as in platypus; a ``KeepTogether`` moves its content to
the next column when it does not fit in what is left of this one. A flowable
whose style asks ``keepWithNext`` -- a heading -- is kept with the next one, as
a ``SimpleDocTemplate`` keeps it: platypus does that in the document template,
which the columns do without, so they group such runs themselves.

A flowable that cannot split and is taller than a whole column is laid down
anyway, overflowing its column, and reported in the log: it is neither lost nor
sent into an endless loop.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, KeepTogether
from reportlab.platypus.doctemplate import ActionFlowable

__all__ = ["Packing", "Placement", "balanced_height", "keep_with_next", "pack_columns"]

logger = logging.getLogger(__name__)

#: Room, in points, below which nothing is tried: rounding, not space.
_FUZZ = 1e-6
#: How close to the lowest height the balancing gets, in points.
_BALANCE_PRECISION = 0.5
#: A column taller than any story, to measure one in a single column.
_UNBOUNDED = 1e7


@dataclass(frozen=True, slots=True)
class Placement:
    """Where a flowable lands: its column, and the depth of its top below the columns' top."""

    flowable: Flowable
    column: int
    top: float
    width: float
    height: float

    @property
    def bottom(self) -> float:
        return self.top + self.height


@dataclass(frozen=True, slots=True)
class Packing:
    """What fits in the columns, and what is left for the next page.

    ``height`` is the depth reached by the lowest flowable, its space after left
    out.
    """

    placements: tuple[Placement, ...]
    rest: tuple[Flowable, ...]
    height: float


def _is_column_break(flowable: Flowable) -> bool:
    action: tuple[object, ...] = tuple(getattr(flowable, "action", ()))
    return action[:1] == ("frameEnd",)


def pack_columns(
    canvas: Canvas,
    story: Sequence[Flowable],
    width: float,
    height: float,
    columns: int,
    *,
    overflow: bool = False,
) -> Packing:
    """Lay ``story`` into ``columns`` columns ``width`` wide and ``height`` tall.

    Nothing is drawn: the flowables are wrapped, and split where a column ends.
    With ``overflow``, a flowable that cannot split and does not fit an empty
    column is laid down anyway, overflowing it: meant for columns as tall as the
    page, where waiting for more room would never end.
    """
    queue = keep_with_next(story)
    placements: list[Placement] = []
    for column in range(columns):
        depth = 0.0
        at_top = True
        while queue:
            head = queue[0]
            if isinstance(head, ActionFlowable):
                queue.pop(0)
                if _is_column_break(head):
                    break
                continue
            space = 0.0 if at_top else head.getSpaceBefore()
            room = height - depth - space
            if room <= _FUZZ and not at_top:
                break
            head_width, head_height = head.wrapOn(canvas, width, room)
            if head_height <= room + _FUZZ:
                placements.append(Placement(head, column, depth + space, head_width, head_height))
                depth += space + head_height + head.getSpaceAfter()
                at_top = False
                queue.pop(0)
                continue
            parts = head.splitOn(canvas, width, room) if room > _FUZZ else []
            if at_top:
                # A KeepTogether too tall for the column asks for a break first: at the
                # top of a column, that would only leave the column empty.
                while parts and isinstance(parts[0], ActionFlowable):
                    parts.pop(0)
            if len(parts) > 1 and _fits(canvas, parts[0], width, room):
                queue[0:1] = parts
                continue
            if at_top and overflow:
                # A failed split can leave the flowable unwrapped (Paragraph drops its lines).
                head_width, head_height = head.wrapOn(canvas, width, height)
                logger.warning(
                    "%s is %.1f pt tall and cannot split: it overflows a %.1f pt column",
                    type(head).__name__,
                    head_height,
                    height,
                )
                placements.append(Placement(head, column, 0.0, head_width, head_height))
                queue.pop(0)
            break
    reached = max((placement.bottom for placement in placements), default=0.0)
    return Packing(tuple(placements), tuple(queue), reached)


def keep_with_next(story: Sequence[Flowable]) -> list[Flowable]:
    """The story with each run of ``keepWithNext`` flowables bound to the next one.

    Each run and the flowable after it become one ``KeepTogether``, as
    ``BaseDocTemplate.handle_keepWithNext`` makes them: a heading never ends a
    column with its text in the next one, unless the whole group is taller than
    a column.
    """
    grouped: list[Flowable] = []
    run: list[Flowable] = []
    for flowable in story:
        run.append(flowable)
        if isinstance(flowable, ActionFlowable) or not flowable.getKeepWithNext():
            grouped.append(run[0] if len(run) == 1 else KeepTogether(run))
            run = []
    if run:
        grouped.append(run[0] if len(run) == 1 else KeepTogether(run))
    return grouped


def _fits(canvas: Canvas, flowable: Flowable, width: float, room: float) -> bool:
    """Whether the first piece of a split fits; an action, such as a column break, always does."""
    if isinstance(flowable, ActionFlowable):
        return True
    return bool(flowable.wrapOn(canvas, width, room)[1] <= room + _FUZZ)


def balanced_height(
    canvas: Canvas, story: Sequence[Flowable], width: float, height: float, columns: int
) -> float:
    """The lowest height, up to ``height``, at which ``story`` fits in the columns.

    ``story`` must fit at ``height``. The search starts from the height the
    story takes in a single column, divided among the columns: no packing can do
    better. That height is measured by packing, not by adding up the flowables'
    heights: a ``KeepTogether`` gives 16777215 on purpose, to be split.
    """
    single = pack_columns(canvas, story, width, _UNBOUNDED, 1).height
    fits, fails = height, min(height, single / columns) - _BALANCE_PRECISION
    while fits - fails > _BALANCE_PRECISION:
        trial = (fits + fails) / 2
        if pack_columns(canvas, story, width, trial, columns).rest:
            fails = trial
        else:
            fits = trial
    return fits
