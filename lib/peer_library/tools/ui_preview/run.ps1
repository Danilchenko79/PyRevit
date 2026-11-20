param([string]$Script = 'all', [string]$Out = "$env:TEMP\peer_ui_preview")
# Library windows without Revit: the real window code under pyRevit's IronPython 2.7
# (stubbed Revit / pyrevit.forms), live library service with your saved key (read only),
# own cache folder. Windows open off-screen; pictures go to -Out.
#   powershell -STA -ExecutionPolicy Bypass -File lib\peer_library\tools\ui_preview\run.ps1   # all
#   ... run.ps1 -Script library      (library.py)   /  -Script windows  (windows.py)
$here = Split-Path $MyInvocation.MyCommand.Path
$eng = Join-Path $env:APPDATA 'pyRevit-Master\bin\engines\IPY2711PR'
if ([Threading.Thread]::CurrentThread.GetApartmentState() -ne 'STA') { throw 'Run with powershell -STA' }
New-Item -ItemType Directory -Force $Out | Out-Null
# IronPython standard library: pyRevit keeps it inside pyRevitLoader.dll
$zip = Join-Path $Out 'python_2711pr_lib.zip'
if (-not (Test-Path $zip)) {
  $a = [Reflection.Assembly]::ReflectionOnlyLoadFrom((Join-Path $eng 'pyRevitLoader.dll'))
  $s = $a.GetManifestResourceStream('pyRevitLoader.python_2711pr_lib.zip')
  $fs = [IO.File]::Create($zip); $s.CopyTo($fs); $fs.Close(); $s.Close()
}
foreach ($n in 'pyRevitLabs.IronPython.dll', 'pyRevitLabs.IronPython.Modules.dll', 'pyRevitLabs.IronPython.Wpf.dll') {
  [void][Reflection.Assembly]::LoadFrom((Join-Path $eng $n))
}
Get-ChildItem $eng -Filter 'pyRevitLabs.Microsoft.*.dll' | ForEach-Object { [void][Reflection.Assembly]::LoadFrom($_.FullName) }
$scripts = if ($Script -eq 'all') { 'library', 'windows' } else { @($Script) }
foreach ($name in $scripts) {
  $file = Join-Path $here ($name + '.py')
  $py = [IronPython.Hosting.Python]::CreateEngine()
  $py.Runtime.LoadAssembly([Reflection.Assembly]::LoadFrom((Join-Path $eng 'pyRevitLabs.IronPython.Wpf.dll')))
  $sp = $py.GetSearchPaths(); $sp.Add($zip); $py.SetSearchPaths($sp)
  $scope = $py.CreateScope()
  $scope.SetVariable('__file__', $file)
  $scope.SetVariable('OUT', $Out)
  $buf = New-Object IO.MemoryStream
  $py.Runtime.IO.SetOutput($buf, [Text.Encoding]::UTF8)
  $err = $null
  try { [void]$py.CreateScriptSourceFromFile($file, [Text.Encoding]::UTF8).Execute($scope) }
  catch { $e = $_.Exception; while ($e.InnerException) { $e = $e.InnerException }
          $err = $py.GetService([Microsoft.Scripting.Hosting.ExceptionOperations]).FormatException($e) }
  "==== $name"
  [Text.Encoding]::UTF8.GetString($buf.ToArray())
  if ($err) { "ERROR:"; $err }
}
"pictures: $Out"
