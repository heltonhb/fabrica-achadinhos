"""
scripts/gerar_vitrine.py — Gerador de site estático da vitrine de achadinhos.

Lê produtos da porta única (sheets.ler_produtos com fallback CSV local),
filtra produtos elegíveis (com nome e link afiliado), copia imagens disponíveis
de Midias/ para vitrine/assets/ e gera vitrine/index.html (para deploy na Vercel).
"""

from __future__ import annotations

import html
import logging
import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Produto

# Adiciona o diretório raiz ao path para importar sheets/config
import sys
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import MIDIAS_DIR, Produto
from sheets import ler_produtos

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Vitrine")

VITRINE_DIR = BASE_DIR / "vitrine"
ASSETS_DIR = VITRINE_DIR / "assets"
INDEX_HTML = VITRINE_DIR / "index.html"


def filtrar_produtos_vitrine(produtos: list[Produto]) -> list[Produto]:
    """Filtra produtos válidos para exibição na vitrine pública.

    Regras:
    - ID preenchido
    - Nome do produto preenchido
    - Link Afiliado Shopee preenchido
    """
    validos = []
    for p in produtos:
        pid = (p.id or "").strip()
        nome = (p.nome or "").strip()
        link = (p.link_afiliado or "").strip()
        if pid and nome and link:
            validos.append(p)
    return validos


def encontrar_ou_copiar_imagem(
    p: Produto,
    vitrine_dir: Path | None = None,
    midias_dir: Path | None = None,
) -> str | None:
    """Retorna o caminho relativo da imagem do produto para a vitrine.

    1. Checa se já existe vitrine/assets/{slug}.jpg (ou .jpeg, .png, .webp).
    2. Se não existir, tenta encontrar na pasta de mídias brutas e copiar para assets/.
    3. Retorna 'assets/{arquivo}' ou None se não houver imagem.
    """
    v_dir = vitrine_dir or VITRINE_DIR
    m_dir = midias_dir or MIDIAS_DIR
    assets_path = v_dir / "assets"
    assets_path.mkdir(parents=True, exist_ok=True)

    slug = p.slug

    # 1. Checa se já existe no vitrine/assets
    for ext in (".jpg", ".jpeg", ".webp", ".png"):
        candidato = assets_path / f"{slug}{ext}"
        if candidato.exists() and candidato.is_file():
            return f"assets/{candidato.name}"

    # 2. Busca na pasta de mídias
    pastas_candidatas = [m_dir / slug]
    # Fallback: pasta com mesmo prefixo de ID (ex: 03_)
    num_id = p.id.replace("#", "").strip()
    if m_dir.exists():
        for sub in m_dir.iterdir():
            if sub.is_dir() and sub.name.startswith(f"{num_id}_") and sub not in pastas_candidatas:
                pastas_candidatas.append(sub)

    for pasta in pastas_candidatas:
        if not pasta.exists() or not pasta.is_dir():
            continue

        exts = {".jpg", ".jpeg", ".png", ".webp"}
        arquivos = [f for f in pasta.iterdir() if f.is_file() and f.suffix.lower() in exts]
        if not arquivos:
            continue

        # Priorização: shopee_main_*, depois shopee_variant_*, depois qualquer imagem
        def prioridade(f: Path) -> int:
            nome_lower = f.name.lower()
            if "main" in nome_lower:
                return 0
            if "variant" in nome_lower:
                return 1
            return 2

        arquivos.sort(key=prioridade)
        melhor = arquivos[0]

        # Copia para vitrine/assets/{slug}.jpg
        destino = assets_path / f"{slug}.jpg"
        try:
            shutil.copy2(melhor, destino)
            logger.info("Imagem copiada de %s para %s", melhor, destino)
            return f"assets/{destino.name}"
        except Exception as exc:
            logger.warning("Falha ao copiar imagem %s: %s", melhor, exc)

    return None


def formatar_preco(preco_str: str) -> str:
    """Normaliza o preço para exibição amigável (ex: 'R$ 35,99')."""
    if not preco_str:
        return ""
    p = preco_str.strip().replace("R$", "").strip()
    return f"R$ {p}"


