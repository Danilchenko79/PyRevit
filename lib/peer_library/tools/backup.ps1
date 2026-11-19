<#
Backup of the PEER family library from the service (Windows PowerShell, .NET TLS).

  powershell -ExecutionPolicy Bypass -File backup.ps1 -Folder D:\Backup\PEER
  [-Url https://peer-library.<you>.workers.dev]

The admin key is read from this Windows user's PEER key store
(%APPDATA%\PEER\library_key.bin, DPAPI) - sign in with PEER -> Library first.
Writes <Folder>\<date>\PEER-Library\ (index.json, changelog.json, every file of
every card, same layout as in R2) and checks every file's SHA-1 against the card.
Keys / proposals / audit live in D1:
  npx wrangler d1 export peer-library --remote --output=<Folder>\<date>\d1.sql
#>
param([Parameter(Mandatory = $true)][string]$Folder, [string]$Url)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

if (-not $Url) {
  $cfg = Get-Content (Join-Path $env:APPDATA 'PEER\library.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  $Url = $cfg.url
}
$Url = $Url.TrimEnd('/')
$blob = [IO.File]::ReadAllBytes((Join-Path $env:APPDATA 'PEER\library_key.bin'))
$key = [Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect(
    $blob, [Text.Encoding]::ASCII.GetBytes('PEER-Library-v1'), 'CurrentUser'))
$h = @{ Authorization = "Bearer $key" }

$who = Invoke-RestMethod "$Url/auth" -Headers $h
$root = Join-Path $Folder ((Get-Date -Format 'yyyy-MM-dd') + '\PEER-Library')
New-Item -ItemType Directory -Force $root | Out-Null
Invoke-WebRequest "$Url/index" -Headers $h -OutFile (Join-Path $root 'index.json') -UseBasicParsing
Invoke-WebRequest "$Url/changelog" -Headers $h -OutFile (Join-Path $root 'changelog.json') -UseBasicParsing
$index = Get-Content (Join-Path $root 'index.json') -Raw -Encoding UTF8 | ConvertFrom-Json

$hashField = @{ '.rfa' = 'sha1'; '.png' = 'png_sha1'; '.txt' = 'catalog_sha1' }
$n = 0; $bad = 0
foreach ($card in $index.families) {
  if (-not $card.files) { continue }
  foreach ($p in $card.files.PSObject.Properties) {
    $rel = $p.Value
    $target = Join-Path $root ($rel -replace '/', '\')
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    $enc = ($rel -split '/' | ForEach-Object { [Uri]::EscapeDataString($_) }) -join '/'
    Invoke-WebRequest "$Url/file/$enc" -Headers $h -OutFile $target -UseBasicParsing
    $n++
    $want = $card.($hashField[$p.Name])
    if ($want -and ((Get-FileHash $target -Algorithm SHA1).Hash.ToLower() -ne $want)) {
      $bad++; Write-Output "HASH MISMATCH $rel"
    }
  }
}
$key = $null; $h = $null
Write-Output ("{0}: {1} families, {2} files, {3} mismatches -> {4}" -f $who.name, $index.count, $n, $bad, $root)
