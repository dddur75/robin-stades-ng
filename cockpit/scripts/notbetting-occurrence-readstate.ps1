$ErrorActionPreference='Stop'
$name='Robin-Tipsters-NotBetting-Occurrences-E2-20261121'
try {
 $task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
 $clock=[DateTimeOffset]::UtcNow.ToString('o')
 if(-not $task){@{state='not_found';verifiedAt=$clock;active=$false} | ConvertTo-Json -Compress;exit 0}
 $info=Get-ScheduledTaskInfo -TaskName $name -ErrorAction Stop
 $xml=Export-ScheduledTask -TaskName $name -ErrorAction Stop
 $bytes=[Text.Encoding]::UTF8.GetBytes($xml.Replace("`r`n","`n"))
 $digest=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
 @{state=$task.State.ToString();enabled=[bool]$task.Settings.Enabled;verifiedAt=$clock;xmlSha256=$digest;lastResult=$info.LastTaskResult;nextRunTime=$info.NextRunTime.ToString('o');active=$false} | ConvertTo-Json -Compress
} catch {@{state='unavailable';verifiedAt=[DateTimeOffset]::UtcNow.ToString('o');active=$false} | ConvertTo-Json -Compress}
