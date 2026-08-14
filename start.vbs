Option Explicit

' DataRelay - single hidden launcher
' Normal startup does not require start.bat.

Const APP_URL = "http://127.0.0.1:5031"
Const INSTANCE_URL = "http://127.0.0.1:5031/api/instance"
Const STARTUP_TIMEOUT_SECONDS = 60
Const LOCAL_APP_FOLDER = "DataRelay"

Dim shell, fso, processEnv
Dim scriptDir, localAppData, localRoot, runtimeDir, logDir, pycacheDir
Dim startupLog, vbsLog, target, requirementsFile, requirementsAlt, missingList, depName, requiredMissing
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
' Only Flask is needed for the app to start. xlrd / win32ui / dde back DDE
' extraction and XLS reading, openpyxl backs XLSX; each reports at the point of
' use, so a site that cannot reach PyPI can still run everything else.
missingList = MissingPackages()
requiredMissing = ""
If InStr(missingList, "flask") > 0 Then requiredMissing = "flask"
rc = 0
If missingList <> "" Then rc = 1
WriteLog "TIMING dependency_check_seconds=" & FormatNumber(Timer() - tPhase, 2) & " rc=" & rc
If rc <> 0 Then
    WriteLog "DEPENDENCY_CHECK failed rc=" & rc & " missing=" & missingList & " required=" & requiredMissing

    If fso.FileExists(requirementsFile) Then
        tPhase = Timer()
        rc = RunHiddenWait(pythonCmd & " -m pip install --user -r " & _
                           Quote(requirementsFile) & _
                           " >> " & Quote(startupLog) & " 2>&1")
        WriteLog "TIMING pip_install_seconds=" & FormatNumber(Timer() - tPhase, 2) & " rc=" & rc
        ' pip can report success while an import still fails, so ask again.
        missingList = MissingPackages()
        requiredMissing = ""
        If InStr(missingList, "flask") > 0 Then requiredMissing = "flask"
        WriteLog "DEPENDENCY_RECHECK missing=" & missingList
    Else
        WriteLog "REQUIREMENTS missing file=" & requirementsFile & " alt=" & requirementsAlt
    End If

    If requiredMissing <> "" Then
        Fail "必要なPythonパッケージが不足しています。", _
             "不足: " & missingList & vbCrLf & _
             "requirements.txt: " & requirementsFile & vbCrLf & _
             "ログ: " & startupLog
    End If

    If missingList <> "" Then
        ' Missing optional packages only disable their own feature.
        WriteLog "DEPENDENCY_OPTIONAL_MISSING continue missing=" & missingList
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
    ' Cache only a fully satisfied environment, so a later manual install is noticed.
    If missingList = "" Then WriteStartupCache pythonCmd
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
                If InStr(1, body, "DataRelay", vbTextCompare) > 0 Or _
                   InStr(1, body, "SymfoNaviDataHub", vbTextCompare) > 0 Or _
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
               vbExclamation, "DataRelay"
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
           vbCritical, "DataRelay"
    WScript.Quit 1
End Sub

Sub FailEarly(title, detail)
    MsgBox title & vbCrLf & vbCrLf & detail, _
           vbCritical, "DataRelay"
    WScript.Quit 1
End Sub


' ==== Startup helpers: loading modal, browser handoff, startup cache ====
' 起動待ちモーダルへ差し込むバージョン。出どころは次の順で選ぶ。
'   1) app.py の APP_VERSION（初回起動でも更新直後でも正しい）
'   2) runtime\version.txt（アプリが起動するたびに書き出す控え。1が読めないとき用）
'   3) どちらも駄目なら差し込まない。画面側が「バージョン確認中」と出す。
Function SourceVersion()
    Dim si, head, at, body, q, k, ap
    SourceVersion = ""
    On Error Resume Next
    ' 版は navi_version.py にある（v1.64.0で app.py から分けた）。
    ' 古い配置でも起動できるよう、無ければ app.py を見に行く。
    ap = fso.BuildPath(fso.BuildPath(scriptDir, "lib"), "navi_version.py")
    If Not fso.FileExists(ap) Then ap = fso.BuildPath(scriptDir, "app.py")
    If Not fso.FileExists(ap) Then Exit Function
    Set si = CreateObject("ADODB.Stream")
    si.Type = 2 : si.Charset = "utf-8" : si.Open
    si.LoadFromFile ap
    head = si.ReadText(8192)
    si.Close
    If Err.Number <> 0 Or Len(head) = 0 Then
        Err.Clear
        Exit Function
    End If
    ' APP_VERSION は APP_VERSION_TITLE や BUILD_VERSION の中にも現れる。
    ' 「APP_VERSION の直後が = で、その先が引用符」のものだけを版として受け取り、
    ' 当てはまらなければ次の出現位置へ進む。
    at = 1
    Do
        at = InStr(at, head, "APP_VERSION")
        If at = 0 Then Exit Do
        body = LTrim(Mid(head, at + Len("APP_VERSION")))
        If Left(body, 1) = "=" Then
            body = LTrim(Mid(body, 2))
            q = Left(body, 1)
            If q = "'" Or q = Chr(34) Then
                body = Mid(body, 2)
                k = InStr(body, q)
                If k > 0 Then
                    body = Trim(Left(body, k - 1))
                    If VersionLooksValid(body) Then
                        SourceVersion = body
                        Exit Do
                    End If
                End If
            End If
        End If
        at = at + Len("APP_VERSION")
    Loop
    Err.Clear
    On Error GoTo 0
