# 📌 Status do Projeto & Handover — Fábrica de Achadinhos

> **Data de atualização:** 30/09/2026  
> **Status:** 🟢 Estável / 84 testes passando (`pytest`) / Working tree limpa

---

## 1. Visão Geral da Sessão

Nesta sessão foi realizada uma avaliação crítica completa da arquitetura do projeto e a execução dos **Passos 1 e 2** do plano de evolução:

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
   - 3 novos testes unitários adicionados em `tests/test_webhook.py` (total de 84 testes, 100% de aprovação).

---

## 2. Estado Atual do Repositório

- **Branch:** `main` (à frente de `origin/main` por 2 commits: `5327d56` e `ccc71ff`).
- **Working Tree:** Limpa (`nothing to commit, working tree clean`).
- **Ambiente de Testes:**
  ```bash
  .venv/bin/pytest -q
  # Resultado: 84 passed, 3 warnings in ~1.9s
  ```

---

## 3. Próximos Passos (Para Retomar)

### 🎯 Passo 3: Implementação da Vitrine Estática Própria (Vercel)
Documentação de referência já pronta em: [`docs/PLANO_VITRINE.md`](PLANO_VITRINE.md).
- **Entregáveis previstos:**
  1. `scripts/gerar_vitrine.py`: script gerador de HTML responsivo, mobile-first, com tema `#FFD600`, busca rápida por nome/nicho e links com `rel="noopener sponsored"`.
  2. `tests/test_vitrine.py`: testes do gerador (filtros de produtos sem link, escape de HTML, placeholders de imagens).
  3. `vercel.json` e ajuste no `.gitignore` para build automático na Vercel.
  4. Script de cópia/seed de imagens de produtos de `Midias/{slug}/` para `vitrine/assets/`.

### 🎯 Passo 4: Limpeza do Código Legado de Renderização Local
- Mover ou arquivar arquivos legados de FFmpeg (`render.py`, `voz.py`, `trilha.py`, `visual.py`, `renders/`, `SFX/`, `Trilhas/`, `fonts/`).
- Limpar `requirements.txt` retirando dependências pesadas não mais necessárias no fluxo Google Vids (`edge-tts`, `numpy`, `scipy`, `Pillow`).

---

## 4. Como Retomar os Trabalhos

Quando voltar ao projeto:
1. Verifique o status do git e rode a suíte de testes:
   ```bash
   git status
   .venv/bin/pytest -q
   ```
2. Para subir os commits locais para o repositório remoto:
   ```bash
   git push origin main
   ```
3. Avance diretamente para a implementação da **Vitrine Estática (Passo 3)** seguindo [`docs/PLANO_VITRINE.md`](PLANO_VITRINE.md).
