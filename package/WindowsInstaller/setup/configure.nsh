/*

configure.nsh

Write registry information and configure FreeCAD

*/

#!define SHORTCUT '${APP_NAME} ${APP_SERIES_NAME}.lnk" "$INSTDIR\${APP_RUN}" "" "$INSTDIR\${APP_RUN}" "" "" "" "${APP_SHORTCUT_INFO}"'

#--------------------------------
# Registry information

Section -InstallData

  # Registry information
  WriteRegStr SHCTX ${APP_REGKEY} "" $INSTDIR
  WriteRegStr SHCTX ${APP_REGKEY} "Version" "${APP_VERSION_NUMBER}"

  # Start Menu shortcut
  SetOutPath "$INSTDIR\bin" # this is the folder in which the shortcut is executed
  # we must assure that the folder is not empty (happens on silent install and can accidentally happen)
  ${if} $StartmenuFolder == ""
   StrCpy $StartmenuFolder "${APP_DIR}"
  ${endif}
  CreateDirectory "$SMPROGRAMS\$StartmenuFolder"
  CreateShortCut "$SMPROGRAMS\$StartmenuFolder\${APP_NAME}.lnk" "$INSTDIR\${APP_RUN}" "" "$INSTDIR\${APP_RUN}" "" "" "" "${APP_SHORTCUT_INFO}"
  # Link to website and Wiki
  WriteINIStr "$SMPROGRAMS\$StartmenuFolder\${APP_WEBPAGE_INFO}.url" "InternetShortcut" "URL" "${APP_WEBPAGE}"
  WriteINIStr "$SMPROGRAMS\$StartmenuFolder\${APP_WIKI_INFO}.url" "InternetShortcut" "URL" "${APP_WIKI}"
  # create desktop icon
  ${if} $CreateDesktopIcon == "true"
   SetOutPath "$INSTDIR\bin"
   CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_RUN}" "" "$INSTDIR\${APP_RUN}" "" "" "" "${APP_SHORTCUT_INFO}"
  ${endif}

  # Uninstaller information
  ${If} $MultiUser.InstallMode == "CurrentUser"
    WriteRegStr SHCTX ${APP_UNINST_KEY} "DisplayName" "${APP_NAME} ${APP_FORK_VERSION} $(TEXT_INSTALL_CURRENTUSER)"
  ${Else}
    WriteRegStr SHCTX ${APP_UNINST_KEY} "DisplayName" "${APP_NAME} ${APP_FORK_VERSION}"
  ${EndIf}

  WriteRegStr SHCTX ${APP_UNINST_KEY} "UninstallString" '"$INSTDIR\${SETUP_UNINSTALLER}"'
  WriteRegStr SHCTX ${APP_UNINST_KEY} "QuietUninstallString" "$\"$INSTDIR\${SETUP_UNINSTALLER}$\" /S"
  WriteRegStr SHCTX ${APP_UNINST_KEY} "DisplayVersion" "${APP_FORK_VERSION}"
  WriteRegStr SHCTX ${APP_UNINST_KEY} "DisplayIcon" "$INSTDIR\${APP_RUN}"
  WriteRegStr SHCTX ${APP_UNINST_KEY} "URLUpdateInfo" "${APP_WEBPAGE}"
  WriteRegStr SHCTX ${APP_UNINST_KEY} "URLInfoAbout" "${APP_WEBPAGE}"
  WriteRegStr SHCTX ${APP_UNINST_KEY} "Publisher" "${APP_PUBLISHER}"
  WriteRegStr SHCTX ${APP_UNINST_KEY} "HelpLink" "${APP_WEBPAGE}"
  WriteRegDWORD SHCTX ${APP_UNINST_KEY} "NoModify" 0x00000001
  WriteRegDWORD SHCTX ${APP_UNINST_KEY} "NoRepair" 0x00000001
  WriteRegStr SHCTX ${APP_UNINST_KEY} "StartMenu" "$SMPROGRAMS\$StartmenuFolder"

  # FreeCAD-CH: the keys are unversioned, so a new release reuses them: no older keys to remove

SectionEnd

#--------------------------------
# Write FreeCAD file associations

Section -Configure

  # FreeCAD-CH: its own ProgID (FreeCAD-CH.Document), always listed under "Open with" for
  # .FCStd. It becomes the default only when the user ticks the box (SecFileAssoc, off by
  # default); otherwise official FreeCAD keeps .FCStd. No App Paths entry, and no thumbnail
  # handler: official FreeCAD's handler (same DLL path and CLSID) already covers .FCStd.
  WriteRegStr SHCTX "Software\Classes\${APP_REGNAME_DOC}" "" "${APP_NAME} Document"
  WriteRegStr SHCTX "Software\Classes\${APP_REGNAME_DOC}\DefaultIcon" "" "$INSTDIR\${APP_RUN},0"
  WriteRegStr SHCTX "Software\Classes\${APP_REGNAME_DOC}\Shell\open\command" "" '"$INSTDIR\${APP_RUN}" --single-instance "%1"'
  WriteRegStr SHCTX "Software\Classes\${APP_EXT}\OpenWithProgids" "${APP_REGNAME_DOC}" ""

  ${if} $CreateFileAssociations == "true"
   WriteRegStr SHCTX "Software\Classes\${APP_EXT}" "" "${APP_REGNAME_DOC}"
   WriteRegStr SHCTX "Software\Classes\${APP_EXT}" "Content Type" "${APP_MIME_TYPE}"
  ${endif}
  # the package carries no thumbnail handler to keep
  RMDir /r "$INSTDIR\thumbnail"

  # Eventually refresh shell icons
  ${RefreshShellIcons}

SectionEnd

#--------------------------------
#
