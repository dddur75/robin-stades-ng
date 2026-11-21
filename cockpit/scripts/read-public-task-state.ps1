$ErrorActionPreference='Stop'
function Test-RosterNextXml([string]$Xml,[string]$Expected) {
 if($Expected -cnotmatch '^[0-9a-f]{64}$'){return $false}
 $bytes=[Text.Encoding]::UTF8.GetBytes($Xml.Replace("`r`n","`n"))
 return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant() -ceq $Expected
}
function Resolve-PublicTaskState([string]$NativeState,[bool]$HasNextRun,[bool]$ExecutablePresent) {
 if($NativeState -eq 'Ready' -and -not $HasNextRun){return 'no_future_run'}
 if($NativeState -eq 'Ready' -and -not $ExecutablePresent){return 'invalid_package'}
 return $NativeState
}
function Read-TaskState([string]$name) {
try {
$task=Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
 if(-not $task){return @{state='not_found';verifiedAt=[DateTimeOffset]::UtcNow.ToString('o')}}
 $info=Get-ScheduledTaskInfo -TaskName $name -TaskPath '\' -ErrorAction Stop
 $nativeState=$task.State.ToString()
 $nextRunTime=if($null -ne $info.NextRunTime){$info.NextRunTime.ToString('o')}else{$null}
 $actions=@($task.Actions)
 $executablePresent=$actions.Count -gt 0 -and @($actions|Where-Object {-not $_.Execute -or -not (Test-Path -LiteralPath $_.Execute -PathType Leaf)}).Count -eq 0
 $state=Resolve-PublicTaskState $nativeState ($null -ne $nextRunTime) $executablePresent
 return @{state=$state;nativeState=$nativeState;enabled=[bool]$task.Settings.Enabled;actionExecutablePresent=$executablePresent;nextRunTime=$nextRunTime;lastResult=$info.LastTaskResult;verifiedAt=[DateTimeOffset]::UtcNow.ToString('o')}
} catch {return @{state='unavailable';verifiedAt=[DateTimeOffset]::UtcNow.ToString('o')}}
}
function Test-SroNextTaskPackage([string]$Xml,[object]$Config,[object]$Task,[object]$State,[DateTimeOffset]$Now=[DateTimeOffset]::UtcNow) {
 try {
  $keys=@('directory','readerSha256','sourceDecisionSha256','privacyDecisionSha256','scaleDecisionSha256','taskDecisionSha256','dataDecisionSha256','nativeXmlSha256')
  if(@($Config.PSObject.Properties.Name).Count -ne 8){return $false}
  foreach($key in $keys){if($key -cnotin $Config.PSObject.Properties.Name){return $false}}
  foreach($key in $keys|Where-Object {$_ -ne 'directory'}){if($Config.$key -isnot [string] -or $Config.$key -cnotmatch '^[0-9a-f]{64}$'){return $false}}
  $expected='C:/Users/ddura/.codex/worktrees/robin-roster-successor-e1/Robin V3/cockpit/.ci/sro-next3-e2-r2-20261121/runtime'
  if([IO.Path]::GetFullPath($Config.directory) -ine [IO.Path]::GetFullPath($expected)){return $false}
  if($Task.TaskName -cne 'Robin-Tipsters-SRO-Next3-20261121' -or $Task.TaskPath -cne '\'){return $false}
  if($State.actionExecutablePresent -isnot [bool] -or $State.enabled -isnot [bool] -or $State.actionExecutablePresent -ne $true -or $State.enabled -ne $true){return $false}
  $next=[DateTimeOffset]::Parse($State.nextRunTime)
  if($next -le $Now -or $next -ge [DateTimeOffset]::Parse('2026-11-22T08:10:00Z')){return $false}
  return Test-RosterNextXml $Xml $Config.nativeXmlSha256
 } catch {return $false}
}
$result=Read-TaskState 'Robin-Tipsters-Forums-V1-20261120'
$result.sro=Read-TaskState 'Robin-Tipsters-SRO-V2-20261119'
$result.sroNext=Read-TaskState 'Robin-Tipsters-SRO-Next3-20261121'
if($result.sroNext.state -in @('Ready','Running')){
 try {
  $config=Get-Content -LiteralPath (Join-Path $PSScriptRoot '../.ci/sro-next-bridge-20261121/config.json') -Raw|ConvertFrom-Json
  $task=Get-ScheduledTask -TaskName 'Robin-Tipsters-SRO-Next3-20261121' -TaskPath '\' -ErrorAction Stop
  $xml=Export-ScheduledTask -TaskName 'Robin-Tipsters-SRO-Next3-20261121' -TaskPath '\' -ErrorAction Stop
  if(-not(Test-SroNextTaskPackage $xml $config $task $result.sroNext)){
   $result.sroNext.state='invalid_package';$result.sroNext.enabled=$false
  }
 } catch {$result.sroNext.state='unavailable';$result.sroNext.enabled=$false}
}
$result.olbg=Read-TaskState 'Robin-Tipsters-OLBG-V1-20261119'
$result.expansion=Read-TaskState 'Robin-Tipsters-OLBG-Expanded383717-20261120'
$result.hepter=Read-TaskState 'Robin-Tipsters-OLBG-Hepter669088-20261120'
$result.roster=Read-TaskState 'Robin-Tipsters-OLBG-Roster42-20261120'
$result.rosterNext=Read-TaskState 'Robin-Tipsters-OLBG-Roster42-Next3-20261121'
if($result.rosterNext.state -in @('Ready','Running')){
 try {
  $config=Get-Content -LiteralPath (Join-Path $PSScriptRoot '../.ci/roster-next-bridge-20261121/config.json') -Raw|ConvertFrom-Json
  $xml=Export-ScheduledTask -TaskName 'Robin-Tipsters-OLBG-Roster42-Next3-20261121' -TaskPath '\' -ErrorAction Stop
  if(-not(Test-RosterNextXml $xml $config.nativeXmlSha256)){
   $result.rosterNext.state='invalid_package';$result.rosterNext.enabled=$false
  }
 } catch {$result.rosterNext.state='unavailable';$result.rosterNext.enabled=$false}
}
$result.notbetting=Read-TaskState 'Robin-Tipsters-NotBetting-Occurrences-E2-20261121'
try {
 $xml=Export-ScheduledTask -TaskName 'Robin-Tipsters-NotBetting-Occurrences-E2-20261121' -ErrorAction Stop
 $bytes=[Text.Encoding]::UTF8.GetBytes($xml.Replace("`r`n","`n"))
 $digest=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
 if($digest -ne '7503cdd2197e6eb0459e3cbd07465416d90c732ea233d7fdf2435a00adf81de6'){
  $result.notbetting.state='invalid_package';$result.notbetting.enabled=$false
 }
} catch {$result.notbetting.state='unavailable';$result.notbetting.enabled=$false}
$result|ConvertTo-Json -Depth 4 -Compress
