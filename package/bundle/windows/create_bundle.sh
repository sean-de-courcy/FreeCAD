#!/bin/bash

set -e
set -x

conda_env="$(pwd | sed 's#\\#/#g')/../../../.pixi/envs/default"

# FreeCAD-CH: the package's name and executables come from fork.json. The executables are
# renamed here only (build trees keep FreeCAD.exe), so that official FreeCAD's FreeCAD.exe
# and FreeCAD-CH's can run, install and uninstall side by side.
app_name=$(python -c "import json; print(json.load(open('../../../fork.json'))['name'])")
app_exe="${app_name}.exe"
app_cmd_exe="${app_name}Cmd.exe"

copy_dir="FreeCAD_Windows"
mkdir -p ${copy_dir}/bin

# Copy Conda's Python and (U)CRT to FreeCAD/bin
cp -a ${conda_env}/DLLs ${copy_dir}/bin/DLLs
cp -a ${conda_env}/Lib ${copy_dir}/bin/Lib
cp -a ${conda_env}/Scripts ${copy_dir}/bin/Scripts
cp -a ${conda_env}/python*.* ${copy_dir}/bin
cp -a ${conda_env}/msvc*.* ${copy_dir}/bin
cp -a ${conda_env}/ucrt*.* ${copy_dir}/bin
# Copy meaningful executables
cp -a ${conda_env}/Library/bin/ccx.exe ${copy_dir}/bin
cp -a ${conda_env}/Library/bin/gmsh.exe ${copy_dir}/bin
cp -a ${conda_env}/Library/bin/dot.exe ${copy_dir}/bin
cp -a ${conda_env}/Library/bin/unflatten.exe ${copy_dir}/bin
cp -a ${conda_env}/Library/mingw-w64/bin/* ${copy_dir}/bin
# copy resources -- perhaps needs reduction
cp -a ${conda_env}/Library/share ${copy_dir}/share
# get all the dependency .dlls
cp -a ${conda_env}/Library/bin/*.dll ${copy_dir}/bin
# Copy FreeCAD build
cp -a ${conda_env}/Library/bin/freecad* ${copy_dir}/bin
cp -a ${conda_env}/Library/bin/FreeCAD* ${copy_dir}/bin
mv ${copy_dir}/bin/freecad.exe "${copy_dir}/bin/${app_exe}"
mv ${copy_dir}/bin/freecadcmd.exe "${copy_dir}/bin/${app_cmd_exe}"
cp -a ${conda_env}/Library/data ${copy_dir}/data
cp -a ${conda_env}/Library/Ext ${copy_dir}/Ext
cp -a ${conda_env}/Library/lib ${copy_dir}/lib
cp -a ${conda_env}/Library/Mod ${copy_dir}/Mod
mkdir -p ${copy_dir}/doc
cp -a ${conda_env}/Library/doc/{ThirdPartyLibraries.html,LICENSE.html} ${copy_dir}/doc

# Generate graphviz config
${copy_dir}/bin/dot.exe -c

# delete unnecessary stuff
find ${copy_dir} -name \*.a -delete
find ${copy_dir} -name \*.lib -delete
find ${copy_dir} -name \*arm\*.exe -delete # arm binaries that fail to extract unless using latest 7zip

rm -rf ${copy_dir}/bin/Lib/site-packages/conda
rm -rf ${copy_dir}/bin/Lib/site-packages/pandas/tests
rm -rf ${copy_dir}/bin/Lib/site-packages/pre_commit
rm -rf ${copy_dir}/bin/Lib/site-packages/pycparser
rm -rf ${copy_dir}/bin/Lib/site-packages/pyright*
rm -rf ${copy_dir}/bin/libclang-*.dll
rm -rf ${copy_dir}/lib/cmake
rm -rf ${copy_dir}/lib/objects-Release
rm -rf ${copy_dir}/lib/qt6/bin
rm -rf ${copy_dir}/share/cmake
rm -rf ${copy_dir}/share/cmake-*
rm -rf ${copy_dir}/share/man

# Turn off the echo before we start actually calling "echo"
set +x

echo '[Paths]' >> ${copy_dir}/bin/qt6.conf
echo 'Prefix = ../lib/qt6' >> ${copy_dir}/bin/qt6.conf

version_name="${app_name}_${BUILD_TAG}-Windows-$(uname -m)"

echo -e "################"
echo -e "version_name:  ${version_name}"
echo -e "################"

# FreeCAD-CH: the shipped packages are the workspace's default environment, not this folder's tools
pixi list --frozen --manifest-path ../../../pixi.toml -e default > ${copy_dir}/packages.txt
sed -i '1s/.*/\nLIST OF PACKAGES:/' ${copy_dir}/packages.txt

