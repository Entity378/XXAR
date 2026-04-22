<#
.SYNOPSIS
    Full release build for Windows: app (onefolder) + helper + portable ZIP + MSI.

.DESCRIPTION
    Produces these artifacts under dist/:
      - XXAR/                            (onefolder app, from XXAR.spec)
      - Updater/XXAR Updater.exe         (helper, from updater/XXAR_Updater.spec)
      - release/Resources/Bin/           (staged layout for zipping)
      - release/Resources/Updater/
      - XXAR-windows-x64.zip             (portable)
      - XXAR-Installer-v<version>.msi    (WixSharp ManagedUI, dark theme)

    Expects python + pyinstaller + .NET SDK + WiX 7 CLI on PATH.

.PARAMETER Version
    Product version, e.g. "1.2.3".

.PARAMETER SkipMsi
    Skip MSI build (useful for dev iterations).

.EXAMPLE
    pwsh -File installer_ws\build_all.ps1 -Version 1.2.3
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [switch]$SkipMsi
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue `
        "dist\XXAR", "dist\Updater", "dist\release", `
        "dist\XXAR-windows-x64.zip", "build"

    Write-Host "==> [1/4] Building app (onefolder)"
    pyinstaller --noconfirm --clean XXAR.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for app" }
    if (-not (Test-Path "dist\XXAR\XXAR.exe")) {
        throw "Expected dist\XXAR\XXAR.exe after app build"
    }

    Write-Host "==> [2/4] Building updater helper"
    pyinstaller --noconfirm --clean `
        --distpath "dist\Updater" `
        --workpath "build\Updater" `
        "updater\XXAR_Updater.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for updater" }
    if (-not (Test-Path "dist\Updater\XXAR Updater.exe")) {
        throw "Expected dist\Updater\XXAR Updater.exe after updater build"
    }

    Write-Host "==> [3/4] Staging release layout and zipping"
    $release = "dist\release"
    $releaseBin = Join-Path $release "Resources\Bin"
    $releaseUpd = Join-Path $release "Resources\Updater"
    New-Item -ItemType Directory -Force -Path $releaseBin | Out-Null
    New-Item -ItemType Directory -Force -Path $releaseUpd | Out-Null
    Copy-Item "dist\XXAR\*" $releaseBin -Recurse -Force
    Copy-Item "dist\Updater\XXAR Updater.exe" $releaseUpd -Force

    $zipPath = Join-Path $repo "dist\XXAR-windows-x64.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

    # Compress-Archive trips over Defender's post-copy scan on the freshly
    # staged exe. Use .NET's ZipFile directly and retry on sharing violation.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $releaseAbs = (Resolve-Path $release).Path
    $zipped = $false
    for ($i = 1; $i -le 5; $i++) {
        try {
            [System.IO.Compression.ZipFile]::CreateFromDirectory(
                $releaseAbs, $zipPath,
                [System.IO.Compression.CompressionLevel]::Optimal,
                $false
            )
            $zipped = $true
            break
        } catch [System.IO.IOException] {
            Write-Host "    zip attempt $i locked, retrying..." -ForegroundColor Yellow
            Start-Sleep -Seconds 2
            if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
        }
    }
    if (-not $zipped) { throw "Failed to create $zipPath after 5 attempts" }
    Write-Host "    portable zip -> $zipPath"

    if ($SkipMsi) {
        Write-Host "==> [4/4] SkipMsi flag set - done."
        return
    }

    Write-Host "==> [4/4] Building MSI (WixSharp + custom WPF dialogs)"
    dotnet run --project installer_ws -- `
        --version $Version `
        --bin-dir "dist\XXAR" `
        --updater-dir "dist\Updater" `
        --output-dir "dist"
    if ($LASTEXITCODE -ne 0) { throw "WixSharp MSI build failed" }
}
finally {
    Pop-Location
}

Write-Host "Done."