End Function

' 版として通す形は、数字と点だけ。ここを緩めると読み違えがそのまま画面へ出る。
Function VersionLooksValid(v)
    Dim n, c
    VersionLooksValid = False
    If Len(v) = 0 Or Len(v) > 20 Then Exit Function
    For n = 1 To Len(v)
        c = Mid(v, n, 1)
        If InStr("0123456789.", c) = 0 Then Exit Function
    Next
    VersionLooksValid = True
End Function

Function StampedVersion()
    Dim vf, ts, txt, parts
    StampedVersion = ""
    On Error Resume Next
    vf = fso.BuildPath(fso.BuildPath(localRoot, "runtime"), "version.txt")
    If fso.FileExists(vf) Then
        Set ts = fso.OpenTextFile(vf, 1, False)
        txt = ts.ReadAll
        ts.Close
        parts = Split(txt, vbTab)
        If UBound(parts) >= 0 Then StampedVersion = Trim(parts(0))
    End If
    Err.Clear
    On Error GoTo 0
End Function

' loading.html は UTF-8。FileSystemObject の OpenTextFile / CreateTextFile は
' ANSI(cp932)で読み書きするため、そのまま通すと日本語が壊れ、タグまで崩れて起動できなくなる
' （v1.49.0 の実害）。UTF-8 を正しく扱える ADODB.Stream を使い、書き上がりを確かめてから差し替える。
Function WriteLoadingWithVersion(src, dst, ver)
    Dim si, so, html, tmp
    WriteLoadingWithVersion = False
    On Error Resume Next
    If Len(ver) = 0 Then Exit Function
    Set si = CreateObject("ADODB.Stream")
    si.Type = 2 : si.Charset = "utf-8" : si.Open
    si.LoadFromFile src
    html = si.ReadText
    si.Close
    If Err.Number <> 0 Or Len(html) = 0 Then Err.Clear : Exit Function
    If InStr(html, "{{APP_VERSION}}") = 0 Then Exit Function
    ' 読めた中身がHTMLの体をなしているかを見る。文字化けしていれば必ずここで落ちる。
    If InStr(html, "<!doctype html>") = 0 Or InStr(html, "</html>") = 0 Then Exit Function
    html = Replace(html, "{{APP_VERSION}}", ver)
    tmp = dst & ".tmp"
    Set so = CreateObject("ADODB.Stream")
    so.Type = 2 : so.Charset = "utf-8" : so.Open
    so.WriteText html
    so.SaveToFile tmp, 2
    so.Close
    ' 書けたものが本当にHTMLかを確かめてから置き換える。壊れたものを掴ませない。
    If Err.Number = 0 And fso.FileExists(tmp) Then
        If fso.GetFile(tmp).Size > 1000 Then
            fso.CopyFile tmp, dst, True
            If Err.Number = 0 Then WriteLoadingWithVersion = True
        End If
        fso.DeleteFile tmp, True
    End If
    Err.Clear
    On Error GoTo 0
End Function

Sub OpenLoading()
    Dim src, dst, appSh, ver, stamped, vsrc
    On Error Resume Next
    src = fso.BuildPath(scriptDir, "loading.html")
    dst = fso.BuildPath(localRoot, "loading.html")
    If fso.FileExists(src) Then
        ver = SourceVersion()
        vsrc = "app.py"
        If ver = "" Then
            ver = StampedVersion()
            vsrc = "version.txt"
        End If
        stamped = WriteLoadingWithVersion(src, dst, ver)
        If stamped Then
            WriteLog "LOADING_MODAL version=" & ver & " source=" & vsrc
        Else
            ' 差し込めなければ丸ごとコピーする。画面側が token を見て「確認中」と出す。
            Err.Clear
            fso.CopyFile src, dst, True
            WriteLog "LOADING_MODAL version=(none) copied-as-is"
        End If
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

Function MissingPackages()
    ' Import each package on its own; a combined import stops at the first failure.
    Dim n, out
    out = ""
    For Each n In Array("flask", "xlrd", "win32ui", "dde", "openpyxl")
        If RunHiddenWait(pythonCmd & " -c " & Quote("import " & n) & _
                         " >> " & Quote(startupLog) & " 2>&1") <> 0 Then
            If out <> "" Then out = out & ", "
            out = out & n
        End If
    Next
    MissingPackages = out
End Function

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
