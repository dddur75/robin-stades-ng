param([Parameter(Mandatory=$true)][string]$Directory, [switch]$Install)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$manifestPath = Join-Path $Directory 'manifest.json'
$planPath = Join-Path $Directory 'plan.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json -DateKind String
$plan = Get-Content -LiteralPath $planPath -Raw | ConvertFrom-Json -DateKind String
$name = 'Robin-Tipsters-Recurring-V1-20261119'
if ($manifest.external_effects.scheduled_task -ne $name -or $plan.intervalSeconds -ne 7200 -or $plan.slots.Count -ne 84) { throw 'Campagne inattendue.' }
foreach ($pin in $plan.codePins.PSObject.Properties) {
    $bytes = [IO.File]::ReadAllText((Join-Path $repo $pin.Name)).Replace("`r`n", "`n")
    $digest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($bytes))).ToLowerInvariant()
    if ($digest -ne $pin.Value) { throw "Empreinte de code différente : $($pin.Name)" }
}
$start = [DateTimeOffset]::Parse($plan.startsAt)
$end = [DateTimeOffset]::Parse($plan.expiresAt)
$launcher = Join-Path $PSScriptRoot 'tipsters-recurring-tick.ps1'
$action = New-ScheduledTaskAction -Execute (Join-Path $PSHOME 'pwsh.exe') -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -Directory "{1}"' -f $launcher,$Directory) -WorkingDirectory $repo
$tick = New-ScheduledTaskTrigger -Once -At $start.LocalDateTime -RepetitionInterval (New-TimeSpan -Hours 2) -RepetitionDuration (New-TimeSpan -Days 7)
$tick.StartBoundary = $start.ToString('yyyy-MM-ddTHH:mm:sszzz')
$tick.EndBoundary = $end.ToString('yyyy-MM-ddTHH:mm:sszzz')
$close = New-ScheduledTaskTrigger -Once -At $end.LocalDateTime
$close.StartBoundary = $end.ToString('yyyy-MM-ddTHH:mm:sszzz')
$close.EndBoundary = $end.AddMinutes(5).ToString('yyyy-MM-ddTHH:mm:sszzz')
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -DeleteExpiredTaskAfter (New-TimeSpan -Days 1) -DisallowDemandStart
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$definition = New-ScheduledTask -Action $action -Trigger @($tick,$close) -Settings $settings -Principal $principal
if (-not $Install) { [pscustomobject]@{Task=$name;Slots=84;Start=$plan.startsAt;End=$plan.expiresAt;RequestsMax=504;CatchUp=$definition.Settings.StartWhenAvailable;Installed=$false}; exit 0 }
$authority = Get-Content -LiteralPath (Join-Path $Directory 'authorization.json') -Raw | ConvertFrom-Json
& (Join-Path $repo '.venv/Scripts/python.exe') -X utf8 -B (Join-Path $PSScriptRoot 'tipsters-recurring.py') --directory $Directory --check-authority | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Validation Python de l'autorite et du plan refusee." }
$hash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($authority.decision -ne 'AUTHORIZED' -or $authority.manifestSha256 -ne $hash -or [string]::IsNullOrWhiteSpace($authority.decisionReference)) { throw 'Autorisation manquante ou incompatible.' }
if ([DateTimeOffset]::UtcNow -ge $start) { throw 'Début atteint : préparer un nouveau plan.' }
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { throw 'Tâche déjà présente : aucun remplacement automatique.' }
Register-ScheduledTask -TaskName $name -InputObject $definition -ErrorAction Stop
