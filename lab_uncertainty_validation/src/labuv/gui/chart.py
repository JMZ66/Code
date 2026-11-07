"""Small bar chart drawn with Qt. No extra plotting package is required offline."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class BarChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._bars = []
        self.setMinimumHeight(160)

    def set_bars(self, bars):
        self._bars = list(bars)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f7f4ee"))
        painter.setPen(QColor("#243027"))
        if not self._bars:
            painter.drawText(self.rect(), Qt.AlignCenter, "没有可绘制的分量")
            painter.end()
            return
        width = self.width()
        height = self.height()
        top = 16
        bottom = height - 28
        span = max(bottom - top, 1)
        values = [abs(value) for _, value in self._bars]
        peak = max(values) or 1.0
        slot = width / max(len(self._bars), 1)
        for index, (name, value) in enumerate(self._bars):
            bar_height = int(span * (abs(value) / peak))
            left = int(index * slot + slot * 0.15)
            bar_width = int(slot * 0.7)
            color = QColor("#1f6f54") if value >= 0 else QColor("#9a3b2f")
            painter.fillRect(QRect(left, bottom - bar_height, bar_width, bar_height), color)
            painter.drawText(QRect(left - 4, bottom + 2, bar_width + 8, 22), Qt.AlignHCenter, str(name)[:8])
        painter.end()
