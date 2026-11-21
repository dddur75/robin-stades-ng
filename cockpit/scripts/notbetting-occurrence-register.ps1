[CmdletBinding(DefaultParameterSetName='Validate')]
param(
 [Parameter(Mandatory=$true)][string]$Directory,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$PlanSha256,
 [Parameter(Mandatory=$true)][string]$Python,
 [Parameter(ParameterSetName='Validate')][switch]$ValidateOnly,
 [Parameter(Mandatory=$true,ParameterSetName='Register')][switch]$Register
)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$packet=[IO.Path]::GetFullPath($Directory)
$start=[Diagnostics.ProcessStartInfo]::new()
$start.FileName=[IO.Path]::GetFullPath($Python)
$start.UseShellExecute=$false
$start.CreateNoWindow=$true
$start.RedirectStandardOutput=$true
$start.RedirectStandardError=$true
$start.WorkingDirectory=$repo
$start.Environment['PYTHONPATH']=Join-Path $repo 'src'
foreach($argument in @('-X','utf8','-B',(Join-Path $PSScriptRoot 'notbetting-occurrence-validate.py'),'--directory',$packet,'--plan-sha256',$PlanSha256,'--registration')){$start.ArgumentList.Add($argument)}
$child=[Diagnostics.Process]::new()
$child.StartInfo=$start
try {
 if(-not $child.Start()){throw 'Package validator refused'}
 $stdout=$child.StandardOutput.ReadToEndAsync()
 $stderr=$child.StandardError.ReadToEndAsync()
 if(-not $child.WaitForExit(110000)){$child.Kill($true);$child.WaitForExit();throw 'Validation watchdog'}
 $output=$stdout.GetAwaiter().GetResult()
 $errors=$stderr.GetAwaiter().GetResult()
 if($child.ExitCode -ne 0){throw ('Independent canary receipt or exact package absent. '+$errors)}
 $plan=$output | ConvertFrom-Json -DateKind String
} finally {$child.Dispose()}
$name='Robin-Tipsters-NotBetting-Occurrences-E2-20261121'
if($plan.state -ne 'validated' -or $plan.taskName -ne $name -or $plan.planSha256 -ne $PlanSha256){throw 'Registration contract refused'}
if(-not $Register){$output;return}
if(Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue){throw 'Existing task must never be overwritten'}
$launcher=Join-Path $PSScriptRoot 'notbetting-occurrence-tick.ps1'
$arguments='-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$launcher+'" -Directory "'+$packet+'" -PlanSha256 '+$PlanSha256+' -Python "'+[IO.Path]::GetFullPath($Python)+'"'
$action=New-ScheduledTaskAction -Execute (Get-Command pwsh.exe).Source -Argument $arguments -WorkingDirectory $repo
$triggers=@($plan.slots | ForEach-Object {
 $slot=[DateTimeOffset]::Parse($_,[Globalization.CultureInfo]::InvariantCulture)
 $trigger=New-ScheduledTaskTrigger -Once -At $slot.LocalDateTime
 $trigger.StartBoundary=$slot.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
 $trigger.EndBoundary=$plan.expiresAt
 $trigger
})
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -Hidden -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
$settings.StartWhenAvailable=$false
$settings.WakeToRun=$false
$settings.RestartCount=0
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$definition=New-ScheduledTask -Action $action -Trigger $triggers -Settings $settings -Principal $principal
Register-ScheduledTask -TaskName $name -InputObject $definition -ErrorAction Stop | Select-Object TaskName,State
