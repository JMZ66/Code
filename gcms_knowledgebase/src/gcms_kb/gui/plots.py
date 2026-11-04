from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal


class ChromPlot(pg.PlotWidget):
    rtClicked = Signal(float)

    def __init__(self):
        super().__init__()
        self.setBackground("w")
        self.showGrid(x=True, y=True, alpha=0.25)
        self.setLabel("bottom", "保留时间", units="min")
        self.setLabel("left", "强度")
        self._line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#c2410c", width=1))
        self.addItem(self._line, ignoreBounds=True)
        self.scene().sigMouseClicked.connect(self._clicked)

    def set_curves(self, curves: list[tuple[np.ndarray, np.ndarray, object, str]]) -> None:
        for item in list(self.listDataItems()):
            self.removeItem(item)
        for x, y, pen, name in curves:
            self.plot(np.asarray(x, dtype=float), np.asarray(y, dtype=float), pen=pen, name=name)
        self.enableAutoRange()

    def mark(self, rt: float) -> None:
        self._line.setPos(float(rt))

    def _clicked(self, event) -> None:
        if not hasattr(event, "button"):
            return
        from PySide6.QtCore import Qt

        if event.button() != Qt.MouseButton.LeftButton:
            return
        position = event.scenePos()
        if not self.sceneBoundingRect().contains(position):
            return
        point = self.plotItem.vb.mapSceneToView(position)
        self.rtClicked.emit(float(point.x()))


class SpectrumPlot(pg.PlotWidget):
    def __init__(self):
        super().__init__()
        self.setBackground("w")
        self.showGrid(x=True, y=True, alpha=0.25)
        self.setLabel("bottom", "m/z")
        self.setLabel("left", "强度")

    def set_sticks(self, series: list[tuple[np.ndarray, np.ndarray, object]]) -> None:
        self.clear()
        for mz, intensity, pen in series:
            mz = np.asarray(mz, dtype=float)
            intensity = np.asarray(intensity, dtype=float)
            if mz.size == 0:
                continue
            xs = np.empty(mz.size * 3)
            ys = np.empty(mz.size * 3)
            xs[0::3] = mz
            xs[1::3] = mz
            xs[2::3] = np.nan
            ys[0::3] = 0
            ys[1::3] = intensity
            ys[2::3] = np.nan
            self.plot(xs, ys, pen=pen, connect="finite")
        self.enableAutoRange()