mv ${copy_dir} ${version_name}

# FreeCAD-CH: the checks below import modules from the bundle, and FreeCADCmd's interpreter ignores
# PYTHONDONTWRITEBYTECODE (an isolated PyConfig), so they write __pycache__ into it. The stamp marks
# what they write; the bundle's own files keep their older times (cp -a). Removed after the gate.
pyc_stamp="$(mktemp)"

# FreeCAD-CH: refuse a bundle that doesn't run the tested environment, pixi.lock's (ops#388).
# Before signing, so a refused bundle is never signed (ops#398), as on macOS.
python ../../scripts/check_release_env.py --lock ../../../pixi.lock --platform "${TARGET_PLATFORM:-win-64}" --freecadcmd "${version_name}/bin/${app_cmd_exe}" ${GITHUB_STEP_SUMMARY:+--summary "$GITHUB_STEP_SUMMARY"}

# FreeCAD-CH: the packaged build reopens the compat corpus itself (WORKFLOW section 6, "Compat
# steps": the release build differs from PR builds, ops#294), so neither a dry run nor a release
# run ships a package the gate refuses. A fresh absolute settings folder, never the runner's.
gate_home="$(mktemp -d)"
gate_status=0
FREECAD_USER_HOME="$(cygpath -w "${gate_home}")" \
    "${version_name}/bin/${app_cmd_exe}" -t PartDesignTests.Compat.TestCompatCorpus \
    > compat-gate.log 2>&1 || gate_status=$?
cat compat-gate.log
rm -rf "${gate_home}" || true    # a scanner's lock on the scratch folder must not fail a passed gate
if [[ ${gate_status} -ne 0 ]] || ! grep -q '^OK' compat-gate.log || grep -q '^FAILED' compat-gate.log; then
  echo "TestCompatCorpus failed on the packaged build (exit ${gate_status}); refusing to package it."
  exit 1
fi
# the bytecode the release check and the gate wrote goes; the package ships only what was copied
find "${version_name}" -name '*.pyc' -newer "${pyc_stamp}" -delete
find "${version_name}" -type d -name __pycache__ -empty -delete
rm -f "${pyc_stamp}"


# Sign the EXE, DLL, and PYD files (if we can access the Azure account for signing):
set -euo pipefail
SIGN_DIR="${version_name}"


