param([Parameter(Mandatory=$true)][string]$Directory,[switch]$Register)
$ErrorActionPreference='Stop'
$Directory=(Resolve-Path -LiteralPath $Directory).Path
$repo=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH=Join-Path $repo 'src'
& (Join-Path $repo '.venv/Scripts/python.exe') -X utf8 -B (Join-Path $PSScriptRoot 'collect-expanded-olbg.py') --directory $Directory --validate-only
if($LASTEXITCODE -ne 0){throw 'EXPANDED_OLBG_PLAN_INVALID'}
$plan=Get-Content -LiteralPath (Join-Path $Directory 'plan.json') -Raw | ConvertFrom-Json -DateKind String
$manifest=Get-Content -LiteralPath (Join-Path $Directory 'manifest.json') -Raw | ConvertFrom-Json -DateKind String
if($plan.taskName -ne 'Robin-Tipsters-OLBG-Expanded383717-20261120'){throw 'EXPANDED_OLBG_TASK_SCOPE_INVALID'}
if(-not $Register){return}
if(Get-ScheduledTask -TaskName $plan.taskName -ErrorAction SilentlyContinue){throw 'EXPANDED_OLBG_TASK_EXISTS'}
$triggers=@($plan.slots|ForEach-Object{$t=New-ScheduledTaskTrigger -Once -At ([DateTimeOffset]::Parse($_).LocalDateTime);$t.EndBoundary=[DateTimeOffset]::Parse($manifest.expires_at).LocalDateTime.ToString('yyyy-MM-ddTHH:mm:ss');$t})
$tick=Join-Path $PSScriptRoot 'expanded-olbg-tick.ps1'
$action=New-ScheduledTaskAction -Execute (Get-Command pwsh.exe).Source -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$tick+'" -Directory "'+$Directory+'"')
$principal=New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -Hidden -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 3)
$task=Register-ScheduledTask -TaskName $plan.taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings
[IO.File]::WriteAllText((Join-Path $Directory 'installed-task.xml'),(Export-ScheduledTask -TaskName $plan.taskName),[Text.UTF8Encoding]::new($false))
$info=Get-ScheduledTaskInfo -TaskName $plan.taskName
@{taskName=$task.TaskName;state=$task.State.ToString();enabled=[bool]$task.Settings.Enabled;nextRunTime=$info.NextRunTime.ToString('o');verifiedAt=[DateTimeOffset]::UtcNow.ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $Directory 'native-registration.json') -Encoding utf8
