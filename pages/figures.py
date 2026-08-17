"""
Shared matplotlib helpers for the page modules.

Tkinter and matplotlib need a small dance to embed a Figure in
a ttk.Frame: create the figure, wrap it in FigureCanvasTkAgg,
and pack the canvas's Tk widget. The setup is identical in
detail_page.py and ml_stats_page.py, so we factor it out here.

Typical use:

    from pages.figures import create_figure_in_frame

    def _build_chart(self, body):
        fig, ax, canvas = create_figure_in_frame(
            body, figsize=(8, 2.0),
        )
        self.line, = ax.plot([], [], label="LTP")

The returned (fig, ax, canvas) trio is what every page already
expects, so swapping `pages.figures.create_figure_in_frame` in
place of the in-line setup is a 3-line change per page.
"""
from typing import Tuple, Any, Optional


# Lazy matplotlib import — same trick the page modules use
# individually. matplotlib.figure + backend_tkagg cost ~270ms
# to import; we only pay that the first time a page actually
# needs a figure.
_Figure: Optional[type] = None
_FigureCanvasTkAgg: Optional[type] = None


def _ensure_matplotlib():
    """Lazily import matplotlib + the TkAgg backend. Returns
    (Figure, FigureCanvasTkAgg) on success."""
    global _Figure, _FigureCanvasTkAgg
    if _Figure is None:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure as _F
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg as _C
        _Figure = _F
        _FigureCanvasTkAgg = _C
    return _Figure, _FigureCanvasTkAgg


def create_figure_in_frame(
    parent: Any,
    figsize: Tuple[float, float] = (4, 3.2),
    dpi: int = 100,
    pack: bool = True,
) -> Tuple[Any, Any, Any]:
    """Create a matplotlib Figure, wrap it in a TkAgg canvas, and
    embed the canvas's Tk widget in `parent`.

    Parameters
    ----------
    parent : tkinter widget
        The ttk.Frame (or any Tk container) to host the figure.
        The figure's Tk widget is `pack()`ed into this frame
        (fill="both", expand=True) by default.
    figsize : (width, height) in inches
        The figure size. Default is 4×3.2 inches.
    dpi : int
        Resolution. Default 100. Higher = sharper on HiDPI
        screens but slower to draw.
    pack : bool
        If True (default), call .pack(fill="both", expand=True)
        on the canvas's Tk widget. Pass False if you want to
        grid() it manually.

    Returns
    -------
    (fig, ax, canvas) :
        fig    — the matplotlib.figure.Figure
        ax     — a single matplotlib.axes.Axes added to the figure
        canvas — the FigureCanvasTkAgg wrapping the figure. The
                 actual Tk widget is canvas.get_tk_widget().
    """
    Figure, FigureCanvasTkAgg = _ensure_matplotlib()
    fig = Figure(figsize=figsize, dpi=dpi)
    ax = fig.add_subplot(111)
    canvas = FigureCanvasTkAgg(fig, master=parent)
    if pack:
        canvas.get_tk_widget().pack(fill="both", expand=True)
    return fig, ax, canvas
