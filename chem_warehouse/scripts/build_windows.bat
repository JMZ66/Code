@echo off
REM Build offline Windows EXE (run on Windows 10/11 with Python 3.10+)
cd /d %~dp0\..
python -m pip install -r requirements.txt
python -m pip install pyinstaller
set PYTHONPATH=src
pyinstaller packaging\chem_warehouse.spec --noconfirm --clean
echo.
echo Output: dist\ChemWarehouse.exe
echo Database will be created under %%USERPROFILE%%\.chem_warehouse\
pause
