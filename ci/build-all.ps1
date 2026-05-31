# Full build pipeline for the Windows builder VM.
# Resets submodules to pinned commits + reapplies patches every run for
# reproducible builds. Run from the repo root after rsyncing the working copy.
# Prereqs: ci\install-prereqs.ps1 + ci\install-qt.ps1 already ran.

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

# Pinned commits — loaded from SRC\pinned-commits.env (shared with clone-git-repos.bat).
$PinnedEnv = Join-Path $RepoRoot "SRC\pinned-commits.env"
if (-not (Test-Path $PinnedEnv)) { throw "Missing $PinnedEnv" }
$Pinned = @{}
Get-Content $PinnedEnv | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
        $Pinned[$matches[1]] = $matches[2]
    }
}
$Rpcs3Url    = $Pinned['RPCS3_URL']
$Rpcs3Commit = $Pinned['RPCS3_COMMIT']
$RpcnUrl     = $Pinned['RPCN_URL']
$RpcnCommit  = $Pinned['RPCN_COMMIT']

# Prebuilt LLVM libs for the RPCS3 PPU/SPU recompilers.
# Skipping the LLVM submodule source build saves ~30 min per cold build.
# Must match SRC\GIT\rpcs3\.github\workflows\rpcs3.yml -> LLVM_VER.
$LlvmVer = "19.1.7"

# Deploy destinations inside the repo. Preserve subdirs (portable\ for RPCS3,
# tss_data\ for RPCN) which hold user/runtime state.
$Rpcs3DeployDir = "BIN\_app\RPCS3"
$RpcnDeployDir  = "BIN\_app\rpcn"

function Step($name) { Write-Host "`n=== $name ===" -ForegroundColor Cyan }

function Sync-Submodule {
    param([string]$Path, [string]$Url, [string]$Commit)
    if (Test-Path "$Path\.git") {
        Push-Location $Path
        git reset --hard HEAD
        git clean -ffdx
        git fetch origin
        git checkout $Commit
        git submodule update --init --recursive --depth 1
        Pop-Location
    } else {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
        git clone $Url $Path
        Push-Location $Path
        git checkout $Commit
        git submodule update --init --recursive --depth 1
        Pop-Location
    }
}

function Apply-Patch {
    param([string]$RepoPath, [string]$PatchPath)
    $patchName = Split-Path -Leaf $PatchPath
    Write-Host "Applying $patchName to $RepoPath..."
    Push-Location $RepoPath
    git apply $PatchPath
    Pop-Location
    Write-Host "  OK" -ForegroundColor Green
}

# 1. Sync submodules
Step "Sync submodules"
Sync-Submodule "SRC\GIT\rpcs3" $Rpcs3Url $Rpcs3Commit
Sync-Submodule "SRC\GIT\rpcn"  $RpcnUrl  $RpcnCommit

# 2. Apply patches
Step "Apply patches"
Apply-Patch "SRC\GIT\rpcs3" "$RepoRoot\SRC\PATCH\RPCS3\tss-support.patch"
Apply-Patch "SRC\GIT\rpcs3" "$RepoRoot\SRC\PATCH\RPCS3\p2ps-disconnect-fix.patch"
Apply-Patch "SRC\GIT\rpcs3" "$RepoRoot\SRC\PATCH\RPCS3\rpcn-reconnect.patch"
Apply-Patch "SRC\GIT\rpcn"  "$RepoRoot\SRC\PATCH\RPCN\tss-server.patch"

# 3. Prebuilt LLVM libs
Step "Fetch prebuilt LLVM"
$LlvmLibsDir = "SRC\GIT\rpcs3\build\lib_ext\Release-x64"
$LlvmLibsMarker = "$LlvmLibsDir\llvmlibs_mt.installed"
if (Test-Path $LlvmLibsMarker) {
    Write-Host "LLVM $LlvmVer libs already extracted, skipping."
} else {
    $LlvmCache = "$env:TEMP\llvmlibs_mt-$LlvmVer.7z"
    if (Test-Path $LlvmCache) {
        Write-Host "Using cached $LlvmCache."
    } else {
        $LlvmUrl = "https://github.com/RPCS3/llvm-mirror/releases/download/custom-build-win-$LlvmVer/llvmlibs_mt.7z"
        Write-Host "Downloading $LlvmUrl..." -ForegroundColor Cyan
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $LlvmUrl -OutFile $LlvmCache
    }
    Write-Host "Extracting llvmlibs to $LlvmLibsDir..."
    New-Item -ItemType Directory -Force -Path $LlvmLibsDir | Out-Null
    & "C:\Program Files\7-Zip\7z.exe" x $LlvmCache "-o$LlvmLibsDir" -y | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "7z extraction of llvmlibs failed" }
    New-Item -ItemType File -Force -Path $LlvmLibsMarker | Out-Null
    Write-Host "  OK" -ForegroundColor Green
}

