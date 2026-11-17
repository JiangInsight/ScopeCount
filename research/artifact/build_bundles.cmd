@echo off
setlocal
if not defined VSCMD_VER call "%ProgramFiles%\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
cl /nologo /std:c++20 /O2 /EHsc /DNOMINMAX "%~dp0bundles.cpp" /Fo:"%~dp0../../compiled/bundles.obj" /Fe:"%~dp0../../compiled/bundles.exe"
exit /b %errorlevel%
