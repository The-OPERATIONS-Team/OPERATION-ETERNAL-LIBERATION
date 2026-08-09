# Incremental RPCS3-only build for the Windows builder VM.
#
# A fast-turnaround companion to build-all.ps1 for iterating on a patch. It
# builds only the emucore + rpcs3 msbuild targets and, crucially, does NOT
# `git clean` the submodule, so the existing build intermediates (.obj/.pch,
# bin\, build\) are reused and only the handful of patched translation units
# recompile. It skips the RPCN build, deploy mirror, and packaging.
#
# Run build-all.ps1 at least once on this checkout first (it provides the cold
# build, the LLVM libs, and the nuget restore that this script reuses). After
# that, dispatch this script instead for a ~minute turnaround on a C++ edit.
#
# It does NOT carry its own patch list: the RPCS3 patch sequence comes from
# SRC\PATCH\series (the single source of truth) via ci\patch-series.ps1, the
# same reader build-all.ps1 uses. Adding a patch to the series propagates here.

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

# Pinned commit (rpcs3 only) - same source of truth as build-all.ps1.
$PinnedEnv = Join-Path $RepoRoot "SRC\pinned-commits.env"
if (-not (Test-Path $PinnedEnv)) { throw "Missing $PinnedEnv" }
$Pinned = @{}
Get-Content $PinnedEnv | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') { $Pinned[$matches[1]] = $matches[2] }
}
$Rpcs3Commit = $Pinned['RPCS3_COMMIT']
if (-not $Rpcs3Commit) { throw "RPCS3_COMMIT not found in $PinnedEnv" }

# Must match build-all.ps1 / rpcs3's LLVM_VER.
$LlvmVer  = "22.1.8"
$Rpcs3Dir = "SRC\GIT\rpcs3"

function Step($name) { Write-Host "`n=== $name ===" -ForegroundColor Cyan }

if (-not (Test-Path "$Rpcs3Dir\.git")) {
    throw "$Rpcs3Dir is not a clone. Run build-all.ps1 once before using this incremental script."
}

# 1. Restore source to pinned commit + reapply patches, WITHOUT cleaning.
#    git reset --hard rewrites only the files that differ from the working tree
#    (i.e. the previously-patched files), so every untouched translation unit
#    keeps its mtime and its cached .obj. The build outputs are untracked and
#    survive the reset; we deliberately skip `git clean` and `git submodule
#    update` to preserve the incremental cache and the prebuilt sub-submodules.
Step "Reset rpcs3 source to pinned (no clean)"
Push-Location $Rpcs3Dir
git reset --hard $Rpcs3Commit
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { throw "git reset to $Rpcs3Commit failed" }

# 2. Apply the RPCS3 patch list from SRC\PATCH\series.
Step "Apply RPCS3 patches"
. "$PSScriptRoot\patch-series.ps1"
$rpcs3Patches = @((Get-PatchSeries -RepoRoot $RepoRoot -RepoFilter 'rpcs3').Leaf)
if (-not $rpcs3Patches) { throw "No RPCS3 patches found in SRC\PATCH\series" }

