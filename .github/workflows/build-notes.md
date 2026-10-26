> [!IMPORTANT]
> FreeCAD-CH build: FreeCAD with V2 topological naming (upstream FreeCAD PR 31040) and the fork's changes. Files saved by this release open in later FreeCAD-CH releases and recompute to the same geometry and references. Files saved by earlier preview builds are not covered, and a file saved by this release may not open correctly in an older build, so everyone working on a file uses the same release.

### How to use

1. Download the asset for your system below.
2. Install or unpack it:
    - **Windows:** run the `*-installer.exe`, or unpack the `*.7z` and run `FreeCAD-CH.exe` in the unpacked folder. The build is unsigned: if SmartScreen blocks it, choose "More info", then "Run anyway".
    - **macOS (Apple silicon):** open the `*.dmg` and drag FreeCAD-CH to Applications. The build is only ad-hoc signed: after the first launch is blocked, allow it in System Settings > Privacy & Security ("Open Anyway"). This is needed once for each new build.
3. FreeCAD-CH installs next to official FreeCAD and keeps its own settings, add-ons and macros (`%APPDATA%\FreeCAD-CH`, `~/Library/Application Support/FreeCAD-CH`). Double-clicking a `.FCStd` file still opens official FreeCAD; use "Open with" for FreeCAD-CH, or tick "Open .FCStd files with FreeCAD-CH" in the Windows installer. About shows the release and the commit: name both in bug reports. It is under Help > About FreeCAD-CH on Windows, and under FreeCAD-CH > About FreeCAD-CH (the application menu) on macOS.
