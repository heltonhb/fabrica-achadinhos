# 🎯 Fábrica de Achadinhos

Pipeline de conteúdo para vídeos curtos de produtos (Reels/TikTok).

## Início Rápido

### Linux/Mac
```bash
chmod +x iniciar.sh
./iniciar.sh
```

### Windows
```
duplo clique em iniciar.bat
```

### Manual
```bash
# criar ambiente virtual
python3 -m venv .venv
source .venv/bin/activate   # Linux/Mac
.venv\Scripts\activate      # Windows

# instalar dependências
pip install -r requirements.txt

# autenticar Google Sheets (primeira vez)
python auth.py

# rodar o app
streamlit run app.py
```

## O que o app faz

1. **📋 Produtos** — gerencia produtos no Google Sheets
2. **➕ Novo Produto** — adiciona achadinhos
3. **🎬 Mídia** — baixa B-Roll de Shopee/AliExpress ou manual
4. **📝 Legenda** — gera legendas para Instagram
5. **🤖 Gerar Prompt** — gera prompts via Gemini para Google Vids/NotebookLM

## Configuração

Copie `.env.example` para `.env` e preencha:
- `GEMINI_API_KEY` — API key do Google AI Studio
- `GOOGLE_SHEETS_ID` — ID da planilha Google Sheets
- `OAUTH_CLIENT_JSON` — arquivo de credenciais OAuth2

## Arquivos principais

| Arquivo | Função |
|---------|--------|
| `app.py` | Interface Streamlit |
| `sheets.py` | Integração Google Sheets |
| `prompts.py` | Geração de prompts via Gemini |
| `legenda.py` | Geração de legendas Instagram |
| `midia.py` | Gerenciamento de mídia |
| `scraping.py` | Extração de mídia de plataformas |
| `auth.py` | Autenticação OAuth2 Google |
