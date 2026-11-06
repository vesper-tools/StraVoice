"""Run the real installer dependency logic with simulated registry/process results."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class InstallerPrerequisitesTests(unittest.TestCase):
    def test_dependency_installation_branches(self):
        compiler = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Inno Setup 6/ISCC.exe"
        if os.name != "nt" or not compiler.is_file():
            self.skipTest("Inno Setup 6 compiler is required")
        source = (Path(__file__).parent / "packaging/FreeVoice.iss").read_text(encoding="utf-8")
        code = source.split("[Code]\n", 1)[1].replace("{#RuntimeVersion}", "14.51.36247.0")
        for name in ("RegQueryDWordValue", "RegQueryStringValue", "ExtractTemporaryFile", "ShellExec"):
            code = code.replace(name + "(", "Test" + name + "(")
        mocks = r'''
var
  MockInstalled: Cardinal;
  MockVersion: String;
  MockLaunch, MockUpgrade: Boolean;
  MockExit, LaunchCount: Integer;

function TestRegQueryDWordValue(Root: Integer; Key, Name: String; var Value: Cardinal): Boolean;
begin
  if Root <> HKLM64 then RaiseException('Must inspect the x64 registry');
  Value := MockInstalled;
  Result := MockInstalled <> 0;
end;

function TestRegQueryStringValue(Root: Integer; Key, Name: String; var Value: String): Boolean;
begin
  Value := MockVersion;
  Result := True;
end;

procedure TestExtractTemporaryFile(Name: String);
begin
end;

function TestShellExec(Verb, Filename, Params, WorkingDir: String; Show: Integer;
  Wait: TExecWait; var ExitCode: Integer): Boolean;
begin
  if Verb <> 'runas' then RaiseException('Missing elevation');
  if Params <> '/install /passive /norestart' then RaiseException('Incorrect arguments');
  if Wait <> ewWaitUntilTerminated then RaiseException('Must wait for installation');
  LaunchCount := LaunchCount + 1;
  ExitCode := MockExit;
  Result := MockLaunch;
  if MockLaunch and MockUpgrade then begin
    MockInstalled := 1;
    MockVersion := 'v14.51.36247.0';
  end;
end;
'''
        checks = r'''
procedure Require(Condition: Boolean; Description: String);
begin
  if not Condition then RaiseException(Description);
end;

procedure InitializeWizard;
var
  Restart: Boolean;
  Error: String;
begin
  MockInstalled := 1;
  MockVersion := 'v14.51.36247.0';
  Require(HasRequiredRuntime, 'Same runtime version must be accepted');
  MockVersion := 'v14.52.1.0';
  Require(HasRequiredRuntime, 'Newer runtime must be accepted');
  Error := PrepareToInstall(Restart);
  Require((Error = '') and (LaunchCount = 0), 'Existing runtime must skip installation');
  MockVersion := 'v14.50.35719.0';
  Require(not HasRequiredRuntime, 'Older runtime must be rejected');
  MockVersion := 'broken';
  Require(not HasRequiredRuntime, 'Invalid registry version must be rejected');
  MockInstalled := 0;
  Require(not HasRequiredRuntime, 'Missing runtime must be rejected');
  MockLaunch := False;
  MockExit := 1223;
  Error := PrepareToInstall(Restart);
  Require(Error <> '', 'Cancelled elevation must block installation');
  MockLaunch := True;
  MockExit := 1603;
  Error := PrepareToInstall(Restart);
  Require(Error <> '', 'Failed prerequisite must block installation');
  MockExit := 0;
  MockUpgrade := False;
  Error := PrepareToInstall(Restart);
  Require(Error <> '', 'Success code without installed runtime must be rejected');
  MockExit := 1638;
  Error := PrepareToInstall(Restart);
  Require(Error <> '', '1638 without sufficient runtime must be rejected');
  MockUpgrade := True;
  Error := PrepareToInstall(Restart);
  Require(Error = '', '1638 with sufficient runtime must be accepted');
  MockInstalled := 0;
  MockExit := 0;
  Error := PrepareToInstall(Restart);
  Require((Error = '') and not NeedRestart, 'Successful installation must continue');
  MockInstalled := 0;
  MockExit := 3010;
  Error := PrepareToInstall(Restart);
  Require((Error = '') and NeedRestart, '3010 must request restart');
  SaveStringToFile(ExpandConstant('{src}\passed.txt'), 'passed', False);
  RuntimeRestartRequired := False;
end;
'''
        with tempfile.TemporaryDirectory(prefix="freevoice-installer-test-") as temp:
            folder = Path(temp)
            setup = folder / "test.iss"
            setup.write_text("[Setup]\nAppName=Prerequisite logic test\nAppVersion=1\n"
                             "CreateAppDir=no\nUninstallable=no\nPrivilegesRequired=lowest\n"
                             f"OutputDir={folder}\nOutputBaseFilename=test\n[Code]\n"
                             + mocks + code + checks, encoding="utf-8-sig")
            compiled = subprocess.run([str(compiler), "/Q", str(setup)], capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            subprocess.run([str(folder / "test.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                            f"/LOG={folder / 'test.log'}"], timeout=30, capture_output=True)
            log = (folder / "test.log").read_text(encoding="utf-8-sig", errors="replace")
            self.assertTrue((folder / "passed.txt").is_file(), log)


if __name__ == "__main__":
    unittest.main()
