$ErrorActionPreference='Stop'
function Read-TaskState([string]$name) {
try {
 $task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
 if(-not $task){return @{state='not_found';verifiedAt=[DateTimeOffset]::UtcNow.ToString('o')}}
 $info=Get-ScheduledTaskInfo -TaskName $name -ErrorAction Stop
 return @{state=$task.State.ToString();enabled=[bool]$task.Settings.Enabled;nextRunTime=$info.NextRunTime.ToString('o');lastResult=$info.LastTaskResult;verifiedAt=[DateTimeOffset]::UtcNow.ToString('o')}
} catch {return @{state='unavailable';verifiedAt=[DateTimeOffset]::UtcNow.ToString('o')}}
}
$result=Read-TaskState 'Robin-Tipsters-Forums-V1-20261120'
$result.sro=Read-TaskState 'Robin-Tipsters-SRO-V2-20261119'
$result.olbg=Read-TaskState 'Robin-Tipsters-OLBG-V1-20261119'
$result.expansion=Read-TaskState 'Robin-Tipsters-OLBG-Expanded383717-20261120'
$result|ConvertTo-Json -Depth 4 -Compress
