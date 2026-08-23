param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [Parameter(Mandatory = $true)][string]$PrimaryHost,
    [int]$PrimaryApiPort = 8787,
    [int]$PrimaryOllamaPort = 11434,
    [switch]$IncludeCode,
    [switch]$IncludeApp,
    [switch]$UsePrimaryOllama,
    [switch]$PullModels,
    [switch]$CheckOnly,
    [switch]$RecordCurrentState,
    [switch]$AutoRestart,
    [switch]$InstallAutoUpdateTask
)

$ErrorActionPreference = "Stop"
$UpdateTaskName = "Eve Auto Update"
$PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Refresh-PythonPath {
    $candidateDirs = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Launcher"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\Scripts")
    )
    foreach ($dir in $candidateDirs) {
        if (Test-Path $dir -and -not (($env:Path -split ";") -contains $dir)) {
            $env:Path = "$dir;$env:Path"
        }
    }
}

function Find-Python {
    Refresh-PythonPath
    foreach ($candidate in @(
        @{ Command = "py"; Arguments = @("-3") },
        @{ Command = "python"; Arguments = @() },
        @{ Command = "python3"; Arguments = @() }
    )) {
        $commandInfo = Get-Command $candidate.Command -ErrorAction SilentlyContinue
        if ($null -ne $commandInfo) {
            return @{
                Command = $commandInfo.Source
                Arguments = $candidate.Arguments
            }
        }
    }
    throw "Python 3 was not found. Install Python 3.9+ first."
}

function Invoke-Python {
    param(
        [hashtable]$Python,
        [string[]]$Arguments
    )
    & $Python.Command @($Python.Arguments + $Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return $null
    }
    $raw = Get-Content -Raw -Path $Path
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    return $raw | ConvertFrom-Json
}

function Write-JsonFile {
    param(
        [string]$Path,
        $Value
    )
    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $json = $Value | ConvertTo-Json -Depth 12
    Set-Content -Path $Path -Value $json -Encoding UTF8
}

function Get-RemoteUpdateManifest {
    $url = "http://$PrimaryHost`:$PrimaryApiPort/api/update-manifest?ollama_port=$PrimaryOllamaPort"
    $payload = Invoke-RestMethod -UseBasicParsing -Uri $url -Method Get
    if ($null -eq $payload) {
        throw "Update manifest request returned no data."
    }
    if ($payload.PSObject.Properties.Name -contains "ok" -and -not $payload.ok) {
        throw "Update manifest request failed for $url"
    }
    if ($payload.PSObject.Properties.Name -contains "data" -and $null -ne $payload.data) {
        return $payload.data
    }
    return $payload
}

function Download-RemoteAppPackage {
    param([string]$DestinationPath)
    $url = "http://$PrimaryHost`:$PrimaryApiPort/api/windows-app-package"
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $DestinationPath
}

function Get-FileSha256 {
    param([string]$Path)
    return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
}

function Test-UpdateNeeded {
    param(
        $RemoteManifest,
        $LocalState
    )

    if ($null -eq $LocalState) {
        return $true
    }

    $bootstrapChanged = [string]$LocalState.bootstrap_sha256 -ne [string]$RemoteManifest.bootstrap.sha256
    $hostChanged = [string]$LocalState.primary_host -ne [string]$PrimaryHost -or [string]$LocalState.primary_api_port -ne [string]$PrimaryApiPort
    $codeChanged = [string]$LocalState.code_sha256 -ne [string]$RemoteManifest.code_bundle.sha256
    $appChanged = $false
    if ($IncludeApp -and $null -ne $RemoteManifest.app_package) {
        $appChanged = [string]$LocalState.app_package_sha256 -ne [string]$RemoteManifest.app_package.sha256
    }

    if ($hostChanged -or $bootstrapChanged) {
        return $true
    }
    if ($IncludeCode -and $codeChanged) {
        return $true
    }
    if ($appChanged) {
        return $true
    }
    return $false
}

