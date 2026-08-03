<#
.SYNOPSIS
    Windows release build for the custom setup channel: onefolder app + portable ZIP + setup exe.

.DESCRIPTION
    Produces these artifacts under dist/:
      - XXAR/                      (onefolder app, from XXAR.spec)
      - release/resources/         (staged portable layout for zipping)
      - XXAR-windows-x64.zip       (portable channel; installs flat under resources\)
      - XXAR-Setup-v<version>.exe  (WPF stub + zip payload + trailer)

    Expects python + pyinstaller + .NET SDK on PATH.

.PARAMETER Version
    Product version, e.g. "1.2.3".

.PARAMETER SkipApp
    Reuse an existing dist\XXAR instead of running PyInstaller.

.EXAMPLE
    pwsh -File installer_custom\build.ps1 -Version 1.2.3
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [switch]$SkipApp
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    # Under -SkipApp the app bundle is left alone, so whatever already sits in dist\XXAR is what ends up packaged.
    $stalePaths = @("dist\release", "dist\XXAR-windows-x64.zip")
    if (-not $SkipApp) { $stalePaths += @("dist\XXAR", "build") }
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $stalePaths

    if ($SkipApp) {
        Write-Host "==> [1/3] SkipApp flag set - reusing existing dist\XXAR"
    }
    else {
        Write-Host "==> [1/3] Building app (onefolder)"
        pyinstaller --noconfirm --clean XXAR.spec
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for app" }
    }
    if (-not (Test-Path "dist\XXAR\XXAR.exe")) {
        throw "Expected dist\XXAR\XXAR.exe after app build"
    }

    Write-Host "==> [2/3] Staging portable layout and zipping"
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

    Write-Host "==> [3/3] Building setup (WPF stub + zip payload)"
    # Always compiled from scratch: an incremental build can emit different bytes than a clean one.
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "installer_custom\obj", "installer_custom\bin"
    # No -p:Version on purpose: the stub keeps its own version, the app's travels in the trailer.
    dotnet build installer_custom -c Release
    if ($LASTEXITCODE -ne 0) { throw "Setup stub build failed" }

    # The stub doubles as the uninstaller, so it rides inside the payload and is extracted like any other file.
    $stubPath = Join-Path $repo "installer_custom\bin\Release\XXAR-Setup.exe"
    $payloadPath = Join-Path $repo "dist\setup-payload.zip"
    if (Test-Path $payloadPath) { Remove-Item $payloadPath -Force }
    Copy-Item $zipPath $payloadPath -Force
    $payloadZip = [System.IO.Compression.ZipFile]::Open($payloadPath, 'Update')
    try {
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $payloadZip, $stubPath, "XXAR-Uninstall.exe") | Out-Null
    }
    finally { $payloadZip.Dispose() }

    # Self-extracting layout: stub exe + payload zip + 48-byte trailer.
    # The version rides in the trailer so a new release needs no recompiling; the field is a fixed 32 bytes
    # because the trailer is read backwards from the end of the file.
    $setupPath = Join-Path $repo "dist\XXAR-Setup-v$Version.exe"
    if (Test-Path $setupPath) { Remove-Item $setupPath -Force }
    if ($Version.Length -gt 32) { throw "Version string does not fit the 32-byte trailer field: $Version" }
    $versionField = New-Object byte[] 32
    [System.Text.Encoding]::ASCII.GetBytes($Version).CopyTo($versionField, 0)

    $stubBytes = [System.IO.File]::ReadAllBytes($stubPath)
    $dstStream = [System.IO.File]::Create($setupPath)
    try {
        $dstStream.Write($stubBytes, 0, $stubBytes.Length)
        $srcStream = [System.IO.File]::OpenRead($payloadPath)
        try { $srcStream.CopyTo($dstStream) } finally { $srcStream.Close() }
        $dstStream.Write([System.Text.Encoding]::ASCII.GetBytes("XXARSFX2"), 0, 8)
        $dstStream.Write([BitConverter]::GetBytes([int64]$stubBytes.Length), 0, 8)
        $dstStream.Write($versionField, 0, 32)
    }
    finally { $dstStream.Close() }
    Remove-Item $payloadPath -Force
    Write-Host "    setup -> $setupPath"
}
finally {
    Pop-Location
}

Write-Host "Done."
