param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PrimaryHost = "",
    [int]$PrimaryApiPort = 8787,
    [int]$PrimaryOllamaPort = 11434,
    [switch]$IncludeCode,
    [switch]$IncludeApp,
    [switch]$UsePrimaryOllama,
    [switch]$PullModels,
    [switch]$SkipOllamaInstall,
    [switch]$SkipDaemonInstall
)

$ErrorActionPreference = "Stop"
$PythonInstallerUrl = "https://www.python.org/ftp/python/3.13.13/python-3.13.13-amd64.exe"
$PythonDefaultDir = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Refresh-PythonPath {
    $candidateDirs = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Launcher"),
        $PythonDefaultDir,
        (Join-Path $PythonDefaultDir "Scripts")
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

function Ensure-Python {
    $existing = $null
    try {
        $existing = Find-Python
    } catch {
        $existing = $null
    }
    if ($null -ne $existing) {
        return $existing
    }

    Write-Step "Installing Python from the official installer"
    $pythonInstaller = Join-Path $env:TEMP "python-3.13.13-amd64.exe"
    Invoke-WebRequest -UseBasicParsing $PythonInstallerUrl -OutFile $pythonInstaller
    & $pythonInstaller /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_test=0 Include_launcher=1
    if ($LASTEXITCODE -ne 0) {
        throw "Python installer exited with code $LASTEXITCODE"
    }
    Start-Sleep -Seconds 2
    Refresh-PythonPath
    return Find-Python
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

function Ensure-OllamaPath {
    $ollamaBin = Join-Path $env:LOCALAPPDATA "Programs\Ollama"
    if (Test-Path $ollamaBin -and -not (($env:Path -split ";") -contains $ollamaBin)) {
        $env:Path = "$ollamaBin;$env:Path"
    }
}

function Ensure-Ollama {
    param([switch]$SkipInstall)

    Ensure-OllamaPath
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if ($null -ne $ollama) {
        return
    }
    if ($SkipInstall) {
        throw "Ollama is not installed and -SkipOllamaInstall was passed."
    }

    Write-Step "Installing Ollama from the official installer"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://ollama.com/install.ps1 | iex"
    Ensure-OllamaPath
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if ($null -eq $ollama) {
        throw "Ollama installation completed, but the ollama CLI is still not on PATH."
    }
}

function Pull-ConfiguredModels {
    param([string]$ConfigPath)

    if (-not (Test-Path $ConfigPath)) {
        throw "Missing Eve config at $ConfigPath"
    }
    $config = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
    $models = New-Object System.Collections.Generic.List[string]
    foreach ($field in @("model", "fast_model", "deep_model", "preferred_fast_model", "preferred_deep_model")) {
        $value = [string]($config.$field)
        if (-not [string]::IsNullOrWhiteSpace($value) -and -not $models.Contains($value)) {
            $models.Add($value)
        }
    }
    foreach ($model in $models) {
        Write-Step "Pulling model $model"
        & ollama pull $model
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to pull model $model"
        }
    }
}

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$EveScript = Join-Path $ProjectRoot "eve.py"
$BundlePath = Join-Path $ProjectRoot ".eve\windows-bootstrap.json"
$ConfigPath = Join-Path $ProjectRoot ".eve\config.json"
$UpdaterScript = Join-Path $ProjectRoot "bin\update_windows_eve.ps1"
$Python = Ensure-Python

if (-not (Test-Path $EveScript)) {
    throw "Missing eve.py at $EveScript"
}

Write-Step "Initializing Eve"
Invoke-Python -Python $Python -Arguments @($EveScript, "init")

if ($PrimaryHost) {
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
    if ($PullModels -and -not $UsePrimaryOllama) {
        Ensure-Ollama -SkipInstall:$SkipOllamaInstall
        $pullArgs += "--pull-models"
    }

    Write-Step "Pulling bootstrap state from the primary Eve API"
    Invoke-Python -Python $Python -Arguments $pullArgs
} else {
    Write-Step "Bootstrapping a local Eve identity"
    Invoke-Python -Python $Python -Arguments @($EveScript, "identity", "bootstrap")
}

if ($PullModels -and -not $UsePrimaryOllama -and -not $PrimaryHost) {
    Ensure-Ollama -SkipInstall:$SkipOllamaInstall
    Pull-ConfiguredModels -ConfigPath $ConfigPath
} elseif (-not $UsePrimaryOllama) {
    Ensure-Ollama -SkipInstall:$SkipOllamaInstall
}

if (-not $SkipDaemonInstall) {
    Write-Step "Installing Eve background services"
    Invoke-Python -Python $Python -Arguments @($EveScript, "daemon", "install")
}

if ($PrimaryHost -and (Test-Path $UpdaterScript)) {
    Write-Step "Installing Eve auto-update task"
    $updaterArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $UpdaterScript,
        "-ProjectRoot", $ProjectRoot,
        "-PrimaryHost", $PrimaryHost,
        "-PrimaryApiPort", "$PrimaryApiPort",
        "-PrimaryOllamaPort", "$PrimaryOllamaPort",
        "-InstallAutoUpdateTask",
        "-RecordCurrentState"
    )
    if ($IncludeCode) {
        $updaterArgs += "-IncludeCode"
    }
    $updaterArgs += "-IncludeApp"
    if ($UsePrimaryOllama) {
        $updaterArgs += "-UsePrimaryOllama"
    }
    if ($PullModels) {
        $updaterArgs += "-PullModels"
    }
    & powershell @updaterArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install the Eve auto-update task."
    }
}

Write-Step "Running Eve doctor"
Invoke-Python -Python $Python -Arguments @($EveScript, "doctor")

Write-Host ""
Write-Host "Windows Eve install completed."
