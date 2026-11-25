#define Publisher "Guilherme Paicheco Ferreira"

[Setup]
AppId=SpotiFlying.GuiPaicheco.Desktop
AppName=SpotiFlying
AppVersion=1.0.1
AppPublisher={#Publisher}
AppPublisherURL=https://guipaicheco.github.io/SpotiFlying/
AppSupportURL=https://github.com/GuiPaicheco/SpotiFlying/issues
AppUpdatesURL=https://github.com/GuiPaicheco/SpotiFlying/releases
VersionInfoDescription=Instalador do SpotiFlying
VersionInfoVersion=1.0.1
DefaultDirName={localappdata}\Programs\SpotiFlying
DefaultGroupName=SpotiFlying
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\release
OutputBaseFilename=SpotiFlying-Setup-x64
SetupIconFile=..\src\spotiflying\assets\spotiflying.ico
UninstallDisplayIcon={app}\SpotiFlying.exe
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked
[Files]
Source: "..\dist\SpotiFlying\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\SpotiFlying"; Filename: "{app}\SpotiFlying.exe"; Comment: "Desenvolvido por {#Publisher}"
Name: "{autodesktop}\SpotiFlying"; Filename: "{app}\SpotiFlying.exe"; Comment: "Desenvolvido por {#Publisher}"; Tasks: desktopicon
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "SpotiFlying"; Flags: dontcreatekey uninsdeletevalue
[Run]
Filename: "{app}\SpotiFlying.exe"; Description: "{cm:LaunchProgram,SpotiFlying}"; Flags: nowait postinstall skipifsilent
