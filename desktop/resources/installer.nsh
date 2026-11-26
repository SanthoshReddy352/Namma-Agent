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

; Refresh Windows' icon cache so Start shows the app's own icon, not one cached
; for the same AppUserModelID by an earlier copy (e.g. a development run).
!macro customInstall
  nsExec::Exec `"$SYSDIR\ie4uinit.exe" -show`
  Pop $0
!macroend

; Finish page. Same as electron-builder's default (a "Run Namma Agent" box),
; except for an UPDATE: the app runs the installer visibly (not /S) so the user
; sees the progress page instead of the app silently vanishing for minutes, and
; once the files are in, the installer reopens the app by itself and closes,
; with no extra click.
!macro customFinishPage
  Function nammaStartApp
    ${if} ${isUpdated}
      StrCpy $1 "--updated"
    ${else}
      StrCpy $1 ""
    ${endif}
    ${StdUtils.ExecShellAsUser} $0 "$launchLink" "open" "$1"
  FunctionEnd

  Function nammaFinishPre
    ${if} ${isUpdated}
      Call nammaStartApp
      Abort
    ${endif}
  FunctionEnd

  !define MUI_FINISHPAGE_RUN
  !define MUI_FINISHPAGE_RUN_FUNCTION "nammaStartApp"
  !define MUI_PAGE_CUSTOMFUNCTION_PRE nammaFinishPre
  !insertmacro MUI_PAGE_FINISH
!macroend

!macro customUnInstall
  ; Leave the install dir as the working directory, or RMDir /r can't remove
  ; the (empty) folder itself afterwards.
  SetOutPath "$TEMP"
  !insertmacro nammaStopBackend

  DeleteRegKey HKCU "Software\Classes\namma"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "NammaAgent"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run" "NammaAgent"

  ${ifNot} ${isUpdated}
    ; electron-updater's copy of the installer (kept for differential updates).
    RMDir /r "$LOCALAPPDATA\namma-agent-desktop-updater"

    ; The in-app uninstall (Settings -> About) has already asked and passes
    ; --delete-app-data or --keep-app-data; only otherwise ask here.
    StrCpy $R2 "ask"
    ${GetParameters} $R0
    ClearErrors
    ${GetOptions} $R0 "--delete-app-data" $R1
    ${ifNot} ${Errors}
      StrCpy $R2 "delete"
    ${endIf}
    ClearErrors
    ${GetOptions} $R0 "--keep-app-data" $R1
    ${ifNot} ${Errors}
      StrCpy $R2 "keep"
    ${endIf}
    ${if} $R2 == "ask"
    ${andIfNot} ${Silent}
      MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 \
        "Also delete your chats, settings and API keys?$\r$\n$\r$\nChoose No to keep them in $APPDATA\Namma Agent, so they are there if you reinstall." \
        /SD IDNO IDNO +2
      StrCpy $R2 "delete"
    ${endIf}
    ${if} $R2 == "delete"
      SetShellVarContext current
      RMDir /r "$APPDATA\Namma Agent"
    ${endIf}
  ${endIf}
!macroend
