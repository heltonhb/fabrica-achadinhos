#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  Fábrica de Achadinhos — Modern Stitch UI (FastAPI + Tailwind)
# ══════════════════════════════════════════════════════════════

echo "🎯 Fábrica de Achadinhos — Stitch Studio UI"
echo "══════════════════════════════════════════"

cd "$(dirname "$0")"

# Encerra instâncias anteriores na porta 8000 se houver
fuser -k 8000/tcp 2>/dev/null || pkill -9 -f "python server.py" 2>/dev/null || true
sleep 1

# ativa o venv
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo ""
echo "🚀 Iniciando interface moderna em http://localhost:8000"
echo "   Pressione Ctrl+C para parar"
echo ""
python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
