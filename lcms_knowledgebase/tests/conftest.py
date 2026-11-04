"""测试公共设置。界面测试使用离屏 Qt。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lcms_kb.offline import enforce_offline_ontology

enforce_offline_ontology()
