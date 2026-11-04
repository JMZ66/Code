#define AppVersion "1.0.0"

[Setup]
AppId={{8F3A1C2E-5B74-4D19-9A60-C3E8B1D24F70}
AppName=危化品仓库管理系统
AppVersion={#AppVersion}
AppPublisher=本单位自行部署
DefaultDirName={localappdata}\ChemWarehouse
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ChemWarehouse-{#AppVersion}-windows-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
InfoBeforeFile=DISCLAIMER.txt
UninstallDisplayIcon={app}\ChemWarehouse.exe
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "..\dist\ChemWarehouse\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\危化品仓库管理系统"; Filename: "{app}\ChemWarehouse.exe"
Name: "{userdesktop}\危化品仓库管理系统"; Filename: "{app}\ChemWarehouse.exe"

[UninstallDelete]
; 不删除 %USERPROFILE%\.chem_warehouse 。那里是正式台账。
Type: files; Name: "{app}\使用说明.txt"
