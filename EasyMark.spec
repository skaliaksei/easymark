# -*- mode: python ; coding: utf-8 -*-
#
# Спецификация сборки EasyMark в PyInstaller.
# Запускать из корня проекта (там же, где main.py):
#     pyinstaller EasyMark.spec
#
# Важно: сюда сознательно НЕ включены через datas=[...] папки img/ и
# workfolder/. Код проекта читает их как "./img/..." и "./workfolder/..."
# относительно текущей рабочей директории (CWD), а не как ресурсы,
# запечённые внутрь exe. Поэтому после сборки эти папки просто
# копируются рядом с готовым exe отдельным шагом (см. build.bat) —
# так поведение в exe остаётся идентичным поведению при запуске
# "python main.py" из этой же папки.

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EasyMark',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,       # GUI-приложение: без чёрного окна консоли.
                          # Поставь True на время отладки сборки, если
                          # нужно видеть print()/traceback — потом верни False.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='img/EM.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EasyMark',
)
