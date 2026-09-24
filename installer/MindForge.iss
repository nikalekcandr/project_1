; Инсталлятор MindForge (Inno Setup 6).
; Сборка: ISCC /DAppVersion=1.0.0 installer\MindForge.iss  (после pyinstaller с MINDFORGE_ONEDIR=1)

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8E3C6F2A-4B7D-4E0B-9C51-5D2F1A7B9E34}
AppName=MindForge
AppVersion={#AppVersion}
AppVerName=MindForge {#AppVersion}
AppPublisher=MindForge
DefaultDirName={localappdata}\Programs\MindForge
DefaultGroupName=MindForge
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=MindForge-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\MindForge.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\MindForge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MindForge"; Filename: "{app}\MindForge.exe"
Name: "{group}\{cm:UninstallProgram,MindForge}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MindForge"; Filename: "{app}\MindForge.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MindForge.exe"; Description: "{cm:LaunchProgram,MindForge}"; Flags: nowait postinstall skipifsilent
