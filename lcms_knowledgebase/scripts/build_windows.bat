@echo off
cd /d "%~dp0\.."
python -m pip install -r requirements-dev.txt
python -m PyInstaller packaging\lcms_knowledgebase.spec --noconfirm --clean
echo Portable folder: dist\LCMS_KnowledgeBase\LCMS_KnowledgeBase.exe
