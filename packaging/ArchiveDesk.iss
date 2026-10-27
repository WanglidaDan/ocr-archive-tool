; ArchiveDesk offline installer.
; The staged directory must already contain ArchiveDesk.exe.
; standard_template.xlsx is included only when that file is already in the stage.
; The GitHub base package does not contain it.

#ifndef DistDir
  #define DistDir "..\dist\ArchiveDesk"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

#define MyAppName "档序 ArchiveDesk"
#define MyAppVersion "0.3"
#define MyAppExeName "ArchiveDesk.exe"

[Setup]
AppId={{8F4E2C1A-6B3D-4E90-9A17-5D2C8B0E4F63}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\ArchiveDesk
DefaultGroupName=档序 ArchiveDesk
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=ArchiveDesk-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\档序 ArchiveDesk"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autoprograms}\档序 ArchiveDesk"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动档序 ArchiveDesk"; Flags: nowait postinstall skipifsilent
