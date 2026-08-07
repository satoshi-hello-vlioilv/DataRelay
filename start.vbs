Option Explicit

' SymfoNavi Data Hub - single hidden launcher
' Normal startup does not require start.bat.

Const APP_URL = "http://127.0.0.1:5031"
Const INSTANCE_URL = "http://127.0.0.1:5031/api/instance"
Const STARTUP_TIMEOUT_SECONDS = 60
Const LOCAL_APP_FOLDER = "SymfoNaviDataHub"

Dim shell, fso, processEnv
Dim scriptDir, localAppData, localRoot, runtimeDir, logDir, pycacheDir
Dim startupLog, vbsLog, target, requirementsFile, requirementsAlt
Dim pythonCmd, commandLine, rc
Dim tStart, tPhase
Dim loadingShown, cacheFile
Dim cachedPython, needVerify
loadingShown = False

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
Set processEnv = shell.Environment("Process")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
localAppData = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%")

If localAppData = "" Or InStr(localAppData, "%LOCALAPPDATA%") > 0 Then
    localAppData = shell.ExpandEnvironmentStrings("%TEMP%")
End If

If localAppData = "" Or InStr(localAppData, "%TEMP%") > 0 Then
    FailEarly "ローカル保存先を特定できません。", _
              "LOCALAPPDATAおよびTEMP環境変数を確認してください。"
End If

localRoot = fso.BuildPath(localAppData, LOCAL_APP_FOLDER)
runtimeDir = fso.BuildPath(localRoot, "runtime")
logDir = fso.BuildPath(localRoot, "logs")
pycacheDir = fso.BuildPath(localRoot, "pycache")
startupLog = fso.BuildPath(logDir, "startup.log")
vbsLog = fso.BuildPath(logDir, "vbs_launcher.log")
target = fso.BuildPath(scriptDir, "start_app.py")
' requirements.txt lives under config\. Older layouts kept it beside start.vbs,
' so fall back to that location instead of reporting the file as missing.
requirementsAlt = fso.BuildPath(scriptDir, "requirements.txt")
requirementsFile = fso.BuildPath(fso.BuildPath(scriptDir, "config"), "requirements.txt")
If Not fso.FileExists(requirementsFile) Then
    If fso.FileExists(requirementsAlt) Then requirementsFile = requirementsAlt
End If

EnsureFolder localRoot
EnsureFolder runtimeDir
EnsureFolder logDir
EnsureFolder pycacheDir

' These variables must be set before starting any Python process.
' Direct assignment intentionally overrides stale or incorrect values.
processEnv("NAVI_LOCAL_ROOT") = localRoot
processEnv("PYTHONPYCACHEPREFIX") = pycacheDir
processEnv("PYTHONDONTWRITEBYTECODE") = "0"
processEnv("NAVI_BROWSER_BY_VBS") = "1"

shell.CurrentDirectory = scriptDir

WriteLog "START script=" & WScript.ScriptFullName
WriteLog "REQUIREMENTS resolved=" & requirementsFile & " exists=" & CStr(fso.FileExists(requirementsFile))
WriteLog "APP_SOURCE=" & scriptDir
WriteLog "LOCAL_ROOT=" & localRoot
WriteLog "PYTHONPYCACHEPREFIX=" & processEnv("PYTHONPYCACHEPREFIX")
WriteLog "STARTUP_LOG=" & startupLog
tStart = Timer()
' 襍ｷ蜍慕峩蠕後↓蠕�讖溘Δ繝ｼ繝繝ｫ(loading.html)繧偵ヶ繝ｩ繧ｦ繧ｶ繝ｼ縺ｧ陦ｨ遉ｺ縺励∵ｺ門ｙ螳御ｺ�縺ｧ閾ｪ蜍暮�ｷ遘ｻ縺輔○繧九�
OpenLoading

If Not fso.FileExists(target) Then
    Fail "start_app.py が見つかりません。", target
End If

' If the server is already running, do not create another Python process.
If ApplicationReady() Then
    WriteLog "EXISTING_SERVER detected"
    EnsureBrowser
    WScript.Quit 0
End If

' Startup cache: skip Python discovery and dependency check when a previous boot succeeded.
cachedPython = ReadStartupCache()
If cachedPython <> "" Then
    pythonCmd = cachedPython
    needVerify = False
    WriteLog "STARTUP_CACHE hit python=" & pythonCmd & " (discovery and dependency check skipped)"
Else
    needVerify = True
End If

' Match the successful batch file's Python selection order.
If needVerify Then
tPhase = Timer()
pythonCmd = FindPython()
If pythonCmd = "" Then
    Fail "Pythonを起動できませんでした。", _
         "Python 3のインストール状態とPATHを確認してください。" & vbCrLf & _
         "ログ: " & startupLog
End If
WriteLog "PYTHON command=" & pythonCmd
WriteLog "TIMING python_discovery_seconds=" & FormatNumber(Timer() - tPhase, 2)
End If

' Check the selected Python environment. Install only when imports fail.
If needVerify Then
tPhase = Timer()
rc = RunHiddenWait(pythonCmd & " -c " & Quote("import flask,xlrd,win32ui,dde,openpyxl") & _
                   " >> " & Quote(startupLog) & " 2>&1")
