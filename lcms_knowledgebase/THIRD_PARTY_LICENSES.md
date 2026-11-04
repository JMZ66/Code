# 第三方许可

本程序源码见 `LICENSE`（MIT）。下面是随程序运行或被明确排除的第三方组件。审计说明见 `docs/许可证审计.md`。

## 随程序分发

使用这些组件时需要保留它们各自的版权声明和许可文本。Apache-2.0 与 MIT 的全文可以从下列链接获得；发布压缩包若再分发这些库，应同时带上这些许可。

- pyteomics 5.0.2，Apache-2.0，https://github.com/levitsky/pyteomics/blob/master/LICENSE
- psims 1.4.0，Apache-2.0，https://github.com/mobiusklein/psims
- matchms 0.33.1，Apache-2.0，Copyright (c) Düsseldorf University of Applied Sciences & Netherlands eScience Center，https://github.com/matchms/matchms/blob/master/LICENSE
- NumPy、SciPy、pandas、scikit-learn、numba、lxml、RDKit：BSD 类许可，以各自安装包元数据为准
- matplotlib：Matplotlib License（BSD 风格）
- openpyxl 3.1.5，MIT
- ReportLab 5.1.0，BSD，Copyright ReportLab Inc.
- Pillow，MIT-CMU
- 文泉驿微米黑 0.2.0-beta：本程序按 Apache-2.0 使用（上游同时提供 GPL-3 加字体例外）。Copyright 2008-2009 WenQuanYi Project / Qianqian Fang，基于 Droid 字体
- PyInstaller 6.22.3：GPLv2-or-later，bootloader 有允许打包其他许可证程序的例外。只在构建机上使用，不要求用户安装

### PySide6 6.12.0 与 Qt

许可证：LGPL-3.0-only，或 GPL-2.0-only，或 GPL-3.0-only。本程序按 **LGPL-3.0-only** 使用未修改的官方二进制。

LGPL-3.0 全文：https://www.gnu.org/licenses/lgpl-3.0.html

Qt 源码按版本从 Qt 项目获取：https://download.qt.io/ 以及 https://code.qt.io/cgit/pyside/pyside-setup.git/

便携目录中的 Qt / Shiboken DLL 是独立文件。替换兼容的 LGPL 构建后，本程序不需要重新取得应用源码以外的许可。本仓库不附带完整 Qt 源码树。再分发本程序的人如果必须自己提供对应源码，请按所打包的 PySide6 版本另行提供。

本程序没有修改 Qt。

## 不随程序分发

这些组件即使用户实验室已经购买或安装，也不能从本发布包里得到：

- ProteoWizard msconvert 及其厂商 DLL（核心 Apache-2.0，厂商库另有协议）
- ThermoRawFileParser 以及其中的 Thermo RawFileReader（RawFileReader 禁止随意再分发，商业利用需要 Thermo 书面同意）
- MZmine（源码仓库为 MIT；官方安装包的学术/商业计划以 mzio 的现行说明为准）
- MS-DIAL / MsdialWorkbench（源码说明为 LGPL-3.0，另有与 CC-BY 4.0 不一致的表述；官方发布版含厂商库）
- pymzML（MIT，未作为依赖使用）

用户把自己安装的转换程序路径填进设置后，程序只会在本机调用它，不会把对方的文件复制进本程序目录。
