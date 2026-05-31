@echo off
setlocal
set "SRC=%~dp0"

echo ============================================================
echo  ACI-RPCS3 -- Apply source patches
echo ============================================================
echo.

echo [1/3] Applying RPCS3 TSS patch...
cd /d "%SRC%GIT\rpcs3"
git apply "..\..\PATCH\RPCS3\tss-support.patch"
if errorlevel 1 (
    echo.
    echo ERROR: RPCS3 TSS patch failed.
    echo Make sure SRC\GIT\rpcs3 is a clean clone with no local modifications.
    pause & exit /b 1
)
echo Done.
echo.

echo [2/3] Applying RPCS3 P2PS disconnect fix patch...
cd /d "%SRC%GIT\rpcs3"
git apply "..\..\PATCH\RPCS3\p2ps-disconnect-fix.patch"
if errorlevel 1 (
    echo.
    echo ERROR: RPCS3 P2PS patch failed.
    echo Make sure SRC\GIT\rpcs3 is a clean clone with no local modifications.
    pause & exit /b 1
)
echo Done.
echo.

echo [2b/3] Applying RPCN auto-reconnect patch...
cd /d "%SRC%GIT\rpcs3"
git apply "..\..\PATCH\RPCS3\rpcn-reconnect.patch"
if errorlevel 1 (
    echo.
    echo ERROR: RPCN reconnect patch failed.
    pause & exit /b 1
)
echo Done.
echo.
echo [3/3] Applying RPCN TSS server patch...
cd /d "%SRC%GIT\rpcn"
git apply "..\..\PATCH\RPCN\tss-server.patch"
if errorlevel 1 (
    echo.
    echo ERROR: RPCN patch failed.
    echo Make sure SRC\GIT\rpcn is a clean clone with no local modifications.
    pause & exit /b 1
)
echo Done.
echo.

echo ============================================================
echo  All patches applied successfully.
echo.
echo  Next steps:
echo    RPCS3: Follow SRC\GIT\rpcs3\BUILDING.md (Visual Studio 2022)
echo           Copy output rpcs3.exe + DLLs to BIN\RPCS3\
echo.
echo    RPCN:  cd SRC\GIT\rpcn
echo           cargo build --release
echo           Copy target\release\rpcn.exe to BIN\rpcn\
echo ============================================================
pause
