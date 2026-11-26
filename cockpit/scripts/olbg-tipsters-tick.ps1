param([Parameter(Mandatory=$true)][string]$Directory,[switch]$Opaque,[string]$Approval,[string]$ApprovalSHA)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$psi=[System.Diagnostics.ProcessStartInfo]::new()
$psi.UseShellExecute=$false;$psi.CreateNoWindow=$true
$psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true;$psi.WorkingDirectory=$repo
if($Opaque){
 if(!$Approval -or $ApprovalSHA -notmatch '^[a-f0-9]{64}$'){throw 'OPAQUE_APPROVAL_REQUIRED'}
 $plan=Get-Content -LiteralPath (Join-Path $Directory 'plan.json') -Raw|ConvertFrom-Json -DateKind String
 $psi.FileName=$plan.python.path
 $psi.Environment['PYTHONPATH']=[string]::Join([IO.Path]::PathSeparator,[string[]]$plan.pythonPaths)
 $psi.Environment['PYTHONNOUSERSITE']='1'
 $arguments=@('-S','-X','utf8','-B',(Join-Path $PSScriptRoot 'collect-olbg-tipsters.py'),'--directory',$Directory,'--opaque','--approval',$Approval,'--approval-sha',$ApprovalSHA,'--execute','--owned')
}else{
 $psi.FileName=Join-Path $repo '.venv/Scripts/python.exe'
 $arguments=@('-X','utf8','-B',(Join-Path $PSScriptRoot 'collect-olbg-tipsters.py'),'--directory',$Directory)
}
foreach($arg in $arguments){$psi.ArgumentList.Add($arg)}
$proc=[System.Diagnostics.Process]::new();$proc.StartInfo=$psi
[void]$proc.Start()
$stdout=$proc.StandardOutput.ReadToEndAsync();$stderr=$proc.StandardError.ReadToEndAsync()
$proc.WaitForExit()
$out=$stdout.GetAwaiter().GetResult();$err=$stderr.GetAwaiter().GetResult()
if($Opaque){
 [ordered]@{at=(Get-Date).ToUniversalTime().ToString('o');exitCode=$proc.ExitCode;stdoutMetrics=$out;stderrBytes=[Text.Encoding]::UTF8.GetByteCount($err);sourceReady=$false}|ConvertTo-Json
}else{
 [ordered]@{at=(Get-Date).ToUniversalTime().ToString('o');exitCode=$proc.ExitCode;stdout=$out;stderr=$err}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $Directory 'task-last.json') -Encoding utf8
}
exit $proc.ExitCode
