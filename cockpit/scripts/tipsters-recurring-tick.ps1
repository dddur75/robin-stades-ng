param([Parameter(Mandatory=$true)][string]$Directory)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $repo '.venv/Scripts/python.exe'
$script = Join-Path $PSScriptRoot 'tipsters-recurring.py'
$manifest = Get-Content -LiteralPath (Join-Path $Directory 'manifest.json') -Raw | ConvertFrom-Json
$mode = if ([DateTimeOffset]::UtcNow -ge [DateTimeOffset]::Parse($manifest.expires_at)) { '--close' } else { '--run' }
& $python -X utf8 -B $script --directory $Directory $mode | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Le créneau récurrent a été refusé. Consulter le suivi admin.' }
