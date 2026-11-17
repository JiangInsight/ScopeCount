@echo off
setlocal
if not defined VSCMD_VER call "%ProgramFiles%\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
if not exist "%~dp0..\..\compiled" mkdir "%~dp0..\..\compiled"
for %%P in (runner bundles controls cut gate cut_execution topology published_run) do (
  cl /nologo /O2 /EHsc /std:c++20 /DNOMINMAX "%~dp0%%P.cpp" /Fo:"%~dp0..\..\compiled\%%P.obj" /Fe:"%~dp0..\..\compiled\%%P.exe"
  if errorlevel 1 exit /b 1
)
exit /b 0
