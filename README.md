# 🎯 Fábrica de Achadinhos

Pipeline de conteúdo para vídeos curtos de produtos (Reels/TikTok).

## Pré-requisitos

- **Python 3.10+**

> FFmpeg **não é mais obrigatório**: o pipeline gera só texto (gancho, roteiro,
> pacote de post) e o vídeo é feito no Google Vids. Ele só é necessário se você
> for rodar o render local legado (`render.py`/`voz.py`):
>
> ```bash
> sudo apt install ffmpeg   # Debian/Ubuntu — brew install ffmpeg no macOS
> ```

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

# testes
pytest -q
```

## O que o app faz

1. **📋 Produtos** — gerencia produtos (status, links, métricas)
2. **➕ Novo Produto** — adiciona achadinhos
3. **🎬 Mídia** — baixa B-Roll de Shopee/AliExpress ou manual
4. **🚀 Pipeline** — gera gancho, roteiro e pacote de post (vídeo no Google Vids)
5. **📝 Legenda** — gera legendas para Instagram
6. **🤖 Gerar Prompt** — gera prompts via Gemini para Google Vids/NotebookLM

## Pipeline (CLI)

```bash
python pipeline.py                   # todos os produtos
python pipeline.py #01 #03           # só esses IDs
python pipeline.py #01 --forcar      # regenera mesmo se já existir
python pipeline.py #01 --estilo educativo
python pipeline.py #01 --sem-ganchos # usa o gancho da planilha
```

Estilos: `chocante` (padrão), `educativo`, `lifestyle`, `comparativo`.

Etapas: gancho → roteiro → `pacote_post.txt` (o vídeo é feito no Google Vids).

Saídas:
- `Produtos/#NN_Slug/` — gancho, roteiro, pacote de post

## Webhook Instagram (opcional)

Bot que responde comentários com o link afiliado:

```bash
python webhook_insta.py   # http://localhost:8000/webhook
```

Configure no `.env`:
- `INSTAGRAM_PAGE_ID`
- `INSTAGRAM_ACCESS_TOKEN`
- `META_VERIFY_TOKEN` (obrigatório — sem default seguro)
- `LINK_VITRINE_PADRAO` (fallback se o media_id não estiver na planilha)

A coluna `Media ID Instagram` da planilha mapeia post → link.

## Configuração

Copie `.env.example` para `.env` e preencha:
- `GEMINI_API_KEY` — API key do Google AI Studio
- `GOOGLE_SHEETS_ID` — ID da planilha Google Sheets
- `GOOGLE_SHEET_NAME` — nome da aba (padrão: `achados`)
- `OAUTH_CLIENT_JSON` — arquivo de credenciais OAuth2

## Arquivos principais

| Arquivo | Função |
|---------|--------|
| `app.py` | Interface Streamlit |
| `sheets.py` | Porta única de leitura/escrita (Sheets + CSV) |
| `pipeline.py` | Orquestrador (gancho → roteiro → pacote) |
| `prompts.py` | Geração de prompts via Gemini |
| `roteirista.py` | Ganchos e roteiro via Gemini |
| `voz.py` | Locução TTS — legado do render local |
| `render.py` | Composição ffmpeg — legado do render local |
| `legenda.py` | Geração de legendas Instagram |
| `midia.py` | Gerenciamento de mídia |
| `scraping.py` | Extração de mídia de plataformas |
| `webhook_insta.py` | Bot de comentários/DM |
| `auth.py` | Autenticação OAuth2 Google |

## Planos

| Doc | Status |
|-----|--------|
| [`docs/PLANO_VITRINE.md`](docs/PLANO_VITRINE.md) | Planejado — vitrine estática na Vercel (não implementado) |
