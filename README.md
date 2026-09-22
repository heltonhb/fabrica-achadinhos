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
- `GOOGLE_SHEET_NAME` — nome da aba (padrão: `Produtos`)
- `GOOGLE_TOKEN_JSON` — conteúdo do token OAuth2 (opcional; localmente o
  arquivo `.google_token.json` gerado por `python auth.py` basta)

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


## Na nuvem (Streamlit Community Cloud — grátis)

O app não precisa mais de ffmpeg (o render é no Google Vids), então roda em
qualquer host Streamlit:

1. `git push` no GitHub (repo `heltonhb/fabrica-achadinhos`).
2. [share.streamlit.io](https://share.streamlit.io) → *Sign in with GitHub* →
   *Deploy an app* → repositório `fabrica-achadinhos`, branch `main`, arquivo
   `app.py`.
3. *Settings → Secrets* (TOML):

   ```toml
   GEMINI_API_KEY = "sua-chave"
   GOOGLE_SHEETS_ID = "1gckCWB0OzPQRgAMaMGj4J9wW48Ux8EDRcRNcRmR2Mq4"
   GOOGLE_SHEET_NAME = "Produtos"
   GOOGLE_TOKEN_JSON = '''{"token": "...", "refresh_token": "...", ...}'''
   ```

   O `GOOGLE_TOKEN_JSON` é o conteúdo do `.google_token.json` gerado por
   `python auth.py`. Segredos são resolvidos na ordem: variável de ambiente →
   `.env` → `st.secrets`.

Observações:

- Disco efêmero: `Produtos/`, `Midias/` e os caches do pipeline são recriados
  a cada redeploy — a planilha é a fonte de verdade e os arquivos regeneram.
- Sem `GOOGLE_TOKEN_JSON` o app sobe em modo leitura (a leitura da planilha é
  pública via export CSV).
- `webhook_insta.py` (porta 8000) é outro serviço: publicação automática no
  Instagram exige um host separado com URL pública (VPS/Render).
