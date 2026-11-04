# 随测试分发的公开 mzML

这些文件只用于自动化测试，界面若导入它们会按文件内容显示，不会被标成合成数据。

## pymzml_example_qexactive_pos.mzML

- 来源：pymzML 仓库 `tests/data/example.mzML`（MIT 许可的项目示例）。
- 下载：https://raw.githubusercontent.com/pymzml/pymzML/master/tests/data/example.mzML
- 文件头：Thermo RAW（`exp105-01-ds5562-Pos.raw`），仪器词条 Q Exactive，Xcalibur 2.2，ProteoWizard 3.0.3768 转换并做了峰提取。
- 实际读到 11 张质心 MS1，全部为正离子，没有 MS/MS。保留时间约 0.0015–0.046 分钟。`spectrumList` 的 count 写成 2918，与文件里真实谱图数不一致，测试以实际读到的 11 张为准。
- 这是一段很短的示例，不能代表完整液相梯度。

## arabidopsis_waters_pos_ms1.mzML

- 来源：Zenodo 记录 8185092 的 `Col_1.mzML`，许可 Creative Commons Attribution 4.0。
  https://doi.org/10.5281/zenodo.8185092
- 文献：Sotelo-Silveira 等，Frontiers in Plant Science，2015，DOI 10.3389/fpls.2015.00365。拟南芥提取物的 LC-ESI-MS。
- 文件头：Waters raw 格式、Waters nativeID、MassLynx、仪器词条为笼统的 “Waters instrument model”（没有具体型号），ProteoWizard 转换。
- 实际读到 800 张质心 MS1，全部为正离子，没有 MS/MS。保留时间约 0.069–34.62 分钟。
