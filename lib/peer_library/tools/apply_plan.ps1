<#
Send card info changes to the library service (admin key of this Windows user).

  powershell -ExecutionPolicy Bypass -File apply_plan.ps1 -Plan plan.json [-Url ...] [-WhatIf]
  powershell -ExecutionPolicy Bypass -File apply_plan.ps1 -ExportIndex index.json

plan.json = [{"id": "...", "fields": {"name": ..., "tags": [...], "types": [...]}}]
(from backfill_plan.py or cards_csv.py). No new versions, files are not touched.
#>
param([string]$Plan, [string]$ExportIndex, [string]$Url, [switch]$WhatIf)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
if (-not $Url) { $Url = (Get-Content (Join-Path $env:APPDATA 'PEER\library.json') -Raw -Encoding UTF8 | ConvertFrom-Json).url }
$Url = $Url.TrimEnd('/')
$blob = [IO.File]::ReadAllBytes((Join-Path $env:APPDATA 'PEER\library_key.bin'))
$key = [Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect(
    $blob, [Text.Encoding]::ASCII.GetBytes('PEER-Library-v1'), 'CurrentUser'))
$h = @{ Authorization = "Bearer $key" }

if ($ExportIndex) {
  Invoke-WebRequest "$Url/index" -Headers $h -OutFile $ExportIndex -UseBasicParsing
  Write-Output "index saved: $ExportIndex"
  return
}
$items = [IO.File]::ReadAllText($Plan, [Text.Encoding]::UTF8) | ConvertFrom-Json
$ok = 0; $bad = 0
foreach ($it in $items) {
  if ($WhatIf) { Write-Output ("would update {0}: {1}" -f $it.id, (($it.fields.PSObject.Properties.Name) -join ',')); continue }
  $body = @{ id = $it.id; fields = $it.fields } | ConvertTo-Json -Depth 6 -Compress
  try {
    Invoke-RestMethod "$Url/card" -Method Post -Headers $h -ContentType 'application/json; charset=utf-8' `
      -Body ([Text.Encoding]::UTF8.GetBytes($body)) | Out-Null
    $ok++
  } catch { $bad++; Write-Output ("FAILED {0}: {1}" -f $it.id, $_.Exception.Message) }
}
$key = $null; $h = $null
Write-Output ("updated {0}, failed {1}" -f $ok, $bad)
