; Inno Setup script for CloakBrowser Manager. Run through build-installer.ps1:
;   ISCC.exe /DAppVersion=0.2.0 /DSourceDir=...\dist\CloakBrowser Manager /DOutputDir=... installer.iss
; Installs per user (no admin prompt). Uninstalling keeps profile data in
; %LOCALAPPDATA%\CloakBrowser Manager.

#define AppName "CloakBrowser Manager"
#define AppExe "CloakBrowser Manager.exe"

[Setup]
AppId={{6E0B7C1E-3F1B-4C8E-9C55-0C9E4B1A7D21}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=NorwayXZ
AppPublisherURL=https://github.com/NorwayXZ/CloakBrowser-Manager
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=CloakBrowser-Manager-{#AppVersion}-windows-x64-setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
; Simplified Chinese is not bundled with every Inno Setup 6 install; build-installer.ps1
; downloads it and passes /DChineseIsl=<path>. Without it the wizard is English.
#ifdef ChineseIsl
Name: "chinesesimplified"; MessagesFile: "{#ChineseIsl}"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\reg.exe"; Parameters: "delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v ""{#AppName}"" /f"; Flags: runhidden; RunOnceId: "RemoveStartup"