function Write-UpdateState {
    param(
        $RemoteManifest,
        $ExistingState,
        [bool]$UpdateApplied,
        [string]$CurrentAppVersionSha = "",
        [string]$PreviousAppVersionSha = ""
    )

    $codeSha = ""
    if ($IncludeCode) {
        $codeSha = [string]$RemoteManifest.code_bundle.sha256
    } elseif ($null -ne $ExistingState -and $ExistingState.PSObject.Properties.Name -contains "code_sha256") {
        $codeSha = [string]$ExistingState.code_sha256
    }
    $appSha = ""
    if ($IncludeApp -and $null -ne $RemoteManifest.app_package) {
        $appSha = [string]$RemoteManifest.app_package.sha256
    } elseif ($null -ne $ExistingState -and $ExistingState.PSObject.Properties.Name -contains "app_package_sha256") {
        $appSha = [string]$ExistingState.app_package_sha256
    }
    if (-not $CurrentAppVersionSha -and $null -ne $ExistingState -and $ExistingState.PSObject.Properties.Name -contains "current_app_version_sha") {
        $CurrentAppVersionSha = [string]$ExistingState.current_app_version_sha
    }
    if (-not $PreviousAppVersionSha -and $null -ne $ExistingState -and $ExistingState.PSObject.Properties.Name -contains "previous_app_version_sha") {
        $PreviousAppVersionSha = [string]$ExistingState.previous_app_version_sha
    }

    $state = [ordered]@{
        version = 1
        primary_host = $PrimaryHost
        primary_api_port = $PrimaryApiPort
        primary_ollama_port = $PrimaryOllamaPort
        include_code = [bool]$IncludeCode
        include_app = [bool]$IncludeApp
        use_primary_ollama = [bool]$UsePrimaryOllama
        pull_models = [bool]$PullModels
        checked_at = (Get-Date).ToUniversalTime().ToString("o")
        last_update_applied = [bool]$UpdateApplied
        bootstrap_sha256 = [string]$RemoteManifest.bootstrap.sha256
        code_sha256 = $codeSha
        app_package_sha256 = $appSha
        current_app_version_sha = $CurrentAppVersionSha
        previous_app_version_sha = $PreviousAppVersionSha
        remote_manifest = $RemoteManifest
    }
    if ($UpdateApplied -or $RecordCurrentState) {
        $state["updated_at"] = (Get-Date).ToUniversalTime().ToString("o")
    } elseif ($null -ne $ExistingState -and $ExistingState.PSObject.Properties.Name -contains "updated_at") {
        $state["updated_at"] = [string]$ExistingState.updated_at
    }
    Write-JsonFile -Path $UpdateStatePath -Value $state
}

