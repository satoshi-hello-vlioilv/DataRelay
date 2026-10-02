@echo off
setlocal EnableExtensions
chcp 65001 >nul
rem ======================================================================
rem  DataRelay.exe を手元（%LOCALAPPDATA%\DataRelay\bin）に置く。アプリの中身はこのフォルダー（共有）から読む。
rem  共有フォルダー上の exe が社内の設定で止められるとき・共有からの起動が遅いときに使う。
rem  1回だけでよい。共有のアプリが新しい版に置き換わると、手元の exe は起動時に自分で入れ替わる。
rem
rem    install_local.cmd              置く（デスクトップとスタートメニューにショートカットも作り、起動する）
rem    install_local.cmd /remove      手元の exe とショートカットを消す（アプリの中身・設定・記録は消さない）
rem    /quiet       最後の確認と、置いたあとの起動をしない
rem    /noshortcut  ショートカットを作らない・消さない
rem  試験用: DATARELAY_EXE_SOURCE があれば、その exe を置く（既定はこのフォルダーの DataRelay.exe）
rem
rem  このファイルは UTF-8・CRLF で保存する（.gitattributes で変換しない）。日本語は echo の行にだけ書く。
rem ======================================================================
rem このファイルのフォルダー（アプリのフォルダー）は、引数を読む前に控える。shift は %%0 もずらすので、あとで読むと別の場所になる
set "APPDIR=%~dp0"
set "APPDIR=%APPDIR:~0,-1%"
set "QUIET="
set "NOSHORTCUT="
set "REMOVE="
:args
if "%~1"=="" goto args_done
if /i "%~1"=="/quiet" set "QUIET=1"
if /i "%~1"=="/noshortcut" set "NOSHORTCUT=1"
if /i "%~1"=="/remove" set "REMOVE=1"
shift
goto args
:args_done

set "DEST=%LOCALAPPDATA%\DataRelay\bin"
set "SRC=%APPDIR%\DataRelay.exe"
if defined DATARELAY_EXE_SOURCE set "SRC=%DATARELAY_EXE_SOURCE%"
set "DR_EXE=%DEST%\DataRelay.exe"
set "DR_DEST=%DEST%"
if defined REMOVE goto remove

echo DataRelay.exe を手元に置きます。
echo   置き場: %DEST%
echo   アプリの中身（共有）: %APPDIR%
if not exist "%APPDIR%\app.py" goto not_app
if not exist "%SRC%" goto no_source
if not exist "%DEST%" mkdir "%DEST%" >nul 2>&1
if not exist "%DEST%" goto cannot_write

rem 手元の exe が動いていても置き換えられるよう、先に名前を変えてよける（動いている exe は消せないが、名前は変えられる）
if exist "%DEST%\DataRelay.old.exe" del /f /q "%DEST%\DataRelay.old.exe" >nul 2>&1
if exist "%DR_EXE%" move /y "%DR_EXE%" "%DEST%\DataRelay.old.exe" >nul 2>&1
if exist "%DR_EXE%" goto in_use
copy /y "%SRC%" "%DR_EXE%" >nul
if errorlevel 1 goto copy_failed

rem 行き先を書く。パスに & や ( ) があっても崩れないよう、遅延展開で書き出す
setlocal EnableDelayedExpansion
> "!DEST!\DataRelay.program.txt" echo # DataRelay.exe（この隣）が読むアプリのフォルダー。install_local.cmd が書きました。
>> "!DEST!\DataRelay.program.txt" echo(!APPDIR!
endlocal
echo   置きました: %DR_EXE%

if defined NOSHORTCUT goto installed
powershell -NoProfile -NonInteractive -Command "$w=New-Object -ComObject WScript.Shell; foreach($d in [Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs')){ $s=$w.CreateShortcut((Join-Path $d 'DataRelay.lnk')); $s.TargetPath=$env:DR_EXE; $s.WorkingDirectory=$env:DR_DEST; $s.Description='DataRelay'; $s.Save() }" >nul 2>&1
if errorlevel 1 goto no_shortcut
echo   デスクトップとスタートメニューに「DataRelay」を作りました。
goto installed

:no_shortcut
echo   ショートカットは作れませんでした（社内の設定で PowerShell が使えない可能性があります）。
echo   %DR_EXE% を右クリックして「スタートにピン留め」などで使ってください。

:installed
echo.
echo 完了しました。次からは、手元の DataRelay.exe（ショートカット）から起動してください。
echo 共有のアプリが新しい版になると、手元の exe は起動時に自分で入れ替わります。
if defined QUIET exit /b 0
start "" "%DR_EXE%"
pause
exit /b 0

:remove
echo 手元の DataRelay.exe を消します（アプリの中身・設定・記録は消しません）。
del /f /q "%DEST%\DataRelay.old.exe" "%DEST%\DataRelay.program.txt" >nul 2>&1
del /f /q "%DR_EXE%" >nul 2>&1
if exist "%DR_EXE%" goto in_use
if not defined NOSHORTCUT powershell -NoProfile -NonInteractive -Command "foreach($d in [Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs')){ Remove-Item -LiteralPath (Join-Path $d 'DataRelay.lnk') -ErrorAction SilentlyContinue }" >nul 2>&1
echo 消しました。
if not defined QUIET pause
exit /b 0

:not_app
echo.
echo このファイルはアプリのフォルダー（app.py がある所）に置いたまま実行してください。
goto fail
:no_source
echo.
echo 置く exe が見つかりません: %SRC%
echo 配る zip（DataRelay.zip）を展開したフォルダーから実行してください。
goto fail
:cannot_write
echo.
echo 置き場を作れません: %DEST%
goto fail
:in_use
echo.
echo 手元の DataRelay.exe が使用中で置き換えられません。DataRelay を終了してから（通知領域のアイコンの「終了」まで）もう一度実行してください。
goto fail
:copy_failed
echo.
echo exe を写せませんでした: %SRC% → %DR_EXE%
if exist "%DEST%\DataRelay.old.exe" move /y "%DEST%\DataRelay.old.exe" "%DR_EXE%" >nul 2>&1
goto fail
:fail
if not defined QUIET pause
exit /b 1
