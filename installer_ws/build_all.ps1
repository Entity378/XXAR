<#
.SYNOPSIS
    Full release build for Windows: onefolder app + portable ZIP + MSI.

.DESCRIPTION
    Produces these artifacts under dist/:
      - XXAR/                            (onefolder app, from XXAR.spec)
      - release/resources/               (staged portable layout for zipping)
      - XXAR-windows-x64.zip             (portable; both MSI and portable install flat under resources\)
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
        "dist\XXAR", "dist\release", "dist\XXAR-windows-x64.zip", "build"

    Write-Host "==> [1/3] Building app (onefolder)"
    pyinstaller --noconfirm --clean XXAR.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for app" }
    if (-not (Test-Path "dist\XXAR\XXAR.exe")) {
        throw "Expected dist\XXAR\XXAR.exe after app build"
    }

    Write-Host "==> [2/3] Staging portable layout and zipping"
    # Both channels install flat under resources\; the portable self-updates with a generated script (no helper).
    $release = "dist\release"
    $releaseRes = Join-Path $release "resources"
    New-Item -ItemType Directory -Force -Path $releaseRes | Out-Null
    Copy-Item "dist\XXAR\*" $releaseRes -Recurse -Force

    $zipPath = Join-Path $repo "dist\XXAR-windows-x64.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

    # Use .NET ZipFile with retries — Compress-Archive trips over Defender's scan lock.
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
        Write-Host "==> [3/3] SkipMsi flag set - done."
        return
    }

    Write-Host "==> [3/3] Building MSI (WixSharp + custom WPF dialogs)"
    dotnet run --project installer_ws -- `
        --version $Version `
        --bin-dir "dist\XXAR" `
        --output-dir "dist"
    if ($LASTEXITCODE -ne 0) { throw "WixSharp MSI build failed" }
}
finally {
    Pop-Location
}

Write-Host "Done."
