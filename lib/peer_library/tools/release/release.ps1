param(
  [ValidateSet('status', 'ext', 'template', 'promote')] [string]$Do = 'status',
  [ValidateSet('ext', 'template')] [string]$Product = 'ext',
  [string]$Ref = 'HEAD',
  [ValidateSet('beta', 'stable')] [string]$Channel = 'beta',
  [string]$Version = '',
  [string]$Note = '',
  [string]$File = '',                    # -Do template: the .rte saved from Revit
  [ValidateSet('this', 'production')] [string]$Target = 'this',   # 'this' = the service of this computer (trial)
  [string]$Engine = (Join-Path $env:APPDATA 'pyRevit-Master\bin\engines\IPY2711PR'),
  [switch]$Yes
)
# Release PEER through the PEER service (admin key of this Windows user, never printed).
#
#   release.ps1                                        what is published now (nothing changes)
# Two editions, each its own extension and ribbon tab in Revit:
#   stable = PEER      (branch main, everybody)        beta = PEER_dev (branch dev, for trying)
#   release.ps1 -Do ext -Ref dev -Channel beta -Note "what changed"       -> PEER_dev
#   release.ps1 -Do ext -Ref main -Channel stable -Note "what changed"    -> PEER, for everybody
#   release.ps1 -Do promote -Version 2026.11.20.1 -Channel stable         roll PEER back to that version
# Pushing to GitHub does the same by itself when the release workflow is set up (.github/workflows).
#   ... -Target production                             the office service instead of this computer's one
#   release.ps1 -Do template -File "D:\work\PR_Template Concrete.rte" -Note "what changed"     template -> beta
#   release.ps1 -Product template                      template versions
#   release.ps1 -Do promote -Product template -Version 14 -Channel stable
#
# Only committed files are packed (git archive). Publishing asks before it sends, unless -Yes.
$ErrorActionPreference = 'Stop'
$env:PEER_RELEASE_TARGET = $Target
$here = Split-Path $MyInvocation.MyCommand.Path
$ext = (Resolve-Path (Join-Path $here '..\..\..\..')).Path
$eng = $Engine          # pyRevit's IronPython (.NET HTTPS + DPAPI, as inside Revit)
$work = Join-Path $env:TEMP 'peer_release'
New-Item -ItemType Directory -Force $work | Out-Null

function Invoke-Service([string[]]$CallArgs) {
  # IronPython standard library: pyRevit keeps it inside pyRevitLoader.dll
  $zip = Join-Path $work 'python_2711pr_lib.zip'
  if (-not (Test-Path $zip)) {
    $a = [Reflection.Assembly]::ReflectionOnlyLoadFrom((Join-Path $eng 'pyRevitLoader.dll'))
    $s = $a.GetManifestResourceStream('pyRevitLoader.python_2711pr_lib.zip')
    $fs = [IO.File]::Create($zip); $s.CopyTo($fs); $fs.Close(); $s.Close()
  }
  foreach ($n in 'pyRevitLabs.IronPython.dll', 'pyRevitLabs.IronPython.Modules.dll') {
    [void][Reflection.Assembly]::LoadFrom((Join-Path $eng $n))
  }
  Get-ChildItem $eng -Filter 'pyRevitLabs.Microsoft.*.dll' | ForEach-Object { [void][Reflection.Assembly]::LoadFrom($_.FullName) }
  $py = [IronPython.Hosting.Python]::CreateEngine()
  $sp = $py.GetSearchPaths(); $sp.Add($zip); $py.SetSearchPaths($sp)
  $scope = $py.CreateScope()
  $file = Join-Path $here 'service_call.py'
  $scope.SetVariable('__file__', $file)
  $scope.SetVariable('ARGS', $CallArgs)
  $buf = New-Object IO.MemoryStream
  $py.Runtime.IO.SetOutput($buf, [Text.Encoding]::UTF8)
  $py.Runtime.IO.SetErrorOutput($buf, [Text.Encoding]::UTF8)
  $boot = "import traceback, sys`n__file__ = r'" + $file + "'`ntry:`n    execfile(__file__, globals())`nexcept SystemExit as e:`n    print('STOP ' + str(e))`nexcept BaseException:`n    traceback.print_exc()`n    print('STOP error')`n"
  [void]$py.CreateScriptSourceFromString($boot).Execute($scope)
  $text = [Text.Encoding]::UTF8.GetString($buf.ToArray()).TrimStart([char]0xFEFF).TrimEnd()
  $text
  if ($text -match '(?m)^STOP') { throw 'The service call failed (see above).' }
}