function Install-AutoUpdateTask {
    $scriptPath = Join-Path $ProjectRoot "bin\update_windows_eve.ps1"
    if (-not (Test-Path $scriptPath)) {
        throw "Missing updater script at $scriptPath"
    }
    $taskArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$scriptPath`"",
        "-ProjectRoot", "`"$ProjectRoot`"",
        "-PrimaryHost", "`"$PrimaryHost`"",
        "-PrimaryApiPort", "$PrimaryApiPort",
        "-PrimaryOllamaPort", "$PrimaryOllamaPort",
        "-InstallAutoUpdateTask",
        "-AutoRestart"
    )
    if ($IncludeCode) {
        $taskArgs += "-IncludeCode"
    }
    if ($IncludeApp) {
        $taskArgs += "-IncludeApp"
    }
    if ($UsePrimaryOllama) {
        $taskArgs += "-UsePrimaryOllama"
    }
    if ($PullModels) {
        $taskArgs += "-PullModels"
    }
    $taskCommand = "$PowerShellExe " + ($taskArgs -join " ")
    & schtasks /Create /TN $UpdateTaskName /SC HOURLY /MO 1 /TR $taskCommand /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the Eve auto-update scheduled task."
    }
}

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$EveScript = Join-Path $ProjectRoot "eve.py"
$AppUpdateHelper = Join-Path $ProjectRoot "bin\apply_windows_app_update.ps1"
$UpdateStatePath = Join-Path $ProjectRoot ".eve\windows_update_state.json"
$Python = Find-Python

if (-not (Test-Path $EveScript)) {
    throw "Missing eve.py at $EveScript"
}

$existingState = Read-JsonFile -Path $UpdateStatePath
$currentAppVersionSha = ""
$previousAppVersionSha = ""
if ($null -ne $existingState) {
    if ($existingState.PSObject.Properties.Name -contains "current_app_version_sha") {
        $currentAppVersionSha = [string]$existingState.current_app_version_sha
    }
    if ($existingState.PSObject.Properties.Name -contains "previous_app_version_sha") {
        $previousAppVersionSha = [string]$existingState.previous_app_version_sha
    }
}

Write-Step "Checking for Eve updates from the primary machine"
$remoteManifest = Get-RemoteUpdateManifest
$needsUpdate = Test-UpdateNeeded -RemoteManifest $remoteManifest -LocalState $existingState

if ($RecordCurrentState) {
    $recordCurrentAppVersionSha = $currentAppVersionSha
    if ($IncludeApp -and $null -ne $remoteManifest.app_package) {
        $recordCurrentAppVersionSha = [string]$remoteManifest.app_package.sha256
    }
    Write-UpdateState -RemoteManifest $remoteManifest -ExistingState $existingState -UpdateApplied:$false -CurrentAppVersionSha $recordCurrentAppVersionSha -PreviousAppVersionSha $previousAppVersionSha
    if ($InstallAutoUpdateTask) {
        Write-Step "Installing Eve auto-update task"
        Install-AutoUpdateTask
    }
    Write-Host ""
    Write-Host "Recorded current Eve update state."
    exit 0
}

if (-not $needsUpdate) {
    Write-Host ""
    Write-Host "Eve is already up to date."
    if ($InstallAutoUpdateTask) {
        Write-Step "Installing Eve auto-update task"
        Install-AutoUpdateTask
    }
    Write-UpdateState -RemoteManifest $remoteManifest -ExistingState $existingState -UpdateApplied:$false -CurrentAppVersionSha $currentAppVersionSha -PreviousAppVersionSha $previousAppVersionSha
    exit 0
}

if ($CheckOnly) {
    Write-Host ""
    Write-Host "An Eve update is available."
    exit 0
}

$appUpdateApplied = $false
$newAppVersionSha = $currentAppVersionSha
$rollbackVersionSha = $previousAppVersionSha
if ($IncludeApp -and $null -ne $remoteManifest.app_package) {
    $existingAppSha = ""
    if ($null -ne $existingState -and $existingState.PSObject.Properties.Name -contains "app_package_sha256") {
        $existingAppSha = [string]$existingState.app_package_sha256
    }
    $remoteAppSha = [string]$remoteManifest.app_package.sha256
    if ($existingAppSha -ne $remoteAppSha) {
        if (-not (Test-Path $AppUpdateHelper)) {
            throw "Missing app update helper at $AppUpdateHelper"
        }
        $rollbackVersionSha = $currentAppVersionSha
        Write-Step "Downloading the updated Eve app package"
        $packagePath = Join-Path $env:TEMP ("EveWindowsAppPackage-" + [guid]::NewGuid().ToString("N") + ".zip")
        try {
            Download-RemoteAppPackage -DestinationPath $packagePath
            $downloadedSha = Get-FileSha256 -Path $packagePath
            if ($downloadedSha -ne $remoteAppSha.ToLowerInvariant()) {
                throw "The downloaded Eve app package hash did not match the update manifest."
            }
            Write-Step "Applying the updated Eve app package"
            & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $AppUpdateHelper -PackagePath $packagePath -PackageSha256 $remoteAppSha -InstallRoot $ProjectRoot
            if ($LASTEXITCODE -ne 0) {
                throw "The Eve app package helper exited with code $LASTEXITCODE"
            }
            $appUpdateApplied = $true
            $newAppVersionSha = $remoteAppSha
        } finally {
            if (Test-Path $packagePath) {
                Remove-Item -LiteralPath $packagePath -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

$pullArgs = @(
    $EveScript,
    "bootstrap",
    "pull",
    "--host",
    $PrimaryHost,
    "--api-port",
    "$PrimaryApiPort",
    "--ollama-port",
    "$PrimaryOllamaPort"
)

if ($UsePrimaryOllama) {
    $pullArgs += "--use-primary-ollama"
}
if ($IncludeCode) {
    $pullArgs += "--include-code"
}
if ($PullModels) {
    $pullArgs += "--pull-models"
}

try {
    Write-Step "Pulling Eve updates from the primary machine"
    Invoke-Python -Python $Python -Arguments $pullArgs

    if ($AutoRestart -or $appUpdateApplied) {
        Write-Step "Restarting Eve background services"
        Invoke-Python -Python $Python -Arguments @($EveScript, "daemon", "stop")
        Invoke-Python -Python $Python -Arguments @($EveScript, "daemon", "install")
    }

    if ($InstallAutoUpdateTask) {
        Write-Step "Installing Eve auto-update task"
        Install-AutoUpdateTask
    }

    Write-Step "Running Eve doctor"
    Invoke-Python -Python $Python -Arguments @($EveScript, "doctor")

    Write-UpdateState -RemoteManifest $remoteManifest -ExistingState $existingState -UpdateApplied:$true -CurrentAppVersionSha $newAppVersionSha -PreviousAppVersionSha $rollbackVersionSha
} catch {
    if ($appUpdateApplied -and $rollbackVersionSha) {
        Write-Step "Rolling back to the previous Eve app version"
        & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $AppUpdateHelper -RollbackVersion $rollbackVersionSha -InstallRoot $ProjectRoot
        if ($LASTEXITCODE -eq 0) {
            try {
                Write-Step "Restarting Eve after rollback"
                Invoke-Python -Python $Python -Arguments @($EveScript, "daemon", "stop")
                Invoke-Python -Python $Python -Arguments @($EveScript, "daemon", "install")
            } catch {
            }
        }
    }
    throw
}

Write-Host ""
Write-Host "Windows Eve update completed."
