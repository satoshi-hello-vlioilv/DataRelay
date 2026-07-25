Option Explicit

' SymfoNavi Data Hub - single hidden launcher
' No start.bat is required for normal startup.

Const APP_URL = "http://127.0.0.1:5031"
Const INSTANCE_URL = "http://127.0.0.1:5031/api/instance"
Const STARTUP_TIMEOUT_SECONDS = 60

Dim shell, fso, scriptDir, logDir, startupLog, vbsLog
Dim pythonCmd, target, commandLine, rc

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
logDir = fso.BuildPath(scriptDir, "logs")
startupLog = fso.BuildPath(logDir, "startup.log")
vbsLog = fso.BuildPath(logDir, "vbs_launcher.log")
target = fso.BuildPath(scriptDir, "start_app.py")

If Not fso.FolderExists(logDir) Then fso.CreateFolder logDir
shell.CurrentDirectory = scriptDir
WriteLog "START script=" & WScript.ScriptFullName

If Not fso.FileExists(target) Then
    Fail "start_app.py が見つかりません。", target
End If

' If the server is already running, do not create another Python process.
If ApplicationReady() Then
    WriteLog "EXISTING_SERVER detected"
    OpenBrowser
    WScript.Quit 0
End If

' Match the successful batch file's Python selection order.
pythonCmd = FindPython()
If pythonCmd = "" Then
    Fail "Pythonを起動できませんでした。", _
         "Python 3のインストール状態とPATHを確認してください。"
End If
WriteLog "PYTHON command=" & pythonCmd

' Check the exact environment selected above. Install only when imports fail.
rc = RunHiddenWait(pythonCmd & " -c " & Quote("import flask,xlrd,win32ui,dde,openpyxl") & _
                   " >> " & Quote(startupLog) & " 2>&1")
If rc <> 0 Then
    WriteLog "DEPENDENCY_CHECK failed rc=" & rc
    If Not fso.FileExists(fso.BuildPath(scriptDir, "requirements.txt")) Then
        Fail "必要なPythonパッケージが不足しています。", _
             "requirements.txt が見つかりません。"
    End If

    rc = RunHiddenWait(pythonCmd & " -m pip install --user -r " & _
                       Quote(fso.BuildPath(scriptDir, "requirements.txt")) & _
                       " >> " & Quote(startupLog) & " 2>&1")
    If rc <> 0 Then
        Fail "Pythonパッケージの導入に失敗しました。", _
             "logs\startup.log を確認してください。"
    End If
End If

' Start start_app.py without a console. The Python launcher retains
' multi-instance protection and detached app.py startup.
commandLine = pythonCmd & " " & Quote(target) & _
              " >> " & Quote(startupLog) & " 2>&1"
WriteLog "LAUNCH " & commandLine

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

' The VBS owns browser startup. This avoids dependence on Python's
' webbrowser module or the Python Install Manager windowed process.
If WaitForApplication(STARTUP_TIMEOUT_SECONDS) Then
    WriteLog "SERVER_READY url=" & APP_URL
    OpenBrowser
    WScript.Quit 0
End If

Fail "アプリサーバーの起動を確認できませんでした。", _
     "logs\vbs_launcher.log、logs\launcher.log、logs\startup.log、logs\app.log を確認してください。"

Function FindPython()
    Dim candidates, item, result
    candidates = Array("py -3", "python")
    FindPython = ""

    For Each item In candidates
        result = RunHiddenWait(CStr(item) & " --version >> " & Quote(startupLog) & " 2>&1")
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
                 " number=" & Err.Number & " description=" & Err.Description
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
    Set http = CreateObject("MSXML2.XMLHTTP.6.0")
    If Err.Number = 0 Then
        http.Open "GET", INSTANCE_URL, False
        http.setRequestHeader "Cache-Control", "no-cache"
        http.Send
        If http.Status = 200 Then
            body = http.responseText
            If InStr(1, body, "SymfoNaviDataHub", vbTextCompare) > 0 Or _
               InStr(1, body, "NaviToSQLite", vbTextCompare) > 0 Then
                ApplicationReady = True
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

    WriteLog "BROWSER_RETRY method=explorer error=" & Err.Number & " " & Err.Description
    Err.Clear
    shell.Run "explorer.exe " & Quote(APP_URL), 1, False
    If Err.Number = 0 Then
        WriteLog "BROWSER_REQUEST method=explorer result=accepted"
    Else
        WriteLog "BROWSER_FAILED error=" & Err.Number & " " & Err.Description
        MsgBox "アプリは起動しましたが、ブラウザーを開けませんでした。" & _
               vbCrLf & vbCrLf & APP_URL, vbExclamation, "SymfoNavi Data Hub"
    End If
    Err.Clear
    On Error GoTo 0
End Sub

Function Quote(value)
    Quote = Chr(34) & CStr(value) & Chr(34)
End Function

Sub WriteLog(message)
    Dim stream
    On Error Resume Next
    Set stream = fso.OpenTextFile(vbsLog, 8, True, 0)
    stream.WriteLine Now & " " & message
    stream.Close
    On Error GoTo 0
End Sub

Sub Fail(title, detail)
    WriteLog "ERROR " & title & " detail=" & detail
    MsgBox title & vbCrLf & vbCrLf & detail, vbCritical, "SymfoNavi Data Hub"
    WScript.Quit 1
End Sub
