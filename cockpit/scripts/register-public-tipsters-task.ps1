param([Parameter(Mandatory=$true)][string]$Directory,[switch]$Register)
$ErrorActionPreference='Stop'
$taskDirectory=[IO.Path]::GetFullPath($Directory)
$taskPlan=Get-Content -LiteralPath (Join-Path $taskDirectory 'plan.json') -Raw | ConvertFrom-Json -DateKind String
if($taskPlan.id -ne 'TIPSTERS-FORUMS-V1-20261120'){throw 'Unknown campaign'}
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$python=Join-Path $repo '.venv/Scripts/python.exe'
$script=Join-Path $PSScriptRoot 'collect-public-tipsters.py'
$arguments='-X utf8 -B "'+$script+'" --directory "'+$taskDirectory+'"'
$launcher=Join-Path $PSScriptRoot 'public-tipsters-tick.ps1'
$hiddenArguments='-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$launcher+'" -Directory "'+$taskDirectory+'"'
$action=New-ScheduledTaskAction -Execute (Get-Command pwsh.exe).Source -Argument $hiddenArguments -WorkingDirectory $repo
$triggers=@($taskPlan.slots | ForEach-Object {
 $localSlot=[DateTimeOffset]::Parse($_,[Globalization.CultureInfo]::InvariantCulture).LocalDateTime
 $trigger=New-ScheduledTaskTrigger -Once -At $localSlot
 $trigger.EndBoundary=[DateTimeOffset]::Parse($taskPlan.expiresAt,[Globalization.CultureInfo]::InvariantCulture).LocalDateTime.ToString('s')
 $trigger
})
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -DeleteExpiredTaskAfter (New-TimeSpan -Hours 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$definition=New-ScheduledTask -Action $action -Trigger $triggers -Settings $settings -Principal $principal
if(-not $Register){$definition | Export-ScheduledTask;return}
$grant=Get-Content -LiteralPath (Join-Path $taskDirectory 'authorization.json') -Raw | ConvertFrom-Json
$env:PYTHONPATH=Join-Path $repo 'src'
# The runner checks exact text, plan hash, code pins, dates and bounds before all GETs.
& $python -X utf8 -B $script --directory $taskDirectory --validate-only
if($LASTEXITCODE -ne 0){throw 'Campaign validation refused'}
if($grant.statement -ne $taskPlan.authorizationText){throw 'Exact owner statement absent'}
Register-ScheduledTask -TaskName $taskPlan.taskName -InputObject $definition -ErrorAction Stop | Select-Object TaskName,State
