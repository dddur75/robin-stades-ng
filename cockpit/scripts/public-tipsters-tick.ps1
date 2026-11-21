param([Parameter(Mandatory=$true)][string]$Directory)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$env:PYTHONPATH=Join-Path $repo 'src'
& (Join-Path $repo '.venv/Scripts/python.exe') -X utf8 -B (Join-Path $PSScriptRoot 'collect-public-tipsters.py') --directory $Directory
exit $LASTEXITCODE
