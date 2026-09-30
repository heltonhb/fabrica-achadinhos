# 📌 Status do Projeto & Handover — Fábrica de Achadinhos

> **Data de atualização:** 30/09/2026  
> **Status:** 🟢 Estável / 92 testes passando (`pytest`) / Working tree limpa

---

## 1. Visão Geral da Sessão

Nesta sessão foi realizada uma avaliação crítica completa da arquitetura do projeto e a execução dos **Passos 1, 2, 3 e 4** do plano de evolução:

1. **Passo 1 — Robustez de Pipeline e Extração de Produtos:**
   - Commit: `5327d56` — `feat(pipeline): robustez na extração shopee, suporte a ganchos estruturados e novos testes`
   - Suporte a múltiplos formatos de URL da Shopee (`product`, `item`, `universal-link`, URLs curtas).
   - Extração via LD-JSON Schema.org com limpeza de termos de SEO e sufixos de imagem.
   - Normalização de ganchos estruturados (compatibilidade com dicionários e strings puras).
   - Atualização da base de produtos em `achados.csv` (`#01`, `#02`, `#03`).

2. **Passo 2 — Otimização e Blindagem do Webhook Instagram:**
   - Commit: `ccc71ff` — `feat(webhook): cache TTL para produtos e background tasks para resposta assíncrona`
   - Implementação de `BackgroundTasks` do FastAPI no endpoint `/webhook`: respostas à Meta em `< 50ms`, eliminando risco de timeout.
   - Cache em memória com TTL de 60s para leitura de produtos, suportando picos de tráfego sem sobrecarregar a Google Sheets API.
   - Timeouts explícitos (10s) nas requisições ao Facebook Graph API.
   - 3 novos testes unitários adicionados em `tests/test_webhook.py`.

3. **Passo 3 — Implementação da Vitrine Estática Própria (Vercel):**
   - Commit: `7aceb7b` — `feat(vitrine): gerador de vitrine estática para Vercel, testes e configuração de build`
   - Gerador estático em `scripts/gerar_vitrine.py`: design responsivo, mobile-first, tema `#FFD600`, busca instantânea em tempo real e filtros de nicho em JavaScript puro (zero dependências pesadas).
   - Filtro de produtos elegíveis (com nome e link afiliado) e assinatura de links afiliados com `rel="noopener sponsored"`.
   - Busca e cópia automática de imagens de `Midias/{slug}/` para `vitrine/assets/{slug}.jpg` (priorizando imagens `main`).
   - Configuração de deploy da Vercel em `vercel.json` (`buildCommand` com build automático de `vitrine/index.html`).
   - 8 novos testes em `tests/test_vitrine.py` cobrindo filtros, segurança XSS/escape, placeholders e build end-to-end.

4. **Passo 4 — Higienização do Código Legado e Otimização de Dependências:**
   - Arquivamento dos módulos de renderização local FFmpeg em `legacy/` (`render.py`, `voz.py`, `trilha.py`, `visual.py`, `teste_voz.py`, `fonts/`).
   - Remoção de pastas vazias (`SFX/`, `Trilhas/`).
   - Limpeza do `requirements.txt`: remoção de dependências pesadas desnecessárias no fluxo Google Vids (`edge-tts`, `numpy`, `scipy`, `Pillow`).
   - Atualização de chaves e variáveis do Streamlit no `app.py` (`sel_pipeline`, `estilo_pipeline`, `ultimo_pipeline`).
   - Redução drástica no tempo de instalação e build para deploys na Vercel e Streamlit Community Cloud.

---

## 2. Estado Atual do Repositório

- **Branch:** `main`
- **Ambiente de Testes:**
  ```bash
  .venv/bin/pytest -q
  # Resultado: 92 passed, 3 warnings in ~2.2s
  ```

---

## 3. Próximos Passos (Para Retomar)

### 🎯 Passo 5: Automação da Distribuição e Métricas
- Integração de agendamento automático via Meta Graph API (Instagram Reels).
- Sincronização periódica automática de métricas dos posts (alcance, comentários "QUERO", salvamentos).

---

## 4. Como Executar a Vitrine Localmente

```bash
# Gerar a vitrine (lê do Google Sheets / fallback CSV local)
.venv/bin/python scripts/gerar_vitrine.py

# Visualizar no navegador
xdg-open vitrine/index.html  # no Linux
# ou abrir o arquivo vitrine/index.html no navegador
```
