; Inno Setup script for BlenderQueue.
; Built by build.py, which passes MyAppVersion in and expects dist\BlenderQueue\
; to already contain a PyInstaller one-folder build.
;
; Installs per-user into %LOCALAPPDATA%\Programs so no administrator rights are
; needed; PrivilegesRequiredOverridesAllowed lets someone choose a machine-wide
; install if they run it elevated.

#ifndef MyAppVersion
  #define MyAppVersion "1.1.0"
#endif

#define MyAppName "BlenderQueue"
#define MyAppExeName "BlenderQueue.exe"
#define MyAppPublisher "BlenderQueue"

[Setup]
AppId={{7C4B5B2E-4C4E-4E9E-9D2A-7B1F0A3C9E51}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename=BlenderQueue-{#MyAppVersion}-Setup
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
MinVersion=10.0
AppSupportURL=https://www.blender.org
DisableDirPage=no
CloseApplications=yes
CloseApplicationsFilter=*.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "assocqueue"; Description: "Open &.bqueue queue files with {#MyAppName}"; GroupDescription: "File associations:"

[Files]
; The whole PyInstaller one-folder build, minus the portable marker.
Source: "dist\BlenderQueue\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\BlenderQueue\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.bqueue"; ValueType: string; ValueName: ""; ValueData: "BlenderQueue.Queue"; Flags: uninsdeletevalue; Tasks: assocqueue
Root: HKA; Subkey: "Software\Classes\BlenderQueue.Queue"; ValueType: string; ValueName: ""; ValueData: "BlenderQueue render queue"; Flags: uninsdeletekey; Tasks: assocqueue
Root: HKA; Subkey: "Software\Classes\BlenderQueue.Queue\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: assocqueue
Root: HKA; Subkey: "Software\Classes\BlenderQueue.Queue\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: assocqueue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Settings and the autosaved queue live in %APPDATA%; leave them unless the
; user asks, which the uninstaller prompt below handles.
Type: filesandordirs; Name: "{app}\_internal"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
  Prompt: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\BlenderQueue');
    if DirExists(DataDir) then
    begin
      // SuppressibleMsgBox, not MsgBox: a silent uninstall (/VERYSILENT
      // /SUPPRESSMSGBOXES) must not sit waiting for an answer. It defaults to
      // No, which keeps the user's settings.
      Prompt := 'Also remove your saved settings and queue?' + #13#10 + #13#10 + DataDir;
      if SuppressibleMsgBox(Prompt, mbConfirmation, MB_YESNO, IDNO) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