if [[ "${WINDOWS_SIGN_RELEASE:-0}" == "1" ]]; then
  TENANT="$(az account show --query tenantId -o tsv)"
  export AZURE_IDENTITY_DISABLE_WORKLOAD_IDENTITY=true
  export AZURE_IDENTITY_DISABLE_MANAGED_IDENTITY=true
  unset AZURE_IDENTITY_LOGGING_ENABLED

  if az account get-access-token \
       --tenant "$TENANT" \
       --scope "https://codesigning.azure.net/.default" \
       >/dev/null 2>&1;
  then
    echo "Azure Artifact Signing access confirmed. Beginning signing process..."

    shopt -s nullglob

    FILES=(
      "$SIGN_DIR"/bin/*.exe
      "$SIGN_DIR"/bin/*.dll
      "$SIGN_DIR"/bin/*.pyd
    )

    count=0
    total=${#FILES[@]}
    echo "Signing $total files"
    for f in "${FILES[@]}"; do
      ((count+=1))
      echo "Signing [$count/$total]: $f"
      sign code artifact-signing \
        --artifact-signing-endpoint "${WINDOWS_AZURE_ENDPOINT}" \
        --artifact-signing-certificate-profile "${WINDOWS_AZURE_CERTIFICATE_PROFILE}" \
        --artifact-signing-account "${WINDOWS_AZURE_SIGNING_ACCOUNT}" \
        --timestamp-url https://timestamp.acs.microsoft.com \
        --timestamp-digest sha256 \
        "$f" >/dev/null 2>&1

      # Output was redirected to /dev/null because Azure authentication is absurdly noisy, with constant misleading
      # "failure" messages about Managed Identity authentication failing. We don't use, or want to use, that
      # authentication, and the fact that it fails is not a problem as long as the real authentication succeeds.
    done

    # Manually check the important one!
    signtool verify -pa "$SIGN_DIR/bin/${app_exe}"

    echo "Signing completed."
  else
    echo "Signing requested, but no Azure Artifact Signing available -- skipping signing."
  fi
else
  echo "Not logged into Azure -- skipping signing."
fi

echo "Running FreeCAD command-line smoke test..."
if ! "$SIGN_DIR/bin/${app_cmd_exe}" --safe-mode --version; then
  echo "FreeCAD command-line smoke test failed; the Windows bundle cannot start."
  exit 1
fi

echo "Running FreeCAD bundled Pivy smoke test..."
if ! "$SIGN_DIR/bin/${app_cmd_exe}" --safe-mode --console "import pivy; from pivy import coin; print(pivy.__file__); print(coin.SoDB.getVersion())"; then
  echo "FreeCAD bundled Pivy smoke test failed; the Windows bundle cannot import the bundled Coin/Pivy runtime."
  exit 1
fi

7z a -t7z -mx9 -mmt=${NUMBER_OF_PROCESSORS} ${version_name}.7z ${version_name} -bb
# create hash
sha256sum ${version_name}.7z > ${version_name}.7z-SHA256.txt

if [ "${MAKE_INSTALLER}" == "true" ]; then
    FILES_FREECAD="$(cygpath -w $(pwd))\\${version_name}"
    nsis_cmd="${CONDA_PREFIX}/NSIS/makensis.exe"
    "${nsis_cmd}" -V4 \
        -D"ExeFile=${version_name}-installer.exe" \
        -D"FILES_FREECAD=${FILES_FREECAD}" \
        -D"FILES_FREECADCMD=${FILES_FREECAD}\\bin\\${app_cmd_exe}" \
        -X'SetCompressor /FINAL lzma' \
        ../../WindowsInstaller/FreeCAD-installer.nsi
    mv ../../WindowsInstaller/${version_name}-installer.exe .
    echo "Created installer ${version_name}-installer.exe"
    # See if we can sign the installer exe as well:
    if [[ "${WINDOWS_SIGN_RELEASE:-0}" == "1" ]] && \
       az account get-access-token \
           --tenant "$TENANT" \
           --scope "https://codesigning.azure.net/.default" \
           >/dev/null 2>&1;
    then
      echo "Signing the installer..."
      sign code artifact-signing \
          --artifact-signing-endpoint "${WINDOWS_AZURE_ENDPOINT}" \
          --artifact-signing-certificate-profile "${WINDOWS_AZURE_CERTIFICATE_PROFILE}" \
          --artifact-signing-account "${WINDOWS_AZURE_SIGNING_ACCOUNT}" \
          --timestamp-url https://timestamp.acs.microsoft.com \
          --timestamp-digest sha256 \
          ${version_name}-installer.exe >/dev/null 2>&1 \
          || { echo "Signing the installer failed!"; exit 1; }
    else
      echo "No code signing available, leaving the installer unsigned"
    fi
    sha256sum ${version_name}-installer.exe > ${version_name}-installer.exe-SHA256.txt
fi

if [ "${UPLOAD_RELEASE}" == "true" ]; then
    echo "Uploading the release..."
    gh release upload --clobber ${BUILD_TAG} "${version_name}.7z" "${version_name}.7z-SHA256.txt"
    if [ "${MAKE_INSTALLER}" == "true" ]; then
        gh release upload --clobber ${BUILD_TAG} "${version_name}-installer.exe" "${version_name}-installer.exe-SHA256.txt"
    fi
    echo "Done uploading"
fi
