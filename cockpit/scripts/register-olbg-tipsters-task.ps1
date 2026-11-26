param([Parameter(Mandatory=$true)][string]$Directory,[switch]$Register,[switch]$Opaque,[string]$Approval,[string]$ApprovalSHA)
$ErrorActionPreference='Stop'
$Directory=(Resolve-Path -LiteralPath $Directory).Path
$repo=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if($Opaque){
 if(!$Approval -or $ApprovalSHA -notmatch '^[a-f0-9]{64}$'){throw 'OPAQUE_APPROVAL_REQUIRED'}
 $p=Get-Content -LiteralPath (Join-Path $Directory 'plan.json') -Raw|ConvertFrom-Json -DateKind String
 $m=Get-Content -LiteralPath (Join-Path $Directory 'manifest.json') -Raw|ConvertFrom-Json -DateKind String
 if($p.taskName -notmatch ('^Robin-OLBG-'+$p.profileId+'-Finite-[A-Za-z0-9_-]+$') -or @($p.slots).Count -ne 12){throw 'FINITE_TASK_SCOPE'}
 $psi=[System.Diagnostics.ProcessStartInfo]::new();$psi.FileName=$p.python.path;$psi.WorkingDirectory=$repo
 $psi.UseShellExecute=$false;$psi.CreateNoWindow=$true;$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
 $psi.Environment['PYTHONPATH']=[string]::Join([IO.Path]::PathSeparator,[string[]]$p.pythonPaths)
 $psi.Environment['PYTHONNOUSERSITE']='1'
 foreach($a in @('-S','-X','utf8','-B',(Join-Path $PSScriptRoot 'collect-olbg-tipsters.py'),'--directory',$Directory,'--opaque','--approval',$Approval,'--approval-sha',$ApprovalSHA,'--campaign-preflight')){$psi.ArgumentList.Add($a)}
 $proc=[Diagnostics.Process]::new();$proc.StartInfo=$psi;[void]$proc.Start()
 $stdout=$proc.StandardOutput.ReadToEndAsync();$stderr=$proc.StandardError.ReadToEndAsync();$proc.WaitForExit()
 $out=$stdout.GetAwaiter().GetResult();$err=$stderr.GetAwaiter().GetResult()
 if($proc.ExitCode -ne 0){throw 'FINITE_PREFLIGHT_REFUSED'}
 if(-not $Register){[ordered]@{state='PREPARED_ONLY';taskName=$p.taskName;triggersMax=12;requests=0}|ConvertTo-Json;return}
 if(Test-Path -LiteralPath (Join-Path $Directory 'campaign-halt.json')){throw 'CAMPAIGN_HALTED'}
 $token=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes([string]$p.slots[0]))).ToLower()
 $canary=Get-Content -LiteralPath (Join-Path $Directory ('slot-result-'+$token+'.json')) -Raw|ConvertFrom-Json
 if($canary.state -ne 'succeeded' -or $canary.job.exit -ne 0 -or $canary.job.timedOut -or !$canary.job.subtreeKillConfirmed -or $canary.picks -lt 1 -or $canary.observationSHA256 -notmatch '^[a-f0-9]{64}$'){throw 'REAL_CANARY_REQUIRED'}
 if(Get-ScheduledTask -TaskName $p.taskName -ErrorAction SilentlyContinue){throw 'FINITE_TASK_ALREADY_EXISTS'}
 $triggers=@($p.slots|Where-Object {[DateTimeOffset]::Parse($_) -gt [DateTimeOffset]::UtcNow}|ForEach-Object {$t=New-ScheduledTaskTrigger -Once -At ([DateTimeOffset]::Parse($_).LocalDateTime);$t.EndBoundary=[DateTimeOffset]::Parse($m.expires_at).LocalDateTime.ToString('yyyy-MM-ddTHH:mm:ss');$t})
 if($triggers.Count -lt 1 -or $triggers.Count -gt 11){throw 'FINITE_FUTURE_SLOTS'}
 $tick=Join-Path $PSScriptRoot 'olbg-tipsters-tick.ps1'
 foreach($v in @($Directory,$Approval,$ApprovalSHA)){if($v.Contains('"')){throw 'ARGUMENT_QUOTE'}}
 $arguments='-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$tick+'" -Directory "'+$Directory+'" -Opaque -Approval "'+$Approval+'" -ApprovalSHA "'+$ApprovalSHA+'"'
 $action=New-ScheduledTaskAction -Execute (Get-Command pwsh.exe).Source -Argument $arguments
 $principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
 $settings=New-ScheduledTaskSettingsSet -Hidden -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 70)
 $task=Register-ScheduledTask -TaskName $p.taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings
 $receipt=[ordered]@{taskName=$task.TaskName;state=$task.State.ToString();triggers=@($task.Triggers).Count;expiresAt=$m.expires_at;renewal=$false;existingTasksChanged=$false;canaryObservationSHA256=$canary.observationSHA256;verifiedAt=(Get-Date).ToUniversalTime().ToString('o')}
 $raw=[Text.UTF8Encoding]::new($false).GetBytes(($receipt|ConvertTo-Json)+"`n")
 $f=[IO.File]::Open((Join-Path $Directory 'native-registration.json'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write)
 try{$f.Write($raw,0,$raw.Length);$f.Flush($true)}finally{$f.Dispose()}
 $receipt|ConvertTo-Json
 return
}

$python=Join-Path $repo '.venv/Scripts/python.exe'
& $python -X utf8 -B (Join-Path $PSScriptRoot 'collect-olbg-tipsters.py') --directory $Directory --validate-only
if($LASTEXITCODE -ne 0){throw 'OLBG_PLAN_INVALID'}
$plan=Get-Content -LiteralPath (Join-Path $Directory 'plan.json') -Raw|ConvertFrom-Json -DateKind String
$manifest=Get-Content -LiteralPath (Join-Path $Directory 'manifest.json') -Raw|ConvertFrom-Json -DateKind String
if($plan.taskName -ne 'Robin-Tipsters-OLBG-V1-20261119'){throw 'OLBG_TASK_SCOPE_INVALID'}
if(-not $Register){return}
if(Get-ScheduledTask -TaskName $plan.taskName -ErrorAction SilentlyContinue){throw 'OLBG_TASK_ALREADY_EXISTS'}
$triggers=@($plan.slots|ForEach-Object{$t=New-ScheduledTaskTrigger -Once -At ([DateTimeOffset]::Parse($_).LocalDateTime);$t.EndBoundary=[DateTimeOffset]::Parse($manifest.expires_at).LocalDateTime.ToString('yyyy-MM-ddTHH:mm:ss');$t})
$tick=Join-Path $PSScriptRoot 'olbg-tipsters-tick.ps1'
$action=New-ScheduledTaskAction -Execute (Get-Command pwsh.exe).Source -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$tick+'" -Directory "'+$Directory+'"')
$principal=New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -Hidden -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
$task=Register-ScheduledTask -TaskName $plan.taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings
$xml=Export-ScheduledTask -TaskName $plan.taskName
[System.IO.File]::WriteAllText((Join-Path $Directory 'installed-task.xml'),$xml,[System.Text.UTF8Encoding]::new($false))
$info=Get-ScheduledTaskInfo -TaskName $plan.taskName
[ordered]@{taskName=$task.TaskName;state=$task.State.ToString();triggers=@($task.Triggers).Count;nextRunTime=$info.NextRunTime.ToString('o');lastResult=$info.LastTaskResult;verifiedAt=(Get-Date).ToUniversalTime().ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $Directory 'native-registration.json') -Encoding utf8
