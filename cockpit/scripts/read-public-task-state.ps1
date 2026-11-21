$ErrorActionPreference='Stop'
function Read-TaskState([string]$name) {
try {
 $task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
 if(-not $task){return @{state='not_found';verifiedAt=[DateTimeOffset]::UtcNow.ToString('o')}}
 $info=Get-ScheduledTaskInfo -TaskName $name -ErrorAction Stop
 $nativeState=$task.State.ToString()
 $nextRunTime=if($null -ne $info.NextRunTime){$info.NextRunTime.ToString('o')}else{$null}
 $state=if($nativeState -eq 'Ready' -and $null -eq $nextRunTime){'no_future_run'}else{$nativeState}
 return @{state=$state;nativeState=$nativeState;enabled=[bool]$task.Settings.Enabled;nextRunTime=$nextRunTime;lastResult=$info.LastTaskResult;verifiedAt=[DateTimeOffset]::UtcNow.ToString('o')}
} catch {return @{state='unavailable';verifiedAt=[DateTimeOffset]::UtcNow.ToString('o')}}
}
$result=Read-TaskState 'Robin-Tipsters-Forums-V1-20261120'
$result.sro=Read-TaskState 'Robin-Tipsters-SRO-V2-20261119'
$result.olbg=Read-TaskState 'Robin-Tipsters-OLBG-V1-20261119'
$result.expansion=Read-TaskState 'Robin-Tipsters-OLBG-Expanded383717-20261120'
$result.hepter=Read-TaskState 'Robin-Tipsters-OLBG-Hepter669088-20261120'
$result.roster=Read-TaskState 'Robin-Tipsters-OLBG-Roster42-20261120'
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
