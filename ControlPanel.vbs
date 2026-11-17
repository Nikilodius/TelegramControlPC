' Открывает панель управления Telegram PC Control без окна консоли.
' Просто дважды кликни этот файл (или помести ярлык на него на рабочий стол).

Set fso = CreateObject("Scripting.FileSystemObject")
Set objShell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
objShell.CurrentDirectory = scriptDir

pythonw = scriptDir & "\.venv\Scripts\pythonw.exe"
panel = scriptDir & "\control_panel.pyw"

If fso.FileExists(pythonw) Then
    objShell.Run """" & pythonw & """ """ & panel & """", 0, False
Else
    objShell.Run "pythonw """ & panel & """", 0, False
End If
