$ErrorActionPreference='Stop'
try {
 $name='Robin-Tipsters-Forums-V1-20261120'
 $task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
 if(-not $task){@{state='not_found';verifiedAt=[DateTimeOffset]::UtcNow.ToString('o')} | ConvertTo-Json -Compress;exit 0}
 $info=Get-ScheduledTaskInfo -TaskName $name -ErrorAction Stop
 @{state=$task.State.ToString();enabled=[bool]$task.Settings.Enabled;nextRunTime=$info.NextRunTime.ToString('o');lastResult=$info.LastTaskResult;verifiedAt=[DateTimeOffset]::UtcNow.ToString('o')} | ConvertTo-Json -Compress
} catch {@{state='unavailable';verifiedAt=[DateTimeOffset]::UtcNow.ToString('o')} | ConvertTo-Json -Compress}
