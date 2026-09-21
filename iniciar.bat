@echo off
REM ══════════════════════════════════════════════════════════════
REM  Fábrica de Achadinhos — Início Rápido (Windows)
REM ══════════════════════════════════════════════════════════════

echo 🎯 Fábrica de Achadinhos
echo ═════════════════════════════════

cd /d "%~dp0"

REM mata processos Streamlit anteriores
taskkill /F /IM python.exe /FI "WINDOWTITLE eq streamlit*" 2>nul
taskkill /F /IM streamlit.exe 2>nul
for /f "tokens=2" %%a in ('tasklist ^| findstr /i "python"') do taskkill /F /PID %%a 2>nul
timeout /t 2 /nobreak >nul

REM cria venv se não existir
if not exist ".venv" (
    echo 📦 Criando ambiente virtual...
    python -m venv .venv
)

REM ativa o venv
call .venv\Scripts\activate.bat

REM instala dependências
echo 📦 Verificando dependências...
pip install -q -r requirements.txt 2>nul

REM autentica Google Sheets (se não tem token)
if not exist ".google_token.json" (
    echo.
    echo ⚠️  Token do Google Sheets não encontrado.
    echo    Execute: python auth.py
    echo.
)

REM inicia o app
echo.
echo 🚀 Iniciando app em http://localhost:8501
echo    Pressione Ctrl+C para parar
echo.
streamlit run app.py --server.port 8501 --server.headless true

pause
