# Plano: Vitrine estática + Vercel

> **Status:** planejado — **não implementado**.  
> Implementar depois; este documento é a referência do acordado.

## Objetivo

Página pública com cards dos produtos e CTA para a Shopee (link afiliado), para usar na bio do Instagram / no lugar do Beacons atual.

## Decisões

| Item | Escolha |
|------|---------|
| Hospedagem | **Vercel** (site estático + build) |
| Produtos | **Todos** da planilha, com filtro abaixo |
| Imagens | **Sim** — pasta versionada em `vitrine/assets/` |
| Build do HTML | Gerado **no build da Vercel** (não versionar `index.html`) |

### Regras de exibição

- Expor produto se tiver **nome** e **`Link Afiliado Shopee`** preenchidos.
- Pular: sem nome, sem link de afiliado ou ID vazio.
- Sem imagem `{slug}.jpg` → placeholder CSS (sem PNG; `*.png` está no `.gitignore`).

## Arquitetura

```
achados.csv  ──►  scripts/gerar_vitrine.py  ──►  vitrine/  ──►  Vercel
                      ▲                              │
              vitrine/assets/{slug}.jpg              index.html + assets
```

- **Fonte no build:** `achados.csv` no repositório.  
  `sheets.ler_produtos` tenta a Sheets pública e, se falhar, usa o CSV local.
- **Imagens no CI:** só o que estiver em `vitrine/assets/` (git).  
  `Midias/` continua fora do git. Na geração **local**, o script pode copiar o melhor jpeg de `Midias/{slug}/` para `vitrine/assets/{slug}.jpg` (priorizar `shopee_main_*.jpeg`); essas cópias são commitadas.

## Estrutura (planejada)

```
scripts/
  gerar_vitrine.py      # gera o HTML
vitrine/
  assets/               # {slug}.jpg / {slug}.jpeg versionados
  .gitkeep
  index.html            # artefato de build (não versionar na opção A)
vercel.json
tests/
  test_vitrine.py
docs/PLANO_VITRINE.md   # este arquivo
```

## Entregáveis na implementação

1. **`scripts/gerar_vitrine.py`**
   - Ler produtos pela porta única (`sheets.ler_produtos` / fallback CSV).
   - Filtrar por nome + link afiliado.
   - Imagem: `vitrine/assets/{slug}.jpg` → se faltar e existir em `Midias/{slug}/`, copiar.
   - Card: nome, preço, nicho, gancho (1 linha), CTA **“Ver na Shopee”** se houver link.
   - `target="_blank" rel="noopener sponsored"`.
   - Escape HTML de nome/gancho/nicho.
   - CSS embutido, mobile-first, tema com amarelo `#FFD600` (mesmo destaque do app).
   - Log: N cards, N com imagem, N com CTA.

2. **`vercel.json`** (referência)

   ```json
   {
     "buildCommand": "pip install -r requirements.txt && python scripts/gerar_vitrine.py",
     "outputDirectory": "vitrine",
     "framework": null
   }
   ```

   Ajustar na primeira depuração do deploy se o projeto Python da Vercel pedir outro formato.

3. **`tests/test_vitrine.py`**
   - Filtra sem link / sem nome.
   - HTML contém `sponsored`, nome escapado, caminho de imagem.
   - Placeholder quando não há `{slug}.jpg`.

4. **`.gitignore`**
   - Não ignorar `vitrine/assets/*.jpg` / `*.jpeg`.
   - Ignorar `vitrine/index.html` (gerado no build).

5. **Seed de imagens**
   - Copiar de `Midias/{slug}/` → `vitrine/assets/{slug}.jpg` e commitar.
   - `.gitkeep` em `vitrine/assets/`.

6. **README**
   - Gerar local: `python scripts/gerar_vitrine.py`
   - Conectar repositório à Vercel
   - Convenção de imagem
   - URL da Vercel → `LINK_VITRINE_PADRAO` / coluna `Link Vitrine (Bio)`

## Ordem de execução sugerida

1. Script de geração + template HTML  
2. Testes  
3. `vercel.json` + ajuste `.gitignore`  
4. Seed de imagens a partir de `Midias/`  
5. README  
6. Deploy (conectar repo na Vercel; validar build Python)

## Fora do escopo

- Carrinho, pagamento, checkout, backend, CMS  
- Sync automático de toda a pasta `Midias/`  
- Domínio próprio (usar `*.vercel.app` no início)

## Riscos / atenção

- Planilha hoje quase vazia (`#A` sem link cai pelo filtro; `#07` com link entra).
- Build Vercel instala `requirements.txt` inteiro (aceito; alternativa futura: gerador só-stdlib).
- Assinar links com `rel="sponsored"` por boas práticas de afiliado.

## Referências no código

- Colunas / `Produto`: `config.py` (`COLUNAS`, `link_afiliado`, `slug`)
- Porta única de leitura: `sheets.ler_produtos`
- Campo de vitrine na planilha: `Link Vitrine (Bio)` (hoje: URL externa Beacons etc.)
- Fallback do bot: `LINK_VITRINE_PADRAO` em `webhook_insta.py`
