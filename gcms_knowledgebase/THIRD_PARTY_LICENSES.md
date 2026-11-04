# 第三方许可与再分发结论

结论先说：发布包里没有 Thermo RawFileReader，没有 ProteoWizard 的厂商 DLL，没有 MS-DIAL，也没有 AMDIS。需要它们的人在自己的电脑上安装，再在设置里填路径。

下面的判断基于 2026-11-04 能读到的上游许可证文本。许可文本以权利人原文为准。

## 不放进发布包

### Thermo RawFileReader，以及带上它的 ThermoRawFileParser

ThermoRawFileParser 仓库本身是 Apache-2.0。它的发行包同时带有 Thermo Fisher 的 RawFileReader。RawFileReader 的许可证（ProteoWizard 仓库中的 `EULA.Thermo.txt`，以及 ThermoRawFileParser 的 `THERMO_LICENSE`）写明：

- 可以在自己的程序一起分发，但要满足分发条件。
- 不得反编译或修改。
- 分发者要为 Thermo 抗辩并赔偿由此引起的索赔。
- 关于对话框要显示：`RawFileReader reading tool. Copyright © 2016 by Thermo Fisher Scientific, Inc. All rights reserved.`
- 必须要求最终用户同意一份禁止他们再分发该软件的协议。
- 未经 Thermo 事先书面同意，不得商业性利用该软件或包含它的产品。列举的情形包括收费，也包括为对价而许可、转让或再分发，并且写明不限于这些情形。
- 不得把它放进 GPL 这类要求披露源码或允许制作衍生作品的许可证组合里。

本程序要放在公开的 GitHub Release 上，供实验室使用。公开下载做不到“每个接收者先签一份禁止再分发的协议”，本仓库也不能替使用单位向 Thermo 承担赔偿。因此不把 ThermoRawFileParser 的二进制、RawFileReader DLL 或自包含 .NET 包放进发布包或仓库。

.NET 运行时本身可以再分发，挡路的是 RawFileReader，不是 .NET。用户如果自己从 CompOmics 发布页下载 ThermoRawFileParser 并接受其条款，可以在设置里指定路径。关于框始终写着上面的 Thermo 版权句，并说明本程序不附带该库、只有你自己安装并使用时这句话才和你的环境有关。

### ProteoWizard / msconvert

核心代码是 Apache-2.0。读取厂家格式依赖厂家库。Thermo 库的条款同上。ProteoWizard 安装包能带上这些库，是因为他们和厂家有单独安排，第三方不能把那些 DLL 拆出来再打包。本程序不附带 msconvert。用户可安装官方 ProteoWizard 后填写 `msconvert.exe`。

### MS-DIAL

源码仓库写明源码是 LGPL-3.0，官方程序集是 CC-BY-4.0。带厂家读取库的正式版不能因为源码是 LGPL 就整包再分发。GC-MS 控制台属于 MS-DIAL 4 这一支，调用方式是 `MsdialConsoleApp gcms -i 输入目录 -o 输出目录 -m 参数文件`。本程序可以按这个命令调用用户自己安装的程序，但不读取它的结果表，因为这里没有用公开样品核对过输出格式。

### AMDIS

NIST 网站提供 AMDIS，并另有 EULA（常见链接为 `EULA-AMDIS.pdf`）。NIST 网站上的一般软件声明不能代替这份 EULA。本程序不下载、不附带、不自动运行 AMDIS。设置里的路径只是记录。

## 放进发布包或源码依赖

直接依赖和本次环境中的版本：

| 组件 | 版本 | 许可证 | 用途 |
| --- | --- | --- | --- |
| PySide6 | 6.12.0 | LGPL-3.0-only 或 GPL-2.0-only 或 GPL-3.0-only | 界面。按 LGPL 使用 |
| Qt（随 PySide6） | 随 6.12.0 | LGPL-3.0 | 界面库 |
| numpy | 2.5.4 | BSD | 数组 |
| scipy | 1.16.3 | BSD | 找峰、Savitzky-Golay、nnls |
| pyteomics | 5.0.2 | Apache-2.0 | 读 mzML |
| psims | 1.4.0 | Apache-2.0 | pyteomics 5 的受控词表。使用它自带的 psi-ms.obo，不联网下载 |
| matchms | 0.33.1 | Apache-2.0 | 余弦相似度和 MSP 读写 |
| rdkit | 随 matchms 安装，本次 2026.9.1 | BSD-3-Clause | matchms 导入时会加载。本程序不用它算结构 |
| numba | 随 matchms | BSD | matchms 依赖 |
| openpyxl | 3.1.5 | MIT | Excel |
| reportlab | 5.1.0 | BSD | PDF |
| pyqtgraph | 0.14.0 | MIT | 色谱和质谱图 |
| 文泉驿微米黑 | 0.2.0-beta 的 TTC | Apache-2.0（上游是 Apache-2.0 或带字体例外的 GPL-3，本分发采用 Apache-2.0） | PDF 嵌入和界面 |
| PyInstaller | 6.22.3 | GPL-2.0-or-later，引导程序带有允许打包非 GPL 程序的例外 | 只在构建机使用，用来生成 exe |
| pytest、pytest-qt、pypdf | 见 pyproject | MIT / BSD | 只在测试里使用，不是运行依赖 |

matchms 还声明了 requests、pubchempy 等库。本程序的业务代码不调用它们，测试会扫描源码。它们仍会进运行环境，因为 matchms 的依赖关系如此。离线冒烟用防火墙看这个 exe 是否还要出站；结果以 CI 日志为准，不在这里提前写成“已经堵住”。

PySide6 / Qt 按 LGPL-3.0 遵守：

- 发布目录版而不是单文件，Qt 动态库可以替换。
- `licenses/LGPL-3.0.txt` 和 `licenses/GPL-3.0.txt` 随包提供。LGPL-3.0 是 GPL-3.0 的附加许可，所以两份都在。
- 关于框说明可以替换 Qt 库。

文泉驿的版权说明在 `src/gcms_kb/resources/fonts/WQY_COPYRIGHT.txt`。PDF 嵌入该字体。Excel 只写 Unicode 和字体名，不把字体嵌进 xlsx，因为这种嵌入在 Excel 里不可靠。这一点写在报告封面和测试里。

ProteoWizard 示例 `small.pwiz.1.1.mzML` 随测试数据和自检一起分发，来源和 Apache-2.0 说明在同目录的 `SOURCE.txt`。它不是 GC-MS 数据。

本目录的程序源码属于仓库 `JMZ66/Code`。这里不另加一个新的开源许可证去覆盖它。第三方组件仍按各自许可证使用。

Apache-2.0 全文在 `licenses/Apache-2.0.txt`。
