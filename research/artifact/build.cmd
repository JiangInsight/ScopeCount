@echo off
setlocal
if not defined VSCMD_VER call "%ProgramFiles%\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
if not exist "%~dp0..\..\compiled" mkdir "%~dp0..\..\compiled"
cl /nologo /O2 /EHsc /std:c++17 /DNOMINMAX "%~dp0runner.cpp" /Fo:"%~dp0..\..\compiled\runner.obj" /Fe:"%~dp0..\..\compiled\runner.exe"
exit /b %errorlevel%
