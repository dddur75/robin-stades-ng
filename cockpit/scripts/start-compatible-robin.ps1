param([ValidateRange(1024,65535)][int]$Port=4173)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$configPath=Join-Path $root '.ci/local-robin/compatible-runtime.json'
if(-not (Test-Path -LiteralPath $configPath -PathType Leaf)){throw 'ROBIN_LOCAL_RUNTIME_CONFIG_MISSING'}
$config=Get-Content -LiteralPath $configPath -Raw|ConvertFrom-Json
$allowed=@('ROBIN_TIPSTERS_PYTHON','PYTHONPATH','ROBIN_LEGACY_READ_ROOT','ROBIN_PUBLIC_TIPSTERS_DIRECTORY','ROBIN_FORUM_CAMPAIGN_DIRECTORY','ROBIN_TIPSTER_CANDIDATES_DIRECTORY','ROBIN_WORKBOOK_INVENTORY_DIRECTORY','ROBIN_TIPSTERS_DIRECTORY','ROBIN_CONNECTORS_READ_DIRECTORY','ROBIN_RECURRING_CANARY_DIRECTORY','ROBIN_RECURRING_CAMPAIGN_DIRECTORY')
foreach($property in $config.PSObject.Properties){
 if($property.Name -notin $allowed -or -not (Test-Path -LiteralPath $property.Value)){throw 'ROBIN_LOCAL_RUNTIME_PATH_INVALID'}
 [Environment]::SetEnvironmentVariable($property.Name,[string]$property.Value,'Process')
}
if(@($config.PSObject.Properties).Count -ne $allowed.Count){throw 'ROBIN_LOCAL_RUNTIME_CONFIG_INCOMPLETE'}
$base="http://127.0.0.1:$Port"
$claim='DATA.SOURCE_OBSERVATORY.OLBG.FAMILY.E1.20261120'
function Test-CompatibleRobin {
 try{
  $response=Invoke-WebRequest -Uri "$base/api/tipsters/public" -TimeoutSec 5 -SkipHttpErrorCheck
  $value=$response.Content|ConvertFrom-Json
  return $response.StatusCode -eq 200 -and $value.status -eq 'ok' -and $value.schemaVersion -eq 'robin-public-tipsters-v1' -and $claim -in $value.claimIds
 }catch{return $false}
}
if(Test-CompatibleRobin){Write-Output "$base/robin-live";Write-Output "$base/expert/collecte-publique";exit 0}
if(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue){throw 'ROBIN_PORT_OCCUPIED_BY_ANOTHER_BUILD'}
$logs=Join-Path $root '.ci/local-robin'
New-Item -ItemType Directory -Force -Path $logs|Out-Null
$cli=Join-Path $root 'node_modules/vinext/dist/cli.js'
if(-not (Test-Path -LiteralPath $cli -PathType Leaf)){throw 'ROBIN_DEPENDENCIES_MISSING'}
$proc=Start-Process -FilePath (Get-Command node.exe -ErrorAction Stop).Source -ArgumentList @(('"{0}"' -f $cli),'dev','-p',[string]$Port,'-H','127.0.0.1') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs "compatible-$Port.log") -RedirectStandardError (Join-Path $logs "compatible-$Port.err") -PassThru
$proc.Id|Set-Content -LiteralPath (Join-Path $logs "compatible-$Port.pid")
$ready=$false
for($i=0;$i -lt 20;$i++){
 if($proc.HasExited){throw 'ROBIN_SERVER_EXITED'}
 if(Test-CompatibleRobin){$ready=$true;break}
 Start-Sleep -Milliseconds 500
}
if(-not $ready){throw "ROBIN_NOT_READY_INSPECT_LOCAL_LOGS_PID_$($proc.Id)"}
Write-Output "Robin PID $($proc.Id)"
Write-Output "$base/robin-live"
Write-Output "$base/expert/collecte-publique"
