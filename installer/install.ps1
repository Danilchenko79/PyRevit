param(
  [string]$Url = '',                    # PEER service address (install.bat passes it)
  [ValidateSet('stable', 'beta')] [string]$Channel = 'stable',
  [string]$ExtDir = '',                 # default: %APPDATA%\pyRevit\Extensions\PEER.extension
  [switch]$Quiet                        # no questions (tests): key from $env:PEER_INSTALL_KEY
)
# PEER for pyRevit - install / repair. Needs a personal PEER key (or sends an access request).
# The key is checked on the PEER service, saved encrypted for this Windows user (DPAPI) and
# never shown. PEER is downloaded from the service with that key; later Revit keeps it up to date.
# This file contains no PEER code and no keys.
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.Security
Add-Type -AssemblyName System.IO.Compression.FileSystem

$peerDir = Join-Path $env:APPDATA 'PEER'
$keyFile = Join-Path $peerDir 'library_key.bin'
$reqFile = Join-Path $peerDir 'library_request.bin'
$cfgFile = Join-Path $peerDir 'library.json'
$entropy = [Text.Encoding]::ASCII.GetBytes('PEER-Library-v1')       # same as lib/peer_library/keystore.py
if (-not $ExtDir) { $ExtDir = Join-Path $env:APPDATA 'pyRevit\Extensions\PEER.extension' }
$work = Join-Path $env:LOCALAPPDATA 'PEER\Update'

function Say([string]$t) { Write-Host $t }
function Stop-Install([string]$t) { Write-Host ''; Write-Host ('[STOP] ' + $t) -ForegroundColor Red; exit 1 }

function Protect-Text([string]$text) {
  [Security.Cryptography.ProtectedData]::Protect([Text.Encoding]::UTF8.GetBytes($text), $entropy, 'CurrentUser')
}
function Unprotect-File([string]$path) {
  try {
    [Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect(
      [IO.File]::ReadAllBytes($path), $entropy, 'CurrentUser'))
  } catch { $null }
}

# One call to the service. Returns @{ status; data } - never throws on an HTTP answer.
function Invoke-Peer([string]$method, [string]$path, [string]$key, $body, [string]$outFile) {
  $req = [Net.HttpWebRequest]::Create($Url.TrimEnd('/') + $path)
  $req.Method = $method; $req.Timeout = 120000; $req.UserAgent = 'PEER-Installer'
  if ($key) { $req.Headers.Add('Authorization', 'Bearer ' + $key) }
  if ($null -ne $body) {
    $bytes = [Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Compress))
    $req.ContentType = 'application/json'; $req.ContentLength = $bytes.Length
    $s = $req.GetRequestStream(); $s.Write($bytes, 0, $bytes.Length); $s.Close()
  }
  try { $resp = $req.GetResponse() }
  catch [Net.WebException] {
    $r = $_.Exception.Response
    if ($null -eq $r) { return @{ status = 0; data = $null; error = $_.Exception.Message } }
    $text = (New-Object IO.StreamReader($r.GetResponseStream())).ReadToEnd(); $code = [int]$r.StatusCode; $r.Close()
    $msg = $text; try { $msg = ($text | ConvertFrom-Json).error } catch { }
    return @{ status = $code; data = $null; error = $msg }
  }
  try {
    if ($outFile) {
      $fs = [IO.File]::Create($outFile)
      try { $resp.GetResponseStream().CopyTo($fs) } finally { $fs.Close() }
      return @{ status = 200; data = $outFile }
    }
    $text = (New-Object IO.StreamReader($resp.GetResponseStream(), [Text.Encoding]::UTF8)).ReadToEnd()
    return @{ status = 200; data = ($text | ConvertFrom-Json) }
  } finally { $resp.Close() }
}

function Get-Sha1([string]$path) { (Get-FileHash -Algorithm SHA1 -LiteralPath $path).Hash.ToLower() }

function Compare-Version([string]$a, [string]$b) {
  $x = @($a.Split('.') | ForEach-Object { [int]$_ }); $y = @($b.Split('.') | ForEach-Object { [int]$_ })
  for ($i = 0; $i -lt [Math]::Max($x.Count, $y.Count); $i++) {
    $p = 0; $q = 0
    if ($i -lt $x.Count) { $p = $x[$i] }
    if ($i -lt $y.Count) { $q = $y[$i] }
    if ($p -ne $q) { return [Math]::Sign($p - $q) }
  }
  0
}

