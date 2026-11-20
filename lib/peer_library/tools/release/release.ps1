param(
  [ValidateSet('status', 'ext', 'promote')] [string]$Do = 'status',
  [ValidateSet('ext', 'template')] [string]$Product = 'ext',
  [string]$Ref = 'HEAD',
  [ValidateSet('beta', 'stable')] [string]$Channel = 'beta',
  [string]$Version = '',
  [string]$Note = '',
  [string]$Engine = (Join-Path $env:APPDATA 'pyRevit-Master\bin\engines\IPY2711PR'),
  [switch]$Yes
)
# Release PEER through the PEER service (admin key of this Windows user, never printed).
#
#   release.ps1                                        what is published now (nothing changes)
#   release.ps1 -Do ext -Note "what changed"           package of HEAD -> beta
#   release.ps1 -Do ext -Ref dev -Channel stable -Note "..."
#   release.ps1 -Do promote -Version 2026.11.20.1 -Channel stable     beta -> everybody / roll back
#
# Only committed files are packed (git archive). Publishing asks before it sends, unless -Yes.
$ErrorActionPreference = 'Stop'
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
  $boot = "import traceback, sys`n__file__ = r'" + $file + "'`ntry:`n    execfile(__file__, globals())`nexcept SystemExit as e:`n    print('STOP', e)`nexcept BaseException:`n    traceback.print_exc()`n    print('STOP error')`n"
  [void]$py.CreateScriptSourceFromString($boot).Execute($scope)
  $text = [Text.Encoding]::UTF8.GetString($buf.ToArray())
  $text.TrimStart([char]0xFEFF).TrimEnd()
  if ($text -match '(?m)^STOP ') { throw 'The service call failed (see above).' }
}

if ($Do -eq 'status') { Invoke-Service @('manifest', $Product); return }

if ($Do -eq 'promote') {
  if (-not $Version) { throw 'Give -Version.' }
  if (-not $Yes) {
    $a = Read-Host "Point $Product '$Channel' at version $Version for everybody on that channel? (yes/no)"
    if ($a -ne 'yes') { 'Cancelled.'; return }
  }
  Invoke-Service @('promote', $Product, $Version, $Channel); return
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
if (-not (Test-Path $package)) { throw 'The package was not built.' }
if (-not $Yes) {
  $a = Read-Host "Publish PEER $Version (from $Ref) to '$Channel'? (yes/no)"
  if ($a -ne 'yes') { "Cancelled. The package stays here: $package"; return }
}
Invoke-Service @('publish', 'ext', $Version, $package, $Channel, $Note)