def gerar_html_vitrine(produtos: list[Produto], imagens_map: dict[str, str | None]) -> str:
    """Gera o HTML completo, responsivo, mobile-first com busca e filtro."""
    # Coleta nichos únicos para os filtros
    nichos_set = set()
    for p in produtos:
        n = (p.nicho or "").strip()
        if n:
            nichos_set.add(n.title())
    nichos = sorted(nichos_set)

    # Renderiza os cards
    cards_html = []
    for p in produtos:
        pid = html.escape(p.id.strip())
        nome = html.escape(p.nome.strip())
        nicho = html.escape((p.nicho or "Achadinho").strip().title())
        gancho = html.escape((p.gancho or "").strip())
        preco_fmt = html.escape(formatar_preco(p.preco))
        link = html.escape(p.link_afiliado.strip())
        img_rel = imagens_map.get(p.id)

        if img_rel:
            img_html = f'<img src="{img_rel}" alt="{nome}" class="card-img" loading="lazy" />'
        else:
            img_html = f'''
            <div class="card-img-placeholder">
                <span class="placeholder-icon">🛍️</span>
                <span class="placeholder-id">{pid}</span>
            </div>'''

        preco_html = f'<span class="card-price">{preco_fmt}</span>' if preco_fmt else ''
        gancho_html = f'<p class="card-hook">{gancho}</p>' if gancho else ''

        card = f'''
        <article class="card" data-nicho="{nicho.lower()}" data-nome="{nome.lower()}">
            <div class="card-media">
                {img_html}
                <span class="card-badge">{nicho}</span>
            </div>
            <div class="card-body">
                <div class="card-header-row">
                    <span class="card-id">{pid}</span>
                    {preco_html}
                </div>
                <h2 class="card-title">{nome}</h2>
                {gancho_html}
                <a href="{link}" target="_blank" rel="noopener sponsored" class="btn-cta">
                    Ver na Shopee
                    <svg class="cta-icon" viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
                        <path fill-rule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clip-rule="evenodd" />
                    </svg>
                </a>
            </div>
        </article>'''
        cards_html.append(card)

    cards_str = "\n".join(cards_html)

    # Botões de filtro por nicho
    filtros_html = ['<button class="filter-btn active" data-filter="all">Todos</button>']
    for n in nichos:
        filtros_html.append(f'<button class="filter-btn" data-filter="{n.lower()}">{n}</button>')
    filtros_str = "\n".join(filtros_html)

    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fábrica de Achadinhos — Vitrine de Ofertas</title>
    <meta name="description" content="Os melhores achadinhos e produtos testados da Shopee com os menores preços.">
    <meta property="og:title" content="Fábrica de Achadinhos — Vitrine Oficial">
    <meta property="og:description" content="Confira nossa seleção exclusiva de achadinhos Shopee com links diretos!">
    <meta property="og:type" content="website">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --primary: #FFD600;
            --primary-hover: #E5C000;
            --primary-glow: rgba(255, 214, 0, 0.25);
            --bg-body: #0B0E14;
            --bg-surface: #151922;
            --bg-card: #1A1F2C;
            --bg-card-hover: #222838;
            --text-main: #FFFFFF;
            --text-muted: #94A3B8;
            --text-dark: #0B0E14;
            --border: rgba(255, 255, 255, 0.08);
            --border-hover: rgba(255, 214, 0, 0.35);
            --shadow-card: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5);
            --radius-md: 14px;
            --radius-lg: 20px;
            --transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: var(--bg-body);
            color: var(--text-main);
            min-height: 100vh;
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }}

        /* Header */
        header {{
            background: linear-gradient(180deg, rgba(21, 25, 34, 0.95) 0%, rgba(11, 14, 20, 0.8) 100%);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--border);
            padding: 2.5rem 1rem 2rem;
            text-align: center;
            position: relative;
            overflow: hidden;
        }}

        .brand-badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: var(--primary-glow);
            color: var(--primary);
            border: 1px solid rgba(255, 214, 0, 0.3);
            padding: 0.35rem 0.9rem;
            border-radius: 9999px;
            font-size: 0.82rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin-bottom: 0.85rem;
        }}

        header h1 {{
            font-size: 2.2rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            margin-bottom: 0.4rem;
            background: linear-gradient(135deg, #FFFFFF 60%, var(--primary) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        header p {{
            color: var(--text-muted);
            font-size: 1rem;
            max-width: 540px;
            margin: 0 auto;
        }}

        /* Container & Controls */
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem 1.25rem 4rem;
        }}

        .controls {{
            display: flex;
            flex-direction: column;
            gap: 1.2rem;
            margin-bottom: 2.5rem;
        }}

        .search-box {{
            position: relative;
            max-width: 580px;
            width: 100%;
            margin: 0 auto;
        }}

        .search-box input {{
            width: 100%;
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: 9999px;
            padding: 0.9rem 1.2rem 0.9rem 3rem;
            color: var(--text-main);
            font-size: 0.95rem;
            font-family: inherit;
            outline: none;
            transition: var(--transition);
        }}

        .search-box input:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 0 3px var(--primary-glow);
        }}

        .search-box svg {{
            position: absolute;
            left: 1.15rem;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
            pointer-events: none;
        }}

        .filters {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            justify-content: center;
        }}

        .filter-btn {{
            background: var(--bg-surface);
            color: var(--text-muted);
            border: 1px solid var(--border);
            padding: 0.45rem 1rem;
            border-radius: 9999px;
            font-size: 0.85rem;
            font-weight: 600;
            font-family: inherit;
            cursor: pointer;
            transition: var(--transition);
        }}

        .filter-btn:hover {{
            color: var(--text-main);
            border-color: rgba(255, 255, 255, 0.2);
        }}

        .filter-btn.active {{
            background: var(--primary);
            color: var(--text-dark);
            border-color: var(--primary);
            box-shadow: 0 4px 12px var(--primary-glow);
        }}

        .results-meta {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.85rem;
            color: var(--text-muted);
            margin-bottom: 1.25rem;
            padding: 0 0.5rem;
        }}

        /* Grid de Cards */
        .cards-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 1.5rem;
        }}

        .card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            transition: var(--transition);
            box-shadow: var(--shadow-card);
        }}

        .card:hover {{
            transform: translateY(-5px);
            border-color: var(--border-hover);
            box-shadow: 0 16px 30px -10px rgba(0, 0, 0, 0.6), 0 0 20px -5px var(--primary-glow);
        }}

        .card-media {{
            position: relative;
            width: 100%;
            aspect-ratio: 1 / 1;
            background: var(--bg-surface);
            overflow: hidden;
        }}

        .card-img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
            transition: transform 0.4s ease;
        }}

        .card:hover .card-img {{
            transform: scale(1.05);
        }}

        .card-img-placeholder {{
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: radial-gradient(circle at center, #262D3D 0%, #151922 100%);
            color: var(--text-muted);
            gap: 0.5rem;
        }}

        .placeholder-icon {{
            font-size: 3rem;
            filter: drop-shadow(0 4px 10px rgba(0,0,0,0.4));
        }}

        .placeholder-id {{
            font-size: 0.8rem;
            font-weight: 700;
            color: var(--primary);
            letter-spacing: 0.05em;
        }}

        .card-badge {{
            position: absolute;
            top: 0.85rem;
            left: 0.85rem;
            background: rgba(11, 14, 20, 0.85);
            backdrop-filter: blur(8px);
            color: var(--text-main);
            border: 1px solid var(--border);
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            padding: 0.3rem 0.65rem;
            border-radius: 9999px;
        }}

        .card-body {{
            padding: 1.25rem;
            display: flex;
            flex-direction: column;
            flex-grow: 1;
        }}

        .card-header-row {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 0.45rem;
        }}

        .card-id {{
            font-size: 0.75rem;
            font-weight: 700;
            color: var(--primary);
            letter-spacing: 0.03em;
        }}

        .card-price {{
            font-size: 1.15rem;
            font-weight: 800;
            color: #38BDF8;
        }}

        .card-title {{
            font-size: 1.05rem;
            font-weight: 700;
            line-height: 1.35;
            color: var(--text-main);
            margin-bottom: 0.45rem;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            min-height: 2.7rem;
        }}

        .card-hook {{
            font-size: 0.85rem;
            color: var(--text-muted);
            line-height: 1.4;
            margin-bottom: 1.1rem;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            flex-grow: 1;
        }}

        .btn-cta {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            background: var(--primary);
            color: var(--text-dark);
            text-decoration: none;
            padding: 0.75rem 1rem;
            border-radius: var(--radius-md);
            font-size: 0.92rem;
            font-weight: 700;
            transition: var(--transition);
            width: 100%;
            margin-top: auto;
        }}

        .btn-cta:hover {{
            background: var(--primary-hover);
            box-shadow: 0 4px 16px var(--primary-glow);
            transform: translateY(-2px);
        }}

        .cta-icon {{
            transition: transform 0.2s ease;
        }}

        .btn-cta:hover .cta-icon {{
            transform: translateX(3px);
        }}

        /* Empty State */
        .empty-state {{
            display: none;
            text-align: center;
            padding: 4rem 1rem;
            color: var(--text-muted);
        }}

        .empty-state-icon {{
            font-size: 3rem;
            margin-bottom: 1rem;
        }}

        /* Footer */
        footer {{
            text-align: center;
            padding: 2.5rem 1rem;
            border-top: 1px solid var(--border);
            color: var(--text-muted);
            font-size: 0.85rem;
            background: var(--bg-surface);
        }}

        footer a {{
            color: var(--primary);
            text-decoration: none;
        }}

        footer a:hover {{
            text-decoration: underline;
        }}

        @media (max-width: 640px) {{
            header h1 {{ font-size: 1.8rem; }}
            .container {{ padding-top: 1.5rem; }}
            .cards-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <header>
        <div class="brand-badge">⚡ Ofertas Verificadas</div>
        <h1>Fábrica de Achadinhos</h1>
        <p>Os produtos mais virais e úteis da internet com links diretos de afiliados e os menores preços da Shopee!</p>
    </header>

    <main class="container">
        <div class="controls">
            <div class="search-box">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="11" cy="11" r="8"></circle>
                    <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
                <input type="text" id="searchInput" placeholder="Buscar por produto ou nicho..." autocomplete="off">
            </div>

            <div class="filters" id="filterContainer">
                {filtros_str}
            </div>
        </div>

        <div class="results-meta">
            <span id="resultsCount">Carregando produtos...</span>
            <span>Atualizado automaticamente</span>
        </div>

        <div class="cards-grid" id="cardsGrid">
            {cards_str}
        </div>

        <div class="empty-state" id="emptyState">
            <div class="empty-state-icon">🔍</div>
            <h3>Nenhum achadinho encontrado</h3>
            <p>Tente buscar por outro termo ou selecione a categoria "Todos".</p>
        </div>
    </main>

    <footer>
        <p>© 2026 Fábrica de Achadinhos. Como afiliado Shopee, recebemos comissão por compras qualificadas sem custo extra para você.</p>
    </footer>

    <script>
        (function() {{
            const searchInput = document.getElementById('searchInput');
            const filterButtons = document.querySelectorAll('.filter-btn');
            const cards = document.querySelectorAll('.card');
            const countEl = document.getElementById('resultsCount');
            const emptyState = document.getElementById('emptyState');
            const grid = document.getElementById('cardsGrid');

            let activeFilter = 'all';
            let searchQuery = '';

            function updateFilter() {{
                let visibleCount = 0;
                cards.forEach(card => {{
                    const nome = card.getAttribute('data-nome') || '';
                    const nicho = card.getAttribute('data-nicho') || '';

                    const matchesFilter = activeFilter === 'all' || nicho.includes(activeFilter);
                    const matchesSearch = !searchQuery || nome.includes(searchQuery) || nicho.includes(searchQuery);

                    if (matchesFilter && matchesSearch) {{
                        card.style.display = 'flex';
                        visibleCount++;
                    }} else {{
                        card.style.display = 'none';
                    }}
                }});

                countEl.textContent = `Exibindo ${{visibleCount}} ${{visibleCount === 1 ? 'achadinho' : 'achadinhos'}}`;
                if (visibleCount === 0) {{
                    grid.style.display = 'none';
                    emptyState.style.display = 'block';
                }} else {{
                    grid.style.display = 'grid';
                    emptyState.style.display = 'none';
                }}
            }}

            searchInput.addEventListener('input', (e) => {{
                searchQuery = e.target.value.trim().toLowerCase();
                updateFilter();
            }});

            filterButtons.forEach(btn => {{
                btn.addEventListener('click', () => {{
                    filterButtons.forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    activeFilter = btn.getAttribute('data-filter');
                    updateFilter();
                }});
            }});

            // Execução inicial
            updateFilter();
        }})();
    </script>
</body>
</html>
'''


def construir_vitrine(
    vitrine_dir: Path | None = None,
    midias_dir: Path | None = None,
) -> dict:
    """Orquestra a construção completa da vitrine estática."""
    v_dir = vitrine_dir or VITRINE_DIR
    v_dir.mkdir(parents=True, exist_ok=True)
    index_file = v_dir / "index.html"

    logger.info("Lendo produtos pela porta única (Sheets / fallback CSV)...")
    todos = ler_produtos()
    elegiveis = filtrar_produtos_vitrine(todos)

    logger.info("Total lido: %d produtos | Elegíveis para vitrine: %d", len(todos), len(elegiveis))

    imagens_map: dict[str, str | None] = {}
    com_imagem = 0
    com_cta = 0

    for p in elegiveis:
        img = encontrar_ou_copiar_imagem(p, vitrine_dir=v_dir, midias_dir=midias_dir)
        imagens_map[p.id] = img
        if img:
            com_imagem += 1
        if p.link_afiliado:
            com_cta += 1

    html_content = gerar_html_vitrine(elegiveis, imagens_map)
    index_file.write_text(html_content, encoding="utf-8")

    logger.info(
        "Vitrine gerada em %s: %d cards (%d com imagem, %d com CTA)",
        index_file, len(elegiveis), com_imagem, com_cta,
    )

    return {
        "total": len(todos),
        "elegiveis": len(elegiveis),
        "com_imagem": com_imagem,
        "com_cta": com_cta,
        "arquivo": str(index_file),
    }


if __name__ == "__main__":
    res = construir_vitrine()
    print("\n" + "=" * 50)
    print("✨ VITRINE ESTÁTICA CONSTRUÍDA COM SUCESSO!")
    print(f"📄 Arquivo: {res['arquivo']}")
    print(f"📦 Cards: {res['elegiveis']} elegíveis (de {res['total']} cadastrados)")
    print(f"🖼️ Imagens vinculadas: {res['com_imagem']}")
    print(f"🔗 Links com CTA: {res['com_cta']}")
    print("=" * 50)
