; Namma Agent: NSIS hooks for electron-builder (Phase 9 W3).
;
; * Before installing or uninstalling, stop any Python backend still running
;   from this install, so its files can be replaced or removed.
; * On a real uninstall (not the silent uninstall an update runs), ask whether
;   to keep the user's chats, settings and keys. "No" (the default) keeps them
;   in %APPDATA%\Namma Agent, so reinstalling picks up where they left off.
; * Remove what the app registered at runtime: the namma:// handler and the
;   start-at-login entry, so an uninstall leaves no registry residue.

!macro nammaStopBackend
  nsExec::Exec `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Get-Process python,pythonw -ErrorAction SilentlyContinue | Where-Object { $$_.Path -like '$INSTDIR\*' } | Stop-Process -Force"`
  Pop $0
!macroend

!macro customInit
  !insertmacro nammaStopBackend
!macroend

!macro customUnInstall
  !insertmacro nammaStopBackend

  DeleteRegKey HKCU "Software\Classes\namma"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "NammaAgent"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run" "NammaAgent"

  ${ifNot} ${isUpdated}
    ${ifNot} ${Silent}
      MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 \
        "Also delete your chats, settings and API keys?$\r$\n$\r$\nChoose No to keep them in $APPDATA\Namma Agent, so they are there if you reinstall." \
        /SD IDNO IDNO namma_keep_data
        SetShellVarContext current
        RMDir /r "$APPDATA\Namma Agent"
      namma_keep_data:
    ${endIf}
  ${endIf}
!macroend
