param(
    [string]$Python = ".venv\Scripts\python.exe",
    [string]$Inno,
    [switch]$PortableOnly
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
function Assert-Exit { if ($LASTEXITCODE -ne 0) { throw "Etapa falhou com código $LASTEXITCODE." } }
function Confirm-Smoke([string]$Executable, [string]$OutputPath) {
    $output = Join-Path (Get-Location) $OutputPath
    $report = Join-Path $output 'smoke.json'
    $process = Start-Process -FilePath $Executable -ArgumentList @('--smoke', ('"{0}"' -f $output)) -PassThru
    if (!$process.WaitForExit(45000)) { $process.Kill(); throw 'Tempo limite do smoke.' }
    if ($process.ExitCode -ne 0 -or !(Test-Path -LiteralPath $report) -or
        !(Get-Content -Raw -LiteralPath $report | ConvertFrom-Json).ok) { throw 'Smoke do executável falhou.' }
}
& $Python -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8"
Assert-Exit
$env:PYTHONUTF8 = '1'
& $Python -m ruff check src packaging tests
Assert-Exit
& $Python -m pytest -q
Assert-Exit
$pyinstallerArgs = @(
    # PyInstaller can reuse the executable when only the icon's contents change.
    '--clean', '--noconfirm', '--onedir', '--windowed', '--name', 'SpotiFlying', '--paths', 'src',
    '--icon', 'src/spotiflying/assets/spotiflying.ico', '--version-file', 'packaging/version.txt',
    '--add-data', 'src/spotiflying/assets:spotiflying/assets',
    '--hidden-import', 'winrt.windows.foundation', '--hidden-import', 'winrt.windows.foundation.collections',
    '--collect-submodules', 'winrt',
    'packaging/launcher.py'
)
& $Python -m PyInstaller @pyinstallerArgs
Assert-Exit
& $Python packaging/prepare_runtime.py
Assert-Exit
& $Python packaging/dependency_notices.py
Assert-Exit
Copy-Item -LiteralPath LICENSE, THIRD_PARTY_NOTICES.md -Destination dist/SpotiFlying
Confirm-Smoke 'dist/SpotiFlying/SpotiFlying.exe' 'release/smoke-frozen'
& $Python packaging/portable.py
Assert-Exit
$assets = @('SpotiFlying-Portable-x64.zip')
if (!$PortableOnly) {
    if (!$Inno) {
        $choices = @(
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
            (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
        )
        $Inno = $choices | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if (!$Inno) { throw 'Informe o caminho do Inno Setup 6 com -Inno.' }
    $encoding = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [System.Text.Encoding]::Default
        & $Inno '/Qp' 'packaging/setup.iss'
        Assert-Exit
    } finally {
        [Console]::OutputEncoding = $encoding
    }
    $assets += 'SpotiFlying-Setup-x64.exe'
}
$assets | Sort-Object | ForEach-Object {
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path 'release' $_)).Hash.ToLowerInvariant()
    "$hash  $_"
} | Set-Content -Encoding ascii -LiteralPath release/SHA256SUMS.txt
