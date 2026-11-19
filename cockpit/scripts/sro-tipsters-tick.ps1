param([Parameter(Mandatory=$true)][string]$Directory)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$psi=[System.Diagnostics.ProcessStartInfo]::new()
$psi.FileName=Join-Path $repo '.venv/Scripts/python.exe'
$psi.UseShellExecute=$false
$psi.CreateNoWindow=$true
$psi.RedirectStandardOutput=$true
$psi.RedirectStandardError=$true
$psi.WorkingDirectory=$repo
foreach($arg in @('-X','utf8','-B',(Join-Path $PSScriptRoot 'collect-sro-tipsters.py'),'--directory',$Directory)){$psi.ArgumentList.Add($arg)}
$proc=[System.Diagnostics.Process]::new();$proc.StartInfo=$psi
[void]$proc.Start()
$stdout=$proc.StandardOutput.ReadToEndAsync();$stderr=$proc.StandardError.ReadToEndAsync()
$proc.WaitForExit()
$out=$stdout.GetAwaiter().GetResult();$err=$stderr.GetAwaiter().GetResult()
[ordered]@{at=(Get-Date).ToUniversalTime().ToString('o');exitCode=$proc.ExitCode;stdout=$out;stderr=$err}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $Directory 'task-last.json') -Encoding utf8
exit $proc.ExitCode