if ($Do -eq 'status') { Invoke-Service @('manifest', $Product); return }

if ($Do -eq 'promote') {
  if (-not $Version) { throw 'Give -Version.' }
  if (-not $Yes) {
    $a = Read-Host "Point $Product '$Channel' at version $Version for everybody on that channel? (yes/no)"
    if ($a -ne 'yes') { 'Cancelled.'; return }
  }
  Invoke-Service @('promote', $Product, $Version, $Channel)
  if ($Product -eq 'ext') {        # the loader of the same version follows the full PEER
    try { Invoke-Service @('promote', 'boot', $Version, $Channel) } catch { 'No loader of this version - skipped.' }
  }
  return
}

# ---- the project template (a .rte saved from Revit; versions are 1, 2, 3 ...) ----
if ($Do -eq 'template') {
  if (-not $Note.Trim()) { throw 'Give -Note "what changed" - colleagues see it.' }
  if (-not $File -or -not (Test-Path -LiteralPath $File)) { throw 'Give -File with the template (.rte).' }
  if ([IO.Path]::GetExtension($File).ToLower() -ne '.rte') { throw 'The template must be a .rte file.' }
  if (-not $Version) {
    $out = Invoke-Service @('manifest', 'template')
    $out
    $Version = ((($out -split "`n") | Where-Object { $_ -match '^NEXTINT ' } | Select-Object -First 1) -replace '^NEXTINT\s+', '').Trim()
  }
  if (-not $Version) { throw 'Could not work out the next version.' }
  $mb = [Math]::Round((Get-Item -LiteralPath $File).Length / 1MB, 1)
  if (-not $Yes) {
    $a = Read-Host "Publish template version $Version ($mb MB) to '$Channel'? (yes/no)"
    if ($a -ne 'yes') { 'Cancelled.'; return }
  }
  Invoke-Service @('publish', 'template', $Version, (Resolve-Path -LiteralPath $File).Path, $Channel, $Note)
  return
}

# ---- package of the extension ----
if (-not $Note.Trim()) { throw 'Give -Note "what changed" - colleagues see it.' }
$dirty = (& git -C $ext status --porcelain)
if ($dirty) { 'Uncommitted changes are NOT in the package (only committed files are packed):'; $dirty | Select-Object -First 15 }
if (-not $Version) {
  $out = Invoke-Service @('manifest', 'ext')
  $out
  $Version = (($out -split "`n") | Where-Object { $_ -match '^NEXT ' } | Select-Object -First 1) -replace '^NEXT\s+', ''
  $Version = $Version.Trim()
}
if (-not $Version) { throw 'Could not work out the next version.' }
$build = & py -3 (Join-Path $here 'build_ext.py') $Version --ref $Ref --channel $Channel --out $work
$build
$package = (($build | Where-Object { $_ -match '^PACKAGE ' }) -replace '^PACKAGE\s+', '').Trim()
$loader = (($build | Where-Object { $_ -match '^LOADER ' }) -replace '^LOADER\s+', '').Trim()
$installer = (($build | Where-Object { $_ -match '^INSTALLER ' }) -replace '^INSTALLER\s+', '').Trim()
if (-not (Test-Path $package) -or -not (Test-Path $loader) -or -not (Test-Path $installer)) { throw 'The package was not built.' }
if (-not $Yes) {
  $a = Read-Host "Publish PEER $Version (from $Ref) to '$Channel' on the $Target service? (yes/no)"
  if ($a -ne 'yes') { "Cancelled. The package stays here: $package"; return }
}
Invoke-Service @('publish', 'ext', $Version, $package, $Channel, $Note)
# the public loader (Account + updater) of the same version - what install.bat puts on a new computer
Invoke-Service @('publish', 'boot', $Version, $loader, $Channel, $Note)
# the installer people download: <service>/install
Invoke-Service @('installer', '-', $installer)
