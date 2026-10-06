param(
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$DataRoot = (Join-Path $env:LOCALAPPDATA 'Robin\explorer'),
    [string]$PythonPath = '',
    [int]$Port = 4173,
    [int]$RefreshSeconds = 300,
    [switch]$SkipStart
)

$ErrorActionPreference = 'Stop'
$taskName = 'RobinRealDataExplorer'
$python = $PythonPath
if (-not $python) {
    $python = Join-Path $RepositoryRoot '.venv\Scripts\pythonw.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        $python = Join-Path $RepositoryRoot '.venv\Scripts\python.exe'
    }
}
$launcher = Join-Path $RepositoryRoot 'scripts\run_real_data_explorer.py'
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $launcher)) {
    throw 'ROBIN_EXPLORER_RUNTIME_NOT_FOUND'
}

New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
$arguments = @(
    ('"{0}"' -f $launcher),
    '--root', ('"{0}"' -f $DataRoot),
    '--port', $Port,
    '--refresh-seconds', $RefreshSeconds
) -join ' '
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $RepositoryRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Days 3650)
$mode = 'ScheduledTask'
try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'Robin private real-data explorer on localhost' -Force | Out-Null
}
catch {
    $mode = 'StartupShortcut'
    $startup = [Environment]::GetFolderPath('Startup')
    $shortcutPath = Join-Path $startup "$taskName.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $python
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $RepositoryRoot
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'Robin private real-data explorer on localhost'
    $shortcut.Save()
}

if (-not $SkipStart) {
    if ($mode -eq 'ScheduledTask') {
        Start-ScheduledTask -TaskName $taskName
    }
    else {
        Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $RepositoryRoot -WindowStyle Hidden
    }
}

[pscustomobject]@{
    TaskName = $taskName
    Mode = $mode
    Url = "http://127.0.0.1:$Port/robin-real-data.html"
    DataRoot = $DataRoot
    RefreshSeconds = $RefreshSeconds
}
