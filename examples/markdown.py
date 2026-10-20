"""A worked solution written in Markdown, its formulas typeset by LaTeX, set in a PDF.

    uv run --extra markdown --extra texformules --extra pdf python examples/markdown.py

Writes ``markdown.pdf`` into the current directory. The text is the kind a site
shows with markdown-it and KaTeX; here texformules typesets its formulas with a
real LaTeX, all of them in one compilation, and they go on the page as vector
drawing: in the line, on the baseline, or displayed, a label flush right. One
formula is wrong on purpose: it is written as it stands, and the reason is
printed. It takes a TeX distribution on the PATH; the second run is served by
texformules' cache.
"""

from reportlab_layout import PDFMaker, make_stylesheet
from reportlab_layout.texmath import TexFormulas

TEXT = r"""
# A ball dropped from a height $h$

A ball of mass $m$ is dropped without speed from a height $h = \SI{10}{m}$. Air
resistance is neglected, and the field of gravity is uniform, $g = \SI{9.8}{m.s^{-2}}$.

## 1. Its speed on landing

The only force on the ball is its weight, $\vec P = m\vec g$, which derives from the
potential energy $E_p = mgz$. The mechanical energy is conserved:

$$
\frac{1}{2} m v^2 + m g z = m g h
$$ (1)

hence, at $z = 0$, $v = \sqrt{2gh} \approx \SI{14}{m.s^{-1}}$: **the mass does not
come into it**.

## 2. The time of the fall

The acceleration is constant, so $z(t) = h - \frac{1}{2} g t^2$, and the ball lands at

$$t_0 = \sqrt{\frac{2h}{g}} \approx \SI{1.4}{s}.$$

| Height $h$ | Speed $v$ | Time $t_0$ |
|---:|---:|---:|
| 5 m | 9.9 m/s | 1.0 s |
| 10 m | 14 m/s | 1.4 s |
| 20 m | 20 m/s | 2.0 s |

> Dropped from twice as high, the ball does **not** land twice as fast: $v$ grows
> as $\sqrt{h}$, by a factor $\sqrt 2 \approx 1.41$.

## Common slips

- Writing the energy without its potential term, $E = \frac12 mv^2$.
- Forgetting the square root:
  1. $v = 2gh$ is not even a speed, its unit is $\mathrm{m^2\,s^{-2}}$;
  2. a check of the units finds it at once.
- A formula left open, $\frac{1}{2$, is written as it stands.
"""


def main() -> None:
    formulas = TexFormulas()  # amsmath, amssymb and siunitx; preamble= for your own
    with PDFMaker("markdown.pdf", stylesheet=make_stylesheet(), top=20, bottom=20) as doc:
        doc.draw_markdown(TEXT, formulas=formulas)
    for problem in doc.markdown_problems:
        print(f"{problem.kind} {problem.source}: {problem.message}")


if __name__ == "__main__":
    main()
