param(
  [string]$Url = '',                    # PEER service address (install.bat passes it)
  [ValidateSet('stable', 'beta')] [string]$Channel = 'stable',     # beta = PEER_dev (branch dev), beside PEER
  [string]$ExtDir = '',                 # default: %APPDATA%\pyRevit\Extensions\PEER.extension
  [switch]$Quiet                        # no questions (tests): key from $env:PEER_INSTALL_KEY
)
# PEER for pyRevit - install / repair. No key needed here: the public loader is installed
# (PEER tab with the Account button and the updater); the person signs in inside Revit and the
# full PEER downloads right after that. A computer that already has a valid key gets the full
# PEER at once. Later Revit keeps it up to date.
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
# stable = PEER (what everybody runs); beta = PEER_dev: its own folder and its own ribbon tab, beside PEER
$extName = 'PEER'; $edition = 'stable'
if ($Channel -eq 'beta') { $extName = 'PEER_dev'; $edition = 'dev' }
if (-not $ExtDir) { $ExtDir = Join-Path $env:APPDATA ('pyRevit\Extensions\' + $extName + '.extension') }
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
if (-not $pyrevit -and -not $Quiet) {       # -Quiet = automatic tests on a computer without pyRevit
  Stop-Install ('pyRevit is not installed on this computer. Install pyRevit 5.2 first ' +
                '(https://github.com/pyrevitlabs/pyRevit/releases), then run this file again.')
}
$revitRuns = [bool](Get-Process Revit -ErrorAction SilentlyContinue)

# ---- 1. a key already on this computer? (re-install / repair) -------------------------
# Nobody is asked for a key here: without one the public loader is installed and the person
# signs in inside Revit (PEER -> Account); the full PEER downloads right after that.
New-Item -ItemType Directory -Force $peerDir | Out-Null
$key = $null; $who = $null
if ($Quiet -and $env:PEER_INSTALL_KEY) { $key = $env:PEER_INSTALL_KEY }
elseif (Test-Path $keyFile) { $key = Unprotect-File $keyFile }
if ($key) {
  $r = Invoke-Peer 'GET' '/auth' $key $null $null
  if ($r.status -eq 200) {
    $who = $r.data
    if ($Quiet -and $env:PEER_INSTALL_KEY) { [IO.File]::WriteAllBytes($keyFile, (Protect-Text $key)) }
    Say ('Signed in as ' + $who.name + ' - the full PEER is installed.')
  } elseif ($r.status -eq 0) { Stop-Install ('No connection to the PEER service: ' + $r.error) }
  else { $key = $null; Say 'The key saved on this computer is not valid any more - the loader is installed, sign in in Revit.' }
}

# ---- 2. settings of this computer ----------------------------------------------------
$cfg = @{}
if (Test-Path $cfgFile) { try { (Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $cfg[$_.Name] = $_.Value } } catch { } }
$cfg['backend'] = 'http'; $cfg['url'] = $Url.TrimEnd('/')
if ($who) { $cfg['user'] = $who.name; $cfg['role'] = $who.role; $cfg['last_ok'] = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss') }
[IO.File]::WriteAllText($cfgFile, ($cfg | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))

# ---- 3. the package: the full PEER with a key, the public loader without ---------------
if ($key) { $manifest = '/release/ext/manifest'; $file = '/release/ext/file/'; $product = 'ext'; $flavor = 'full' }
else { $manifest = '/boot/manifest'; $file = '/boot/file/'; $product = 'boot'; $flavor = 'boot' }
$r = Invoke-Peer 'GET' $manifest $key $null $null
if ($r.status -ne 200) { Stop-Install ('Could not read the list of PEER versions: ' + $r.error) }
$m = $r.data
$want = $m.channels.stable
if ($Channel -eq 'beta') { $want = $m.channels.beta }
if (-not $want) { Stop-Install ('No ' + $extName + ' package is published yet. Ask a PEER admin.') }
$entry = $m.versions | Where-Object { $_.version -eq $want } | Select-Object -First 1
if (-not $entry) { Stop-Install ('Version ' + $want + ' is not on the service any more. Ask a PEER admin.') }
New-Item -ItemType Directory -Force $work | Out-Null
$zip = Join-Path $work ($product + '-' + $want + '.zip')
if (-not (Test-Path $zip) -or (Get-Sha1 $zip) -ne $entry.sha1) {
  Say ('Downloading PEER ' + $want + ' ...')
  $r = Invoke-Peer 'GET' ($file + $want) $key $null $zip
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
$vj = Get-Content (Join-Path $stage 'version.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$got = 'full'; if ($vj.flavor -eq 'boot') { $got = 'boot' }
if ($got -ne $flavor) { Stop-Install 'The service sent another package than asked for. Ask a PEER admin.' }
$gotEdition = 'stable'; if ($vj.edition -eq 'dev') { $gotEdition = 'dev' }
if ($gotEdition -ne $edition) { Stop-Install 'The service sent the other edition of PEER. Ask a PEER admin.' }
$backup = $null
if (Test-Path $ExtDir) {
  $backup = $ExtDir + '.old-' + (Get-Date).ToString('yyyyMMdd-HHmmss')
  try { Move-Item -LiteralPath $ExtDir -Destination $backup }
  catch { Stop-Install ('The PEER folder is in use. Close Revit and run this file again: ' + $ExtDir) }
}
New-Item -ItemType Directory -Force (Split-Path $ExtDir) | Out-Null
Move-Item -LiteralPath $stage -Destination $ExtDir
if ($backup) {
  # pyRevit loads every *.extension folder it finds: the backup must not look like one
  $safe = Join-Path (Split-Path $ExtDir) ($extName + '_backup_' + (Get-Date).ToString('yyyyMMdd-HHmmss'))
  Move-Item -LiteralPath $backup -Destination $safe
  Say ('The previous PEER folder is kept here: ' + $safe)
}

Say ''
if ($key) {
  Say ('[OK] ' + $extName + ' ' + $want + ' is installed for ' + $who.name + '.')
  Say ('Start Revit - the ' + $extName + ' tab appears. Updates come by themselves when Revit starts.')
} else {
  Say ('[OK] ' + $extName + ' ' + $want + ' is installed.')
  Say ('Start Revit, open the ' + $extName + ' tab and press Account: paste your key, or request access.')
  Say 'After you sign in, PEER downloads all its tools by itself.'
}
if ($revitRuns) { Say ('Revit is running now: restart Revit to see the ' + $extName + ' tab.') }
exit 0
