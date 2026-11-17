@echo off
setlocal
if not defined VSCMD_VER call "%ProgramFiles%\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
if not exist "%~dp0..\..\..\compiled" mkdir "%~dp0..\..\..\compiled"
cl /nologo /std:c++20 /O2 /EHsc /DNOMINMAX "%~dp0prefix.cpp" /Fo:"%~dp0..\..\..\compiled\prefix.obj" /Fe:"%~dp0..\..\..\compiled\prefix.exe"
exit /b %errorlevel%
