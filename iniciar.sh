#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  Fábrica de Achadinhos — Início Rápido (Linux/Mac)
# ══════════════════════════════════════════════════════════════

echo "🎯 Fábrica de Achadinhos"
echo "════════════════════════════════"

cd "$(dirname "$0")"

# mata processos Streamlit anteriores
pkill -9 -f "streamlit run" 2>/dev/null
sleep 1

# cria venv se não existir
if [ ! -d ".venv" ]; then
    echo "📦 Criando ambiente virtual..."
    python3 -m venv .venv
fi

# ativa o venv
source .venv/bin/activate

# instala dependências
echo "📦 Verificando dependências..."
pip install -q -r requirements.txt 2>/dev/null

# autentica Google Sheets (se não tem token)
if [ ! -f ".google_token.json" ]; then
    echo ""
    echo "⚠️  Token do Google Sheets não encontrado."
    echo "   Execute: python auth.py"
    echo ""
fi

# inicia o app
echo ""
echo "🚀 Iniciando app em http://localhost:8501"
echo "   Pressione Ctrl+C para parar"
echo ""
streamlit run app.py --server.port 8501 --server.headless true
