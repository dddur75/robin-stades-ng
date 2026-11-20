param([Parameter(Mandatory=$true)][string]$Directory,[switch]$Register)
$ErrorActionPreference='Stop'
$Directory=(Resolve-Path -LiteralPath $Directory).Path
$repo=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$config=Get-Content -LiteralPath (Join-Path $Directory 'runtime.json') -Raw|ConvertFrom-Json
$env:PYTHONPATH=Join-Path $repo 'src'
& $config.python -X utf8 -B (Join-Path $PSScriptRoot 'collect-profile-tipsters.py') --directory $Directory --validate-only
if($LASTEXITCODE -ne 0){throw 'PROFILE_PLAN_INVALID'}
$plan=Get-Content -LiteralPath (Join-Path $Directory 'plan.json') -Raw|ConvertFrom-Json -DateKind String
$manifest=Get-Content -LiteralPath (Join-Path $Directory 'manifest.json') -Raw|ConvertFrom-Json -DateKind String
if($plan.taskName -ne 'Robin-Tipsters-OLBG-Hepter669088-20261120'){throw 'PROFILE_TASK_SCOPE_INVALID'}
if(-not $Register){return}
& $config.python -X utf8 -B (Join-Path $PSScriptRoot 'collect-profile-tipsters.py') --directory $Directory --validate-registration
if($LASTEXITCODE -ne 0){throw 'PROFILE_CANARY_NATIVE_RECEIPTS_INVALID'}
if(Get-ScheduledTask -TaskName $plan.taskName -ErrorAction SilentlyContinue){throw 'PROFILE_TASK_ALREADY_EXISTS'}
$receipt=Get-Content -LiteralPath (Join-Path $Directory 'canary-recette.json') -Raw|ConvertFrom-Json
if($receipt.status -ne 'PASS' -or $receipt.taskRegistrationAuthorized -ne $true -or $receipt.planSha256 -ne $manifest.source_hash){throw 'PROFILE_CANARY_NOT_ACCEPTED'}
if(@($plan.slots|Where-Object{[DateTimeOffset]::Parse($_) -le [DateTimeOffset]::UtcNow}).Count){throw 'PROFILE_TRIGGER_ALREADY_PAST'}
$triggers=@($plan.slots|ForEach-Object{$t=New-ScheduledTaskTrigger -Once -At ([DateTimeOffset]::Parse($_).LocalDateTime);$t.EndBoundary=[DateTimeOffset]::Parse($manifest.expires_at).LocalDateTime.ToString('yyyy-MM-ddTHH:mm:ss');$t})
$tick=Join-Path $PSScriptRoot 'profile-tipsters-tick.ps1'
$action=New-ScheduledTaskAction -Execute (Get-Command pwsh.exe).Source -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$tick+'" -Directory "'+$Directory+'"')
$principal=New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -Hidden -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
$task=Register-ScheduledTask -TaskName $plan.taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings
$xml=Export-ScheduledTask -TaskName $plan.taskName
[IO.File]::WriteAllText((Join-Path $Directory 'installed-task.xml'),$xml,[Text.UTF8Encoding]::new($false))
$info=Get-ScheduledTaskInfo -TaskName $plan.taskName
[ordered]@{taskName=$task.TaskName;state=$task.State.ToString();triggers=@($task.Triggers).Count;nextRunTime=$info.NextRunTime.ToString('o');lastResult=$info.LastTaskResult;verifiedAt=[DateTimeOffset]::UtcNow.ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $Directory 'native-registration.json') -Encoding utf8
