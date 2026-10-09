' Silent process launcher for Task Scheduler actions.
' Unlike "powershell -WindowStyle Hidden", WScript.Shell.Run with window
' style 0 never allocates a visible console window at all -- no flash.
'
' Each command-line token (exe + each arg) is passed as a SEPARATE argument
' to this script; we re-quote them ourselves and hand the whole line to
' Shell.Run. Exit code of the child process is propagated.
'
' Task Scheduler starts wscript in System32 when a task has no working
' directory, and children inherit it, so the child cwd is anchored to the
' repo root (this file lives in ops\windows\).

Set objShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
objShell.CurrentDirectory = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))

Set objArgs = WScript.Arguments

cmd = ""
For i = 0 To objArgs.Count - 1
    a = objArgs(i)
    cmd = cmd & """" & a & """ "
Next
cmd = Trim(cmd)

rc = objShell.Run(cmd, 0, True)
WScript.Quit rc