WriteLog "TIMING dependency_check_seconds=" & FormatNumber(Timer() - tPhase, 2) & " rc=" & rc
If rc <> 0 Then
    WriteLog "DEPENDENCY_CHECK failed rc=" & rc

    If Not fso.FileExists(requirementsFile) Then
        Fail "必要なPythonパッケージが不足しています。", _
             "requirements.txt が見つかりません。" & vbCrLf & _
             "確認先: " & requirementsFile & vbCrLf & requirementsAlt
    End If

    tPhase = Timer()
    rc = RunHiddenWait(pythonCmd & " -m pip install --user -r " & _
                       Quote(requirementsFile) & _
                       " >> " & Quote(startupLog) & " 2>&1")
    WriteLog "TIMING pip_install_seconds=" & FormatNumber(Timer() - tPhase, 2) & " rc=" & rc
    If rc <> 0 Then
        Fail "Pythonパッケージの導入に失敗しました。", _
             "ログを確認してください。" & vbCrLf & startupLog
    End If
End If
End If

' Start start_app.py without a console.
commandLine = pythonCmd & " " & Quote(target) & _
              " >> " & Quote(startupLog) & " 2>&1"
WriteLog "LAUNCH command=" & commandLine

On Error Resume Next
Err.Clear
rc = shell.Run(ComSpecCommand(commandLine), 0, False)
If Err.Number <> 0 Then
    Dim launchError
    launchError = "Err " & Err.Number & ": " & Err.Description
    On Error GoTo 0
    Fail "アプリの起動要求に失敗しました。", launchError
End If
On Error GoTo 0

' The VBS owns browser startup.
tPhase = Timer()
If WaitForApplication(STARTUP_TIMEOUT_SECONDS) Then
    WriteLog "TIMING launch_to_server_ready_seconds=" & FormatNumber(Timer() - tPhase, 2)
    WriteLog "TIMING total_startup_seconds=" & FormatNumber(Timer() - tStart, 2)
    WriteLog "SERVER_READY url=" & APP_URL
    WriteStartupCache pythonCmd
    EnsureBrowser
    WScript.Quit 0
End If
DeleteStartupCache

Fail "アプリサーバーの起動を確認できませんでした。", _
     "次のローカルログを確認してください。" & vbCrLf & _
     vbsLog & vbCrLf & _
     startupLog & vbCrLf & _
     fso.BuildPath(logDir, "launcher.log") & vbCrLf & _
     fso.BuildPath(logDir, "app.log")

Function FindPython()
    Dim candidates, item, result
    candidates = Array("py -3", "python")
    FindPython = ""

    For Each item In candidates
        result = RunHiddenWait(CStr(item) & " --version >> " & _
                               Quote(startupLog) & " 2>&1")
        If result = 0 Then
            FindPython = CStr(item)
            Exit Function
        End If
        WriteLog "PYTHON_SKIP command=" & CStr(item) & " rc=" & result
    Next
End Function

Function RunHiddenWait(innerCommand)
    On Error Resume Next
    Err.Clear
    RunHiddenWait = shell.Run(ComSpecCommand(innerCommand), 0, True)
    If Err.Number <> 0 Then
        WriteLog "RUN_ERROR command=" & innerCommand & _
                 " number=" & Err.Number & _
                 " description=" & Err.Description
        RunHiddenWait = -1
    End If
    Err.Clear
    On Error GoTo 0
End Function

Function ComSpecCommand(innerCommand)
    ComSpecCommand = shell.ExpandEnvironmentStrings("%ComSpec%") & _
                     " /d /s /c " & Quote(innerCommand)
End Function

Function ApplicationReady()
    Dim http, body
    ApplicationReady = False
    Set http = Nothing

    On Error Resume Next
    Err.Clear
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    If Err.Number = 0 Then
        http.setTimeouts 500, 500, 800, 800
        http.Open "GET", INSTANCE_URL, False
        http.setRequestHeader "Cache-Control", "no-cache"
        http.Send
        If Err.Number = 0 Then
            If http.Status = 200 Then
                body = http.responseText
                If InStr(1, body, "SymfoNaviDataHub", vbTextCompare) > 0 Or _
                   InStr(1, body, "NaviToSQLite", vbTextCompare) > 0 Then
                    ApplicationReady = True
                End If
            End If
        End If
    End If
    Err.Clear
    On Error GoTo 0
End Function

Function WaitForApplication(seconds)
    Dim n
    WaitForApplication = False

    For n = 1 To seconds * 2
        If ApplicationReady() Then
            WaitForApplication = True
            Exit Function
        End If
        WScript.Sleep 500
    Next
End Function