# 4. Build RPCS3 (msbuild via VS dev environment)
Step "Build RPCS3"
$vsPath = & 'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe' -latest -products * -property installationPath
if (-not $vsPath) { throw "vswhere found no Visual Studio installation" }
$vsDevCmd = Join-Path $vsPath 'Common7\Tools\VsDevCmd.bat'
if (-not (Test-Path $vsDevCmd)) { throw "VsDevCmd.bat not found at $vsDevCmd" }
# Run VsDevCmd.bat under cmd, dump env, import back into PowerShell. Much more
# reliable than Launch-VsDevShell.ps1 against Build Tools installs.
$envDump = & cmd /c "`"$vsDevCmd`" -arch=amd64 -host_arch=amd64 -no_logo > NUL && set"
foreach ($line in $envDump) {
    if ($line -match '^([^=]+)=(.*)$') {
        Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2]
    }
}
$nugetExe = "$env:TEMP\nuget.exe"
if (-not (Test-Path $nugetExe)) {
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri "https://dist.nuget.org/win-x86-commandline/latest/nuget.exe" -OutFile $nugetExe
}
Push-Location "SRC\GIT\rpcs3"
# rpcs3_test pulls googletest via packages.config; msbuild /restore only handles
# PackageReference style, so run nuget restore explicitly first.
& $nugetExe restore rpcs3.sln
msbuild rpcs3.sln /p:Configuration=Release /p:Platform=x64 /v:minimal /m
Pop-Location

# 5. Build RPCN
# openssl-src (pulled by openssl = "0.10" with vendored feature) shells out to
# perl. If Git for Windows' MSYS2 perl is earlier on PATH, it gets picked and
# fails on missing core modules. Force Strawberry Perl to win.
Step "Build RPCN"
$strawberryBin = "C:\Strawberry\perl\bin"
if (Test-Path $strawberryBin) {
    $env:Path = "$strawberryBin;$env:Path"
} else {
    Write-Warning "Strawberry Perl not found at $strawberryBin; openssl-src may fall back to MSYS2 perl and fail."
}
Push-Location "SRC\GIT\rpcn"
cargo build --release
Pop-Location

# 6. Deploy artifacts
Step "Deploy artifacts"
$Rpcs3BuildOut = "SRC\GIT\rpcs3\bin"
$RpcnBuildOut  = "SRC\GIT\rpcn\target\release\rpcn.exe"

if (-not (Test-Path $Rpcs3BuildOut)) { throw "RPCS3 build output not found at $Rpcs3BuildOut" }
if (-not (Test-Path $RpcnBuildOut))  { throw "RPCN build output not found at $RpcnBuildOut" }

New-Item -ItemType Directory -Force -Path $Rpcs3DeployDir | Out-Null
New-Item -ItemType Directory -Force -Path $RpcnDeployDir  | Out-Null

# Main mirror: bin/ -> BIN\_app\RPCS3\, excluding subdirs handled separately
# (GuiConfigs and Icons go under portable\) and preserving the helper scripts
# at the root. The rpcs3.exp / .lib / .pdb / vc_redist.x64.exe files are
# stripped to match what rpcs3's own .ci/deploy-windows.sh removes before
# distribution. Exit codes 0-7 are success-with-warnings for robocopy.
robocopy $Rpcs3BuildOut $Rpcs3DeployDir /MIR `
    /XD GuiConfigs Icons portable `
    /XF clear_tus_save.bat clear_tus_save.ps1 restore_tus_save.bat restore_tus_save.ps1 `
        rpcs3.exp rpcs3.lib rpcs3.pdb vc_redist.x64.exe `
    /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw "robocopy main failed with exit code $LASTEXITCODE" }
$global:LASTEXITCODE = 0

# RPCS3 portable mode looks for GuiConfigs and Icons under portable\ rather
# than the install root, so route those there.
$portable = "$Rpcs3DeployDir\portable"
foreach ($subdir in 'GuiConfigs', 'Icons') {
    $src = Join-Path $Rpcs3BuildOut $subdir
    if (Test-Path $src) {
        robocopy $src "$portable\$subdir" /E /NFL /NDL /NJH /NJS /NP
        if ($LASTEXITCODE -ge 8) { throw "robocopy $subdir failed with exit code $LASTEXITCODE" }
        $global:LASTEXITCODE = 0
    }
}

Copy-Item -Force $RpcnBuildOut "$RpcnDeployDir\rpcn.exe"

# 7. Package. cmd /c with < nul lets pause statements return immediately.
Step "Package"
cmd /c "`"$RepoRoot\package.bat`" < nul"
if ($LASTEXITCODE -ne 0) { throw "package.bat failed with exit code $LASTEXITCODE" }

Step "Done"
Get-ChildItem $RepoRoot\OP-ETERNAL-Setup-*.exe, $RepoRoot\OEL-SRC-*.7z, $RepoRoot\OEL-DOCKER-*.7z |
    Select-Object Name, @{N='SizeMB';E={[math]::Round($_.Length/1MB,1)}}
