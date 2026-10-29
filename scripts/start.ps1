param([string]$FreeCADCmd,[string]$Blender,[string]$DataDirectory,[int]$Port=8765)
$ErrorActionPreference='Stop'
if($FreeCADCmd){$env:FREECAD_CMD=$FreeCADCmd}
if($Blender){$env:BLENDER_EXE=$Blender}
if($DataDirectory){$env:OPENARCH_DATA_DIR=$DataDirectory}
# Run after activating the virtual environment and installing the package.
python -m openarch --port $Port
