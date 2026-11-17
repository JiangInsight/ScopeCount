@echo off
setlocal
if defined VSCMD_VER goto build
for /f "usebackq tokens=*" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "scope_vspath=%%i"
if not defined scope_vspath exit /b 1
call "%scope_vspath%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
:build
if not exist "%~dp0..\..\..\compiled" mkdir "%~dp0..\..\..\compiled"
cl /nologo /std:c++20 /O2 /EHsc /DNOMINMAX "%~dp0test_pivot.cpp" /Fo:"%~dp0..\..\..\compiled\test_pivot.obj" /Fe:"%~dp0..\..\..\compiled\test_pivot.exe"
if errorlevel 1 exit /b 1
"%~dp0..\..\..\compiled\test_pivot.exe"
if errorlevel 1 exit /b 1
cl /nologo /std:c++20 /O2 /EHsc /DNOMINMAX "%~dp0test_segments.cpp" /Fo:"%~dp0..\..\..\compiled\test_segments.obj" /Fe:"%~dp0..\..\..\compiled\test_segments.exe"
if errorlevel 1 exit /b 1
"%~dp0..\..\..\compiled\test_segments.exe"
if errorlevel 1 exit /b 1
cl /nologo /std:c++20 /O2 /EHsc /DNOMINMAX "%~dp0profile_segments.cpp" /Fo:"%~dp0..\..\..\compiled\profile_segments.obj" /Fe:"%~dp0..\..\..\compiled\profile_segments.exe"
