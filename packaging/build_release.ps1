param(
    [string]$PythonExe = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    [string]$IsccExe = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    [string]$ReleaseName = 'v1.0.0-offline-number-reading-fix'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$releaseRoot = Join-Path $projectRoot 'release'
$destination = [IO.Path]::GetFullPath((Join-Path $releaseRoot $ReleaseName))
if (-not $destination.StartsWith($releaseRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw '发布目录必须位于项目的 release 目录内。'
}
if (Test-Path -LiteralPath $destination) { throw "发布目录已存在，请换一个 ReleaseName：$destination" }
$runtimeDir = Join-Path $PSScriptRoot 'dependencies'
$runtime = Join-Path $runtimeDir 'vc_redist.x64.exe'
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
if (-not (Test-Path -LiteralPath $runtime)) {
    Invoke-WebRequest 'https://aka.ms/vc14/vc_redist.x64.exe' -OutFile $runtime
}
$signature = Get-AuthenticodeSignature -LiteralPath $runtime
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation,') {
    throw '微软运行库签名校验失败，停止打包。'
}
$expectedHash = '843068991DAAA1F73AD9F6239BCE4D0F6A07A51F18C37EA2A867E9BECA71295C'
if ((Get-FileHash -LiteralPath $runtime -Algorithm SHA256).Hash -ne $expectedHash) {
    throw '运行库与已验证版本不一致，请先核对微软签名、版本和兼容性，再更新固定哈希。'
}
$buildTemp = Join-Path ([IO.Path]::GetTempPath()) ('freevoice-release-' + [guid]::NewGuid())
$previousPythonPath = $env:PYTHONPATH
try {
    New-Item -ItemType Directory -Path $buildTemp | Out-Null
    $env:PYTHONPATH = Join-Path $projectRoot '.venv\Lib\site-packages'
    Push-Location $projectRoot
    try {
        & $PythonExe -m PyInstaller --noconfirm --workpath (Join-Path $buildTemp 'build') --distpath (Join-Path $buildTemp 'dist') FreeVoice.spec
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 构建失败。' }
    } finally { Pop-Location }
    $payload = Join-Path $destination '星悦配音-1.0.0-便携版-x64'
    New-Item -ItemType Directory -Path $payload | Out-Null
    Copy-Item -LiteralPath (Join-Path $buildTemp 'dist\星悦配音.exe') -Destination $payload
    foreach ($name in @('bin\ffmpeg.exe', 'models\speech-timing\model.int8.onnx', 'models\speech-timing\tokens.txt')) {
        $target = Join-Path $payload $name
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item -LiteralPath (Join-Path $projectRoot $name) -Destination $target
    }
    Copy-Item -LiteralPath (Join-Path $projectRoot 'THIRD_PARTY') -Destination $payload -Recurse
    Copy-Item -LiteralPath (Join-Path $projectRoot 'LICENSE') -Destination $payload
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '使用说明.txt') -Destination $payload
    # Portable users can install the same verified prerequisite without downloading it.
    New-Item -ItemType Directory -Path (Join-Path $payload 'prerequisites') | Out-Null
    Copy-Item -LiteralPath $runtime -Destination (Join-Path $payload 'prerequisites')
    & $IsccExe "/DPayloadDir=$payload" "/DReleaseDir=$destination" "/DRuntimeInstaller=$runtime" (Join-Path $PSScriptRoot 'FreeVoice.iss')
    if ($LASTEXITCODE -ne 0) { throw '安装包编译失败。' }
    Compress-Archive -LiteralPath $payload -DestinationPath (Join-Path $destination '星悦配音-1.0.0-便携版-x64.zip')
    Write-Output "发布目录：$destination"
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $resolvedTemp = [IO.Path]::GetFullPath($buildTemp)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($resolvedTemp.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $resolvedTemp).StartsWith('freevoice-release-')) {
        if (Test-Path -LiteralPath $resolvedTemp) { Remove-Item -LiteralPath $resolvedTemp -Recurse -Force }
    }
}
