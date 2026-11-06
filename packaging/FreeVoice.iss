#define AppVersion "1.0.0"
#ifndef PayloadDir
  #define PayloadDir "..\release\v1.0.0\星悦配音-1.0.0-便携版"
#endif
#ifndef RuntimeInstaller
  #define RuntimeInstaller "dependencies\vc_redist.x64.exe"
#endif
#define RuntimeVersion GetFileVersion(RuntimeInstaller)
#ifndef ReleaseDir
  #define ReleaseDir "..\release\v1.0.0"
#endif

[Setup]
AppId={{C433FA26-75E1-426A-8BEC-D14069F4F544}
AppName=星悦配音
AppVersion={#AppVersion}
AppPublisher=星悦配音
DefaultDirName={localappdata}\Programs\FreeVoice
DefaultGroupName=星悦配音
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#ReleaseDir}
OutputBaseFilename=星悦配音-1.0.0-安装版-x64
SetupIconFile=..\app.ico
UninstallDisplayIcon={app}\星悦配音.exe
VersionInfoVersion=1.0.0.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayName=星悦配音 v1.0.0

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RuntimeInstaller}"; Flags: dontcopy

[Icons]
Name: "{autoprograms}\星悦配音"; Filename: "{app}\星悦配音.exe"
Name: "{autodesktop}\星悦配音"; Filename: "{app}\星悦配音.exe"; Tasks: desktopicon

[InstallDelete]
Type: files; Name: "{app}\FreeVoice.exe"
Type: files; Name: "{autoprograms}\免费配音.lnk"; Check: not WizardNoIcons
Type: files; Name: "{autodesktop}\免费配音.lnk"; Check: not WizardNoIcons and WizardIsTaskSelected('desktopicon')

[Run]
Filename: "{app}\星悦配音.exe"; Description: "启动星悦配音"; Flags: nowait postinstall skipifsilent; Check: not NeedRestart

[Code]
var
  RuntimeRestartRequired: Boolean;

function HasRequiredRuntime: Boolean;
var
  Installed: Cardinal;
  VersionText: String;
  InstalledVersion, RequiredVersion: Int64;
begin
  Result := False;
  if not RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) then
    Exit;
  if Installed <> 1 then Exit;
  if not RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Version', VersionText) then
    Exit;
  if Copy(VersionText, 1, 1) = 'v' then Delete(VersionText, 1, 1);
  if not StrToVersion(VersionText, InstalledVersion) then Exit;
  if not StrToVersion('{#RuntimeVersion}', RequiredVersion) then Exit;
  Result := ComparePackedVersion(InstalledVersion, RequiredVersion) >= 0;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
begin
  Result := '';
  if HasRequiredRuntime then begin
    Log('Microsoft Visual C++ x64 runtime is already installed.');
    Exit;
  end;
  ExtractTemporaryFile('vc_redist.x64.exe');
  WizardForm.PreparingLabel.Caption := '正在安装配音引擎所需的微软运行库，请允许管理员授权…';
  if not ShellExec('runas', ExpandConstant('{tmp}\vc_redist.x64.exe'),
      '/install /passive /norestart', '', SW_SHOWNORMAL, ewWaitUntilTerminated, ExitCode) then begin
    Result := '未能安装微软 C++ x64 运行库：' + SysErrorMessage(ExitCode) +
      '。请重新安装并允许管理员授权。';
    Exit;
  end;
  Log(Format('Microsoft Visual C++ runtime installer exit code: %d', [ExitCode]));
  if (ExitCode <> 0) and (ExitCode <> 3010) and (ExitCode <> 1638) then begin
    Result := Format('微软 C++ x64 运行库安装失败（错误码 %d）。请重启电脑后重新安装软件。', [ExitCode]);
    Exit;
  end;
  RuntimeRestartRequired := ExitCode = 3010;
  if not HasRequiredRuntime then
    Result := '尚未检测到所需版本的微软 C++ x64 运行库，请重启电脑后重新安装软件。';
  if (Result <> '') and RuntimeRestartRequired then NeedsRestart := True;
end;

function NeedRestart: Boolean;
begin
  Result := RuntimeRestartRequired;
end;
