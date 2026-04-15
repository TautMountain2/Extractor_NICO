@echo off
setlocal
cd /d %~dp0\..
if not exist build\docs mkdir build\docs
doxygen Doxyfile
echo Documentacion generada en build\docs\html\index.html
endlocal
