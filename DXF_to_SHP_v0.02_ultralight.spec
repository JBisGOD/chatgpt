# -*- mode: python ; coding: utf-8 -*-
"""
DXF_to_SHP_v0.02_ultralight 전용 spec
- GUI(Tkinter) 유지 + onefile + strip + UPX + 불필요 모듈 exclude
- 파이썬 표준 모듈 중 사용 안 하는 것들 과감히 제외
- ezdxf, pyshp만 포함


빌드: pyinstaller DXF_to_SHP_v0.02_ultralight.spec
"""


import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files


APP_NAME = "DXF_to_SHP_v0_02_ultralight"
MAIN_SCRIPT = "DXF_to_SHP_v0.02_ultralight.py"


hiddenimports = []
hiddenimports += collect_submodules("ezdxf")
hiddenimports += collect_submodules("shapefile") # pyshp


# datas: 일반적으로 Tkinter(tcl/tk) 리소스는 자동 수집됨. 별도 추가 불필요.
datas = []


# onedir이 아니라 onefile로 묶을 예정이라, binaries 별도 지정은 생략
binaries = []


# 사용하지 않는 표준/외부 모듈 제외 (필요시 추가/삭제)
excludes = [
# 대형 생태계/미사용 과학 패키지(혹시 들어오면 방지)
"matplotlib", "PIL", "Pillow", "scipy", "skimage", "numpy", "pandas",
# 네트워킹/웹 관련 표준 모듈(미사용)
"asyncio", "email", "http", "xml", "html", "urllib",
# 개발/문서/테스트 관련
"pydoc_data", "pydoc", "lib2to3", "distutils", "test", "tkinter.test", "turtledemo",
# 로깅 부속
"logging.config",
]


block_cipher = None


a = Analysis(
[MAIN_SCRIPT],
pathex=[os.getcwd()],
binaries=binaries,
datas=datas,
hiddenimports=hiddenimports,
hookspath=[],
hooksconfig={},
runtime_hooks=[],
excludes=excludes,
noarchive=False,
)


pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)


exe = EXE(
pyz,
a.scripts,
a.binaries,
a.zipfiles,
a.datas,
name=APP_NAME,
console=False, # GUI
strip=True, # 심볼 제거
upx=True, # UPX 적용(설치 필요)
upx_exclude=[],
disable_windowed_traceback=True,
)