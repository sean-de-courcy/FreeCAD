/*
init.nsh

Initialization functions
*/

#--------------------------------
# User initialization

!include WinVer.nsh

Var FCLangName

Function InitUser

  # Get FreeCAD language

  ReadRegStr $FCLangName SHELL_CONTEXT "${APP_REGKEY_SETUP}" "FreeCAD Language"

  ${If} $FCLangName != ""
    StrCpy $LangName $FCLangName
  ${EndIf}

FunctionEnd

#--------------------------------
# MultiUser custom method

Function PostMultiUserPageInit
  # restore command line install directory
  ${if} $OriginalCmdInstDir != ""
    StrCpy $INSTDIR $OriginalCmdInstDir
  ${endif}
  # check if this FreeCAD version is already installed
  ReadRegStr $0 SHCTX "${APP_UNINST_KEY}" "UninstallString"
  ${if} $0 != ""
   # check if the uninstaller was accidentally deleted
   # if so, don't bother the user if they really want to install a new FreeCAD over an existing one
   # because they won't have a chance to deny this

   # remove quotes from uninstaller filename
   ${TrimQuotes} $0 $0
   # skip message box if uninstaller file is missing
   IfFileExists $0 0 ContinueInstall

   # installing over an existing installation of the same FreeCAD release is not necessary
   # if the users does this, they most probably have a problem with FreeCAD that can better be solved
   # by reinstalling FreeCAD
   # for beta and other test releases over-installing can even cause errors
   MessageBox MB_YESNOCANCEL "$(AlreadyInstalled)" /SD IDCANCEL IDYES ContinueInstall IDNO BackToMuiltUserPage
   Quit
   BackToMuiltUserPage:
   Abort
   ContinueInstall:
  ${endif}

  # FreeCAD-CH: one unversioned install (APP_UNINST_KEY above), replaced by each release;
  # there is no series of versioned installs to scan
FunctionEnd


#--------------------------------
# visible installer sections

Section "!${APP_NAME}" SecCore
 SectionIn RO
SectionEnd

Section /o "$(SecFileAssocTitle)" SecFileAssoc
 StrCpy $CreateFileAssociations "true"
SectionEnd

Section "$(SecDesktopTitle)" SecDesktop
 StrCpy $CreateDesktopIcon "true"
SectionEnd

# Section descriptions
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
!insertmacro MUI_DESCRIPTION_TEXT ${SecCore} "$(SecCoreDescription)"
!insertmacro MUI_DESCRIPTION_TEXT ${SecFileAssoc} "$(SecFileAssocDescription)"
!insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "$(SecDesktopDescription)"
!insertmacro MUI_FUNCTION_DESCRIPTION_END


# .onInit must be here after the section definition because we have to set
# the selection states of the dictionary sections
Function .onInit
  # save INSTDIR specified with /D for later
  StrCpy $OriginalCmdInstDir $INSTDIR
  # qt6.8 has windows 10 1809 as minimum version, which is build 17763
  # build number details at https://learn.microsoft.com/en-us/windows/release-health/release-information
  ${ifnot} ${AtLeastBuild} 17763
    MessageBox MB_OK|MB_ICONSTOP "${APP_NAME} ${APP_VERSION} requires Windows 10 or newer." /SD IDOK
    Quit
  ${endif}

  # check if it is a 64bit system
  ${if} ${RunningX64}
   SetRegView 64
   !define LIBRARY_X64
  ${endif}

  # Check that FreeCAD is not currently running
  Push $R0
  Push $R1
  ${FindProc} $R0 ${BIN_FREECAD}
  ${FindProc} $R1 ${BIN_FREECADCMD}
  # if running result is '0', if not running it is '1'
  ${if} $R0 == "0"
  ${orif} $R1 == "0"
   MessageBox MB_OK|MB_ICONSTOP "$(UnInstallRunning)" /SD IDOK
   Abort
  ${endif}
  Pop $R1
  Pop $R0

  # initialize the multi-user installer UI
  !insertmacro MULTIUSER_INIT

  # this can be reset to "true" in section SecDesktop
  StrCpy $CreateDesktopIcon "false"
  StrCpy $CreateFileAssociations "false"

  ${IfNot} ${Silent}
    # Show banner while installer is initializing
    Banner::show /NOUNLOAD "Checking system"
    Banner::destroy
  ${EndIf}

  # if installer runs silent the post install mode and directory page routines have to be called here
  ${If} ${Silent}
    Call PostMultiUserPageInit
    Call ValidateInstallDir
  ${EndIf}

FunctionEnd

# this function is called at first after starting the uninstaller
Function un.onInit

  # Macro to investigate name of FreeCAD's preferences folders to be able remove them
  !insertmacro UnAppPreSuff $AppPre $AppSuff # macro from Utils.nsh

  !insertmacro MULTIUSER_UNINIT

  # Check that FreeCAD is not currently running
  Push $R0
  Push $R1
  ${FindProc} $R0 ${BIN_FREECAD}
  ${FindProc} $R1 ${BIN_FREECADCMD}
  # if running result is '0', if not running it is '1'
  ${if} $R0 == "0"
  ${orif} $R1 == "0"
   MessageBox MB_OK|MB_ICONSTOP "$(UnInstallRunning)" /SD IDOK
   Abort
  ${endif}
  Pop $R1
  Pop $R0

  # check if it is a 64bit system
  ${if} ${RunningX64}
   SetRegView 64
  ${endif}

  # Ascertain whether the user has sufficient privileges to uninstall.
  # abort when FreeCAD was installed with admin permissions but the user doesn't have administrator privileges
  ReadRegStr $0 HKLM "${APP_UNINST_KEY}" "DisplayVersion"
  ${if} $0 != ""
  ${andif} $MultiUser.Privileges != "Admin"
  ${andif} $MultiUser.Privileges != "Power"
   MessageBox MB_OK|MB_ICONSTOP "$(UnNotAdminLabel)" /SD IDOK
   Abort
  ${endif}
  # warning when FreeCAD couldn't be found in the registry
  ${if} $0 == "" # check in HKCU
   ReadRegStr $0 HKCU "${APP_UNINST_KEY}" "DisplayVersion"
   ${if} $0 == ""
     MessageBox MB_OK|MB_ICONEXCLAMATION "$(UnNotInRegistryLabel)" /SD IDOK
   ${endif}
  ${endif}

  # question message if the user really wants to uninstall FreeCAD
  MessageBox MB_ICONQUESTION|MB_YESNO|MB_DEFBUTTON2 "$(UnReallyRemoveLabel)" /SD IDYES IDYES +2 # continue if yes
  Abort

FunctionEnd
