' SymfoNavi Data Hub - hidden launcher.
' Starts start_app.py (single-instance guard + detached app.py + opens the browser)
' without ever showing a console/command-prompt window.
' Initial setup (installing Python packages) should still be done once via start.bat;
' this script assumes the required packages are already installed.
Option Explicit

Dim shell, fso, scriptDir, target, launched, errMsg

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
target = scriptDir & "\start_app.py"

If Not fso.FileExists(target) Then
    MsgBox "start_app.py が見つかりません。" & vbCrLf & vbCrLf & target, vbCritical, "SymfoNavi Data Hub"
    WScript.Quit 1
End If

shell.CurrentDirectory = scriptDir
launched = False
errMsg = ""

On Error Resume Next

' pythonw.exe (コンソールを持たないPython)を優先する。
Err.Clear
shell.Run "pythonw.exe """ & target & """", 0, False
If Err.Number = 0 Then
    launched = True
Else
    errMsg = Err.Description
End If

If Not launched Then
    Err.Clear
    shell.Run "python.exe """ & target & """", 0, False
    If Err.Number = 0 Then
        launched = True
    Else
        errMsg = Err.Description
    End If
End If

On Error Goto 0

If Not launched Then
    MsgBox "Pythonを起動できませんでした。" & vbCrLf & _
           "Python 3がインストールされ、PATHに登録されているか確認してください。" & vbCrLf & vbCrLf & _
           "初回セットアップが未実施の場合は、先に start.bat を一度実行してください。" & vbCrLf & vbCrLf & _
           "詳細: " & errMsg, vbCritical, "SymfoNavi Data Hub"
    WScript.Quit 1
End If
