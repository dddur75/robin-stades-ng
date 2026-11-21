param([Parameter(Mandatory=$true)][string]$Directory,[switch]$Canary)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$config=Get-Content -LiteralPath (Join-Path $Directory 'runtime.json') -Raw|ConvertFrom-Json
$psi=[System.Diagnostics.ProcessStartInfo]::new()
$psi.FileName=$config.python
$psi.UseShellExecute=$false
$psi.CreateNoWindow=$true
$psi.RedirectStandardOutput=$true
$psi.RedirectStandardError=$true
$psi.WorkingDirectory=$repo
$psi.Environment['PYTHONPATH']=Join-Path $repo 'src'
foreach($arg in @('-X','utf8','-B',(Join-Path $PSScriptRoot 'collect-profile-tipsters.py'),'--directory',$Directory)){$psi.ArgumentList.Add($arg)}
if($Canary){$psi.ArgumentList.Add('--canary')}
$proc=[System.Diagnostics.Process]::new();$proc.StartInfo=$psi
[void]$proc.Start()
$stdout=$proc.StandardOutput.ReadToEndAsync();$stderr=$proc.StandardError.ReadToEndAsync()
if(-not $proc.WaitForExit(110000)){
 $proc.Kill($true)
 $proc.WaitForExit()
 $stdout.GetAwaiter().GetResult()|Set-Content -LiteralPath (Join-Path $Directory 'timeout-stdout.txt') -Encoding utf8
 $stderr.GetAwaiter().GetResult()|Set-Content -LiteralPath (Join-Path $Directory 'timeout-stderr.txt') -Encoding utf8
 throw 'PROFILE_CHILD_TIMEOUT_ORPHAN_BLOCKS_RESUMPTION'
}
$out=$stdout.GetAwaiter().GetResult();$err=$stderr.GetAwaiter().GetResult()
[ordered]@{at=[DateTimeOffset]::UtcNow.ToString('o');exitCode=$proc.ExitCode;stdout=$out;stderr=$err}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $Directory 'task-last.json') -Encoding utf8
exit $proc.ExitCode