# ---- 0. address, pyRevit, Revit ------------------------------------------------------
Say 'PEER for pyRevit - install'
Say '---------------------------'
if (-not $Url -and (Test-Path $cfgFile)) { try { $Url = (Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json).url } catch { } }
if (-not $Url) { Stop-Install 'The PEER service address is not set. Use install.bat from the PEER site.' }
$u = $null
if (-not [Uri]::TryCreate($Url, 'Absolute', [ref]$u) -or -not ($u.Scheme -eq 'https' -or ($u.Scheme -eq 'http' -and $u.Host -eq '127.0.0.1'))) {
  Stop-Install 'The PEER service address must start with https://'
}

$pyrevit = @((Join-Path $env:APPDATA 'pyRevit-Master'), (Join-Path $env:ProgramFiles 'pyRevit-Master'),
             (Join-Path $env:ProgramData 'pyRevit-Master')) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $pyrevit -and -not $Quiet) {
  Stop-Install ('pyRevit is not installed on this computer. Install pyRevit 5.2 first ' +
                '(https://github.com/pyrevitlabs/pyRevit/releases), then run this file again.')
}
if (-not $Quiet -and (Get-Process Revit -ErrorAction SilentlyContinue)) {
  Say ''
  Say 'Revit is running. Close Revit before installing (its files may be in use).'
  if ((Read-Host 'Revit is closed now? (yes / no)') -ne 'yes') { Stop-Install 'Close Revit and run this file again.' }
}

# ---- 1. the key ----------------------------------------------------------------------
New-Item -ItemType Directory -Force $peerDir | Out-Null
$key = $null
if (Test-Path $keyFile) {
  $key = Unprotect-File $keyFile
  if ($key) {
    $r = Invoke-Peer 'GET' '/auth' $key $null $null
    if ($r.status -eq 200) { Say ('Signed in as ' + $r.data.name + ' (key already on this computer).') }
    elseif ($r.status -eq 0) { Stop-Install ('No connection to the PEER service: ' + $r.error) }
    else { $key = $null; Say 'The key saved on this computer is not valid any more.' }
  }
}
if (-not $key -and (Test-Path $reqFile)) {             # an access request sent earlier
  $parts = (Unprotect-File $reqFile); if ($parts) { $parts = $parts.Split("`n") }
  if ($parts -and $parts.Count -ge 2) {
    $r = Invoke-Peer 'POST' '/access/status' $null @{ id = $parts[0]; token = $parts[1] } $null
    if ($r.status -eq 200 -and $r.data.status -eq 'delivered' -and $r.data.key) {
      $key = $r.data.key; Remove-Item $reqFile -Force
      Say ('Your access request was approved. Welcome, ' + $r.data.name + '!')
    } elseif ($r.status -eq 200 -and $r.data.status -eq 'pending') {
      Stop-Install 'Your access request is still waiting for a PEER admin. Run this file again after it is approved.'
    } else { Remove-Item $reqFile -Force -ErrorAction SilentlyContinue }
  }
}
if (-not $key -and $Quiet) { $key = $env:PEER_INSTALL_KEY }
if (-not $key) {
  Say ''
  Say 'PEER works with a personal key.'
  Say '  1 - I have a key (from a PEER admin)'
  Say '  2 - I have no key: send an access request'
  $choice = Read-Host 'Choose 1 or 2'
  if ($choice -eq '2') {
    $name = (Read-Host 'Your name (as colleagues know you)').Trim()
    if ($name.Length -lt 2) { Stop-Install 'Write your name.' }
    $note = (Read-Host 'Note for the admin (optional)').Trim()
    $r = Invoke-Peer 'POST' '/access/request' $null @{ name = $name; note = $note } $null
    if ($r.status -ne 200) { Stop-Install ('The request was not sent: ' + $r.error) }
    [IO.File]::WriteAllBytes($reqFile, (Protect-Text ($r.data.id + "`n" + $r.data.token + "`n" + $name)))
    Say ''
    Say 'Request sent. A PEER admin approves it in Revit (PEER > Keys).'
    Say 'Then run this file again - PEER installs without any key to copy.'
    exit 0
  }
  $secure = Read-Host 'Paste the key (it is not shown) and press Enter' -AsSecureString
  $key = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)).Trim()
}
if (-not $key.StartsWith('peer_')) { Stop-Install 'The key starts with peer_ - paste it as you got it.' }
$r = Invoke-Peer 'GET' '/auth' $key $null $null
if ($r.status -eq 0) { Stop-Install ('No connection to the PEER service: ' + $r.error) }
if ($r.status -ne 200) { Stop-Install 'This key is not valid. Ask a PEER admin for a new one, or request access.' }
[IO.File]::WriteAllBytes($keyFile, (Protect-Text $key))
$who = $r.data

