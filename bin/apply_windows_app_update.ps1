param(
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [string]$PackagePath,
    [string]$PackageSha256,
    [string]$RollbackVersion
)

$ErrorActionPreference = "Stop"

function Copy-Tree {
    param(
        [string]$SourceRoot,
        [string]$DestinationRoot
    )

    Get-ChildItem -LiteralPath $SourceRoot -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($SourceRoot.Length).TrimStart('\', '/')
        $destination = Join-Path $DestinationRoot $relative
        $parent = Split-Path -Parent $destination
        if ($parent) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
        }
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
    }
}

function Stage-PackageVersion {
    param(
        [string]$ResolvedPackagePath,
        [string]$VersionSha,
        [string]$VersionsRoot
    )

    $versionRoot = Join-Path $VersionsRoot $VersionSha
    $payloadRoot = Join-Path $versionRoot "payload"
    if (Test-Path $payloadRoot) {
        return $payloadRoot
    }

    $tempRoot = Join-Path $env:TEMP ("eve-app-stage-" + [guid]::NewGuid().ToString("N"))
    try {
        New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
        Expand-Archive -LiteralPath $ResolvedPackagePath -DestinationPath $tempRoot -Force
        New-Item -ItemType Directory -Force -Path $versionRoot | Out-Null
        Move-Item -LiteralPath $tempRoot -Destination $payloadRoot
    } catch {
        if (Test-Path $payloadRoot) {
            Remove-Item -LiteralPath $payloadRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw
    }

    return $payloadRoot
}

function Get-VersionPayloadRoot {
    param(
        [string]$VersionSha,
        [string]$VersionsRoot
    )
    $payloadRoot = Join-Path (Join-Path $VersionsRoot $VersionSha) "payload"
    if (-not (Test-Path $payloadRoot)) {
        throw "Cached Eve app version not found: $VersionSha"
    }
    return $payloadRoot
}

$resolvedInstallRoot = (Resolve-Path $InstallRoot).Path
$appStorageRoot = Join-Path $resolvedInstallRoot ".eve\windows_app"
$versionsRoot = Join-Path $appStorageRoot "versions"
New-Item -ItemType Directory -Force -Path $versionsRoot | Out-Null

if ($RollbackVersion) {
    $payloadRoot = Get-VersionPayloadRoot -VersionSha $RollbackVersion -VersionsRoot $versionsRoot
    Copy-Tree -SourceRoot $payloadRoot -DestinationRoot $resolvedInstallRoot
    exit 0
}

if (-not $PackagePath) {
    throw "PackagePath is required unless RollbackVersion is provided."
}
if (-not $PackageSha256) {
    throw "PackageSha256 is required when staging a new app version."
}

$resolvedPackage = (Resolve-Path $PackagePath).Path
$payloadRoot = Stage-PackageVersion -ResolvedPackagePath $resolvedPackage -VersionSha $PackageSha256 -VersionsRoot $versionsRoot
Copy-Tree -SourceRoot $payloadRoot -DestinationRoot $resolvedInstallRoot
