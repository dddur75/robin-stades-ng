$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$url = 'http://127.0.0.1:4173/expert/tipsters'
try {
    $response = Invoke-WebRequest -Uri 'http://127.0.0.1:4173/api/tipsters' -TimeoutSec 3 -SkipHttpErrorCheck
    $data = $response.Content | ConvertFrom-Json
    if ($data.schemaVersion -eq 'robin-tipsters-pilot-v1' -or $data.status -in @('unavailable', 'invalid', 'updating')) {
        Write-Output $url
        exit 0
    }
} catch {
    # An absent local server is started below.
}
$node = (Get-Command node.exe -ErrorAction Stop).Source
$cli = Join-Path $root 'node_modules/vinext/dist/cli.js'
if (-not (Test-Path -LiteralPath $cli -PathType Leaf)) {
    throw 'Les dépendances du cockpit doivent être installées dans ce dossier.'
}
$logs = Join-Path $root '.ci/local-robin'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$process = Start-Process -FilePath $node -ArgumentList @(('"{0}"' -f $cli), 'dev', '-p', '4173', '-H', '127.0.0.1') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'server.log') -RedirectStandardError (Join-Path $logs 'server.err') -PassThru
Write-Output "Robin démarre sous le processus $($process.Id)."
Write-Output $url
