param(
 [Parameter(Mandatory=$true)][string]$Directory,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$PlanSha256,
 [Parameter(Mandatory=$true)][string]$Python
)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$start=[Diagnostics.ProcessStartInfo]::new()
$start.FileName=[IO.Path]::GetFullPath($Python)
$start.UseShellExecute=$false
$start.CreateNoWindow=$true
$start.RedirectStandardOutput=$true
$start.RedirectStandardError=$true
$start.WorkingDirectory=$repo
$start.Environment['PYTHONPATH']=Join-Path $repo 'src'
foreach($argument in @('-X','utf8','-B',(Join-Path $PSScriptRoot 'notbetting-occurrence-collect.py'),'--directory',[IO.Path]::GetFullPath($Directory),'--plan-sha256',$PlanSha256,'--slot','auto','--execute')){
 $start.ArgumentList.Add($argument)
}
$child=[Diagnostics.Process]::new()
$child.StartInfo=$start
try {
 if(-not $child.Start()){throw 'NotBetting child refused'}
 $stdout=$child.StandardOutput.ReadToEndAsync()
 $stderr=$child.StandardError.ReadToEndAsync()
 if(-not $child.WaitForExit(110000)){$child.Kill($true);$child.WaitForExit();throw 'NotBetting watchdog110s; permanent slot lock requires review'}
 [Console]::Out.Write($stdout.GetAwaiter().GetResult())
 [Console]::Error.Write($stderr.GetAwaiter().GetResult())
 exit $child.ExitCode
} finally {$child.Dispose()}
