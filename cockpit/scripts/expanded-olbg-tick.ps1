param([Parameter(Mandatory=$true)][string]$Directory)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH=Join-Path $repo 'src'
& (Join-Path $repo '.venv/Scripts/python.exe') -X utf8 -B (Join-Path $PSScriptRoot 'collect-expanded-olbg.py') --directory $Directory
exit $LASTEXITCODE
