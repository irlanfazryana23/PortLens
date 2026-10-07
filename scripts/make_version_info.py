"""
Render the Windows version resource (Properties > Details) for the PortLens exe.

Used by PortLens.spec during the build, and unit tested. The output is the text
format PyInstaller's `version=` option expects.
"""

import re

APP_NAME = "PortLens"
DESCRIPTION = "PortLens - printer port and status detector"
COPYRIGHT = "Copyright (c) 2026 PortLens contributors. MIT License."


def version_tuple(version):
    """'1.2.3' -> (1, 2, 3, 0). Raises ValueError for anything else."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version or ""):
        raise ValueError(f"VERSION must look like 1.2.3, got {version!r}")
    major, minor, patch = (int(part) for part in version.split("."))
    return (major, minor, patch, 0)


def render(version, exe_name):
    numbers = version_tuple(version)
    dotted = ".".join(str(n) for n in numbers)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numbers},
    prodvers={numbers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', ''),
         StringStruct('FileDescription', '{DESCRIPTION}'),
         StringStruct('FileVersion', '{dotted}'),
         StringStruct('InternalName', '{APP_NAME}'),
         StringStruct('LegalCopyright', '{COPYRIGHT}'),
         StringStruct('OriginalFilename', '{exe_name}'),
         StringStruct('ProductName', '{APP_NAME}'),
         StringStruct('ProductVersion', '{dotted}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
