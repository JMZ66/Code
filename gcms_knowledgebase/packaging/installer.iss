; 可选安装包。需要本机已安装 Inno Setup 6。便携 zip 不依赖本脚本。
#define MyAppName "GCMS 谱图知识库"
#define MyAppVersion "1.0.0"
#define MyAppExe "GCMS_KnowledgeBase.exe"

[Setup]
AppId={{7C2A9E1B-4F63-4A1E-9C55-2B8E6D0A1F44}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\GCMS_KnowledgeBase
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=GCMS_KnowledgeBase_Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Files]
Source: "..\dist\GCMS_KnowledgeBase\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
