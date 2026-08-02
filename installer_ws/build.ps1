<#
.SYNOPSIS
    Windows release build for the MSI channel: onefolder app + WixSharp MSI.

.DESCRIPTION
    Produces these artifacts under dist/:
      - XXAR/                          (onefolder app, from XXAR.spec)
      - XXAR-Installer-v<version>.msi  (WixSharp ManagedUI, dark theme)

    The MSI packages dist\XXAR directly and never touches the portable zip, so this
    script is independent of installer_custom\build.ps1 and can be dropped with it.

    Expects python + pyinstaller + .NET SDK + WiX 7 CLI on PATH.

.PARAMETER Version
    Product version, e.g. "1.2.3".

.PARAMETER SkipApp
    Reuse an existing dist\XXAR instead of running PyInstaller. Use it when the setup
    build already produced the bundle, to avoid compiling the app twice.

.EXAMPLE
    pwsh -File installer_ws\build.ps1 -Version 1.2.3
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
    if ($SkipApp) {
        Write-Host "==> [1/2] SkipApp flag set - reusing existing dist\XXAR"
    }
    else {
        Write-Host "==> [1/2] Building app (onefolder)"
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "dist\XXAR", "build"
        pyinstaller --noconfirm --clean XXAR.spec
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for app" }
    }
    if (-not (Test-Path "dist\XXAR\XXAR.exe")) {
        throw "Expected dist\XXAR\XXAR.exe after app build"
    }

    Write-Host "==> [2/2] Building MSI (WixSharp + custom WPF dialogs)"
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
