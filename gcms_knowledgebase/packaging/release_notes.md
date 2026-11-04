GCMS 谱图知识库 1.0.0

便携目录压成 `GCMS_KnowledgeBase-win64.zip`。解压后双击 `GCMS_KnowledgeBase.exe` 或 `启动GCMS知识库.bat`。不需要安装 Python。

这个发布由 GitHub Actions 的 `windows-latest` 生成。该环境是 Windows Server，不是 Windows 10/11 桌面。请在自己的 Win10/11 电脑上、断开外网后，用本实验室的 Xcalibur RAW 再确认一次。

本程序不附带 Thermo RawFileReader、msconvert、MS-DIAL 或 AMDIS。需要读 RAW 时，请自行安装 ThermoRawFileParser 或 ProteoWizard，并在软件设置里填写路径。转换结果写在本程序的数据目录，不改原始文件。

随附的公开 mzML 是 ProteoWizard 的 `small.pwiz.1.1.mzML`，滤镜字符串为 FTMS 正离子 ESI，不是 GC-MS EI。自检只用它证明能读入 mzML。

谱库分数一律标成“谱库候选（未确认）”。它不是化合物鉴定。