Sub OpenBrowser()
    Dim appShell
    WriteLog "BROWSER_REQUEST url=" & APP_URL

    On Error Resume Next
    Err.Clear
    Set appShell = CreateObject("Shell.Application")
    appShell.ShellExecute APP_URL, "", "", "open", 1
    If Err.Number = 0 Then
        WriteLog "BROWSER_REQUEST method=Shell.Application result=accepted"
        On Error GoTo 0
        Exit Sub
    End If

    WriteLog "BROWSER_RETRY method=explorer error=" & _
             Err.Number & " " & Err.Description
    Err.Clear
    shell.Run "explorer.exe " & Quote(APP_URL), 1, False
    If Err.Number = 0 Then
        WriteLog "BROWSER_REQUEST method=explorer result=accepted"
    Else
        WriteLog "BROWSER_FAILED error=" & Err.Number & " " & Err.Description
        MsgBox "アプリは起動しましたが、ブラウザーを開けませんでした。" & _
               vbCrLf & vbCrLf & APP_URL, _
               vbExclamation, "SymfoNavi Data Hub"
    End If
    Err.Clear
    On Error GoTo 0
End Sub

Sub EnsureFolder(path)
    Dim parent
    If fso.FolderExists(path) Then Exit Sub

    parent = fso.GetParentFolderName(path)
    If parent <> "" And Not fso.FolderExists(parent) Then
        EnsureFolder parent
    End If
    fso.CreateFolder path
End Sub

Function Quote(value)
    Quote = Chr(34) & CStr(value) & Chr(34)
End Function

Sub WriteLog(message)
    Dim stream
    On Error Resume Next
    Set stream = fso.OpenTextFile(vbsLog, 8, True, 0)
    If Err.Number = 0 Then
        stream.WriteLine Now & " " & message
        stream.Close
    End If
    Err.Clear
    On Error GoTo 0
End Sub

Sub Fail(title, detail)
    WriteLog "ERROR " & title & " detail=" & detail
    MsgBox title & vbCrLf & vbCrLf & detail, _
           vbCritical, "SymfoNavi Data Hub"
    WScript.Quit 1
End Sub

Sub FailEarly(title, detail)
    MsgBox title & vbCrLf & vbCrLf & detail, _
           vbCritical, "SymfoNavi Data Hub"
    WScript.Quit 1
End Sub


' ==== Startup helpers: loading modal, browser handoff, startup cache ====
Sub OpenLoading()
    Dim src, dst, appSh
    On Error Resume Next
    src = fso.BuildPath(scriptDir, "loading.html")
    dst = fso.BuildPath(localRoot, "loading.html")
    If fso.FileExists(src) Then
        fso.CopyFile src, dst, True
        If Err.Number = 0 And fso.FileExists(dst) Then
            Set appSh = CreateObject("Shell.Application")
            appSh.ShellExecute dst, "", "", "open", 1
            If Err.Number = 0 Then
                loadingShown = True
                WriteLog "LOADING_MODAL shown path=" & dst
            End If
        End If
    Else
        WriteLog "LOADING_MODAL source-missing path=" & src
    End If
    Err.Clear
    On Error GoTo 0
End Sub

Sub EnsureBrowser()
    If loadingShown Then
        WriteLog "BROWSER_HANDLED_BY loading-modal"
    Else
        OpenBrowser
    End If
End Sub

Function ReqSig()
    Dim f
    ReqSig = "noreq"
    On Error Resume Next
    If fso.FileExists(requirementsFile) Then
        Set f = fso.GetFile(requirementsFile)
        ReqSig = CStr(f.Size) & "_" & CStr(f.DateLastModified)
    End If
    Err.Clear
    On Error GoTo 0
End Function

Function ReadStartupCache()
    Dim ts, line, py, sig
    ReadStartupCache = ""
    cacheFile = fso.BuildPath(runtimeDir, "startup_cache.txt")
    py = "" : sig = ""
    On Error Resume Next
    If fso.FileExists(cacheFile) Then
        Set ts = fso.OpenTextFile(cacheFile, 1, False, 0)
        Do Until ts.AtEndOfStream
            line = ts.ReadLine
            If Left(line, 7) = "PYTHON=" Then py = Mid(line, 8)
            If Left(line, 7) = "REQSIG=" Then sig = Mid(line, 8)
        Loop
        ts.Close
    End If
    Err.Clear
    On Error GoTo 0
    If py <> "" And sig = ReqSig() Then
        ReadStartupCache = py
    End If
End Function

Sub WriteStartupCache(py)
    Dim ts
    cacheFile = fso.BuildPath(runtimeDir, "startup_cache.txt")
    On Error Resume Next
    Set ts = fso.OpenTextFile(cacheFile, 2, True, 0)
    If Err.Number = 0 Then
        ts.WriteLine "PYTHON=" & py
        ts.WriteLine "REQSIG=" & ReqSig()
        ts.Close
        WriteLog "STARTUP_CACHE write python=" & py
    End If
    Err.Clear
    On Error GoTo 0
End Sub

Sub DeleteStartupCache()
    cacheFile = fso.BuildPath(runtimeDir, "startup_cache.txt")
    On Error Resume Next
    If fso.FileExists(cacheFile) Then
        fso.DeleteFile cacheFile, True
        WriteLog "STARTUP_CACHE cleared (re-verify on next start)"
    End If
    Err.Clear
    On Error GoTo 0
End Sub