# ---- 2. settings of this computer ----------------------------------------------------
$cfg = @{}
if (Test-Path $cfgFile) { try { (Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $cfg[$_.Name] = $_.Value } } catch { } }
$cfg['backend'] = 'http'; $cfg['url'] = $Url.TrimEnd('/'); $cfg['user'] = $who.name; $cfg['role'] = $who.role
$cfg['last_ok'] = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
$cfg['channel'] = $Channel
[IO.File]::WriteAllText($cfgFile, ($cfg | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))

# ---- 3. the package ------------------------------------------------------------------
$r = Invoke-Peer 'GET' '/release/ext/manifest' $key $null $null
if ($r.status -ne 200) { Stop-Install ('Could not read the list of PEER versions: ' + $r.error) }
$m = $r.data
$want = $m.channels.stable
if ($Channel -eq 'beta' -and $m.channels.beta -and (-not $want -or (Compare-Version $m.channels.beta $want) -ge 0)) { $want = $m.channels.beta }
if (-not $want) { Stop-Install 'No PEER package is published yet. Ask a PEER admin.' }
$entry = $m.versions | Where-Object { $_.version -eq $want } | Select-Object -First 1
if (-not $entry) { Stop-Install ('Version ' + $want + ' is not on the service any more. Ask a PEER admin.') }
New-Item -ItemType Directory -Force $work | Out-Null
$zip = Join-Path $work ('ext-' + $want + '.zip')
if (-not (Test-Path $zip) -or (Get-Sha1 $zip) -ne $entry.sha1) {
  Say ('Downloading PEER ' + $want + ' ...')
  $r = Invoke-Peer 'GET' ('/release/ext/file/' + $want) $key $null $zip
  if ($r.status -ne 200) { Stop-Install ('Download failed: ' + $r.error) }
  if ((Get-Sha1 $zip) -ne $entry.sha1) { Remove-Item $zip -Force; Stop-Install 'The downloaded file is damaged. Run this file again.' }
}

# ---- 4. put it in place (an existing folder is kept next to it as a backup) -----------
$stage = Join-Path $work 'install-stage'
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
[IO.Compression.ZipFile]::ExtractToDirectory($zip, $stage)
if (-not (Test-Path (Join-Path $stage 'version.json')) -or -not (Test-Path (Join-Path $stage 'startup.py'))) {
  Stop-Install 'The package is not a PEER package.'
}
$backup = $null
if (Test-Path $ExtDir) {
  $backup = $ExtDir + '.old-' + (Get-Date).ToString('yyyyMMdd-HHmmss')
  try { Move-Item -LiteralPath $ExtDir -Destination $backup }
  catch { Stop-Install ('The PEER folder is in use (is Revit closed?): ' + $ExtDir) }
}
New-Item -ItemType Directory -Force (Split-Path $ExtDir) | Out-Null
Move-Item -LiteralPath $stage -Destination $ExtDir
if ($backup) {
  # pyRevit loads every *.extension folder it finds: the backup must not look like one
  $safe = Join-Path (Split-Path $ExtDir) ('PEER_backup_' + (Get-Date).ToString('yyyyMMdd-HHmmss'))
  Move-Item -LiteralPath $backup -Destination $safe
  Say ('The previous PEER folder is kept here: ' + $safe)
}

Say ''
Say ('[OK] PEER ' + $want + ' is installed for ' + $who.name + '.')
Say 'Start Revit - the PEER tab appears. Updates come by themselves when Revit starts.'
exit 0
