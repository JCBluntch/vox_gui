@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "UI_SCRIPT=%SCRIPT_DIR%batch_clone_webui.py"

if defined VOXCPM_PYTHON (
  set "PY_EXE=%VOXCPM_PYTHON%"
)

if not defined PY_EXE if exist "%USERPROFILE%\anaconda3\envs\voxcpm310\python.exe" (
  set "PY_EXE=%USERPROFILE%\anaconda3\envs\voxcpm310\python.exe"
)

if not defined PY_EXE if exist "%USERPROFILE%\miniconda3\envs\voxcpm310\python.exe" (
  set "PY_EXE=%USERPROFILE%\miniconda3\envs\voxcpm310\python.exe"
)

if not defined PY_EXE (
  for %%I in (python.exe) do set "PY_EXE=%%~$PATH:I"
)

if not defined PY_EXE (
  echo Python executable not found.
  echo Activate your VoxCPM environment or set VOXCPM_PYTHON to the full python.exe path.
  pause
  exit /b 1
)

if not exist "%PY_EXE%" (
  echo Python executable not found:
  echo %PY_EXE%
  pause
  exit /b 1
)

if not exist "%UI_SCRIPT%" (
  echo UI script not found:
  echo %UI_SCRIPT%
  pause
  exit /b 1
)

echo Launching VoxCPM Batch Clone UI...
echo URL: http://127.0.0.1:8820
"%PY_EXE%" "%UI_SCRIPT%"

endlocal