# A patch that creates a file leaves it behind as untracked on the next run (the reset above
# deliberately skips `git clean`), and re-applying the creating patch then fails on
# "already exists". Delete exactly those leftovers before applying.
foreach ($p in $rpcs3Patches) {
    $lines = Get-Content "$RepoRoot\SRC\PATCH\RPCS3\$p"
    for ($i = 1; $i -lt $lines.Count; $i++) {
        if ($lines[$i - 1] -match '^--- /dev/null' -and $lines[$i] -match '^\+\+\+ b/(.+)$') {
            $rel = $matches[1].Trim()
            $leftover = Join-Path $Rpcs3Dir ($rel -replace '/', '\')
            if (Test-Path $leftover) {
                Remove-Item -Force $leftover
                Write-Host "  removed leftover $rel"
            }
        }
    }
}

foreach ($p in $rpcs3Patches) {
    Write-Host "Applying $p..."
    Push-Location $Rpcs3Dir
    git apply "$RepoRoot\SRC\PATCH\RPCS3\$p"
    $rc = $LASTEXITCODE
    Pop-Location
    if ($rc -ne 0) { throw "git apply failed for $p" }
    Write-Host "  OK" -ForegroundColor Green
}

# Force msbuild to recompile every patched translation unit. `git reset --hard`
# followed by `git apply` should already bump each file's mtime, but the
# incremental .obj cache occasionally outlives that write (clock granularity /
# identical-content checkouts), leaving a stale object linked into rpcs3.exe.
# Re-stamping the patched files' LastWriteTime to now makes the file tracker
# treat them as dirty without a full /t:rpcs3:Rebuild of the whole project.
Step "Touch patched files (force recompile)"
$now = Get-Date
$patchedFiles = foreach ($p in $rpcs3Patches) {
    Get-Content "$RepoRoot\SRC\PATCH\RPCS3\$p" |
        Where-Object { $_ -match '^\+\+\+ b/(.+)$' } |
        ForEach-Object { $matches[1].Trim() }
}
foreach ($rel in ($patchedFiles | Sort-Object -Unique)) {
    $full = Join-Path $Rpcs3Dir ($rel -replace '/', '\')
    if (Test-Path $full) {
        (Get-Item $full).LastWriteTime = $now
        Write-Host "  touched $rel"
    } else {
        Write-Host "  WARN: patched file not found: $rel" -ForegroundColor Yellow
    }
}

# 3. Prebuilt LLVM libs (extract only if the cold build did not already).
Step "Ensure prebuilt LLVM"
$LlvmLibsDir = "$Rpcs3Dir\build\lib_ext\Release-x64"
$LlvmLibsMarker = "$LlvmLibsDir\llvmlibs_mt.installed"
if (Test-Path $LlvmLibsMarker) {
    Write-Host "LLVM $LlvmVer libs already extracted, skipping."
} else {
    $LlvmCache = "$env:TEMP\llvmlibs_mt-$LlvmVer.7z"
    if (-not (Test-Path $LlvmCache)) {
        $LlvmUrl = "https://github.com/RPCS3/llvm-mirror/releases/download/custom-build-win-$LlvmVer/llvmlibs_mt.7z"
        Write-Host "Downloading $LlvmUrl..." -ForegroundColor Cyan
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $LlvmUrl -OutFile $LlvmCache
    }
    New-Item -ItemType Directory -Force -Path $LlvmLibsDir | Out-Null
    & "C:\Program Files\7-Zip\7z.exe" x $LlvmCache "-o$LlvmLibsDir" -y | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "7z extraction of llvmlibs failed" }
    New-Item -ItemType File -Force -Path $LlvmLibsMarker | Out-Null
}

# 4. Build emucore + rpcs3 only, via the VS dev environment.
#    The rpcs3 solution target is unambiguous (not nested in a solution folder)
#    and pulls emucore in as a project dependency, so msbuild recompiles only the
#    changed sources and relinks - no RPCN, no rpcs3_test, no other targets.
Step "Build emucore + rpcs3 (incremental)"
$vsPath = & 'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe' -latest -products * -property installationPath
if (-not $vsPath) { throw "vswhere found no Visual Studio installation" }
$vsDevCmd = Join-Path $vsPath 'Common7\Tools\VsDevCmd.bat'
if (-not (Test-Path $vsDevCmd)) { throw "VsDevCmd.bat not found at $vsDevCmd" }
$envDump = & cmd /c "`"$vsDevCmd`" -arch=amd64 -host_arch=amd64 -no_logo > NUL && set"
foreach ($line in $envDump) {
    if ($line -match '^([^=]+)=(.*)$') { Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2] }
}

$nugetExe = "$env:TEMP\nuget.exe"
if (-not (Test-Path $nugetExe)) {
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri "https://dist.nuget.org/win-x86-commandline/latest/nuget.exe" -OutFile $nugetExe
}
Push-Location $Rpcs3Dir
& $nugetExe restore rpcs3.sln
msbuild rpcs3.sln /t:rpcs3 /p:Configuration=Release /p:Platform=x64 /v:minimal /m
Pop-Location

# 5. Drop the freshly built rpcs3.exe over the existing deploy (plain copy, not a
#    /MIR mirror - this preserves the Qt DLLs and qt6\ plugins from the last full
#    build-all.ps1 deploy, so the binary stays runnable for validation).
$BuiltExe  = "$Rpcs3Dir\bin\rpcs3.exe"
$DeployExe = "BIN\_app\RPCS3\rpcs3.exe"
if ((Test-Path $BuiltExe) -and (Test-Path "BIN\_app\RPCS3")) {
    Step "Deploy rpcs3.exe"
    Copy-Item -Force $BuiltExe $DeployExe
    Write-Host "Copied $BuiltExe -> $DeployExe" -ForegroundColor Green
} else {
    Write-Host "`nSkipping deploy: build output or deploy dir not found." -ForegroundColor Yellow
}

Step "Done"
Write-Host "Built: $BuiltExe" -ForegroundColor Green
