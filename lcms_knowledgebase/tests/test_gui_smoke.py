"""离屏界面冒烟：导入、绘图和理论质量，不把合成数据说成采集谱。"""

from PySide6.QtCore import Qt

from lcms_kb.ui.main_window import MainWindow
from tests.synthetic_mzml import write_synthetic_mzml


def test_gui_import_plot_and_mass(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("LCMS_KB_HOME", str(tmp_path / "home"))
    window = MainWindow()
    qtbot.addWidget(window)
    path = write_synthetic_mzml(tmp_path / "synthetic.mzML")
    window.queue_file(path, sample_name="合成样品", sample_type="sample")
    qtbot.mouseClick(window.import_button, Qt.LeftButton)
    assert window.dataset_count() == 1
    assert "测试用合成数据" in window.dataset_table.item(0, 5).text()
    assert "不是采集" in window.import_log.toPlainText() or "测试用合成" in window.import_log.toPlainText()

    window.nav.setCurrentRow(1)
    window.chroma_list.item(0).setSelected(True)
    plot_button = window.findChild(type(window.import_button), "plotChroma")
    qtbot.mouseClick(plot_button, Qt.LeftButton)
    assert window.chroma_plot.axes.lines

    window.nav.setCurrentRow(3)
    window.formula_edit.setText("C8H10N4O2")
    qtbot.mouseClick(window.mass_button, Qt.LeftButton)
    text = window.mass_output.toPlainText()
    assert "理论 m/z" in text
    assert "不是鉴定" in text
    assert "谱库候选（未确认）" in window.findChild(type(window.spectrum_info), "layerBanner").text()
    window.close()
