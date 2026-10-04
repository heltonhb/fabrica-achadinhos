"""
scripts/gerar_vitrine.py — Gerador de site estático da vitrine de achadinhos.

Lê produtos da porta única (sheets.ler_produtos com fallback CSV local),
filtra produtos elegíveis (com nome e link afiliado), copia imagens disponíveis
de Midias/ para vitrine/assets/ e gera vitrine/index.html (para deploy na Vercel).

Otimizado especificamente para tráfego de vídeos curtos (Shorts / Reels / TikTok):
- Seleção automática do "Achadinho do Momento" (Opção B: último produto postado)
- Destaque Hero pulsante no topo
- Grade compacta de 2 colunas no celular (estilo Shopee / feed de ofertas)
- Miniaturas obrigatórias com badge de #ID sobreposto na foto
- Busca instantânea por #ID (ex: digita '6' -> acha '#06') e nome
- Filtros em pílulas horizontais navegáveis por toque
- Banner sutil de escape para in-app browsers (Instagram, TikTok, YouTube)
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
    """Filtra produtos válidos para exibição na vitrine pública."""
    validos = []
    for p in produtos:
        pid = (p.id or "").strip()
        nome = (p.nome or "").strip()
        link = (p.link_afiliado or "").strip()
        if pid and nome and link:
            validos.append(p)
    return validos


def selecionar_produto_do_momento(produtos: list[Produto]) -> Produto | None:
    """Seleciona o 'Produto do Momento / Vídeo de Hoje' (Opção B).

    1. Filtra produtos com status 'Postado' (case-insensitive).
    2. Se houver mais de um, seleciona o último da lista (mais recente).
    3. Se nenhum tiver status 'Postado', usa o último produto cadastrado como fallback.
    """
    postados = [p for p in produtos if (p.status or "").strip().lower() == "postado"]
    if postados:
        return postados[-1]
    if produtos:
        return produtos[-1]
    return None


def encontrar_ou_copiar_imagem(
    p: Produto,
    vitrine_dir: Path | None = None,
    midias_dir: Path | None = None,
) -> str | None:
    """Retorna o caminho relativo da imagem do produto para a vitrine.

    1. Checa se já existe vitrine/assets/{slug}.jpg (ou .jpeg, .png, .webp).
    2. Checa se existe imagem já salva com mesmo sufixo de nome (outro ID do mesmo produto).
    3. Busca na pasta de mídias por slug, p.pasta_midias, prefixo numérico ou nome.
    4. Copia a melhor imagem para assets/{slug}.jpg.
    """
    v_dir = vitrine_dir or VITRINE_DIR
    m_dir = midias_dir or MIDIAS_DIR
    assets_path = v_dir / "assets"
    assets_path.mkdir(parents=True, exist_ok=True)

    slug = p.slug
    name_suffix = slug.split("_", 1)[-1] if "_" in slug else slug
    num_id = p.id.replace("#", "").strip()

    # 0. Checa se o usuário colocou a foto diretamente por ID simples (ex: 06.jpg, 6.jpg, #06.jpg)
    nomes_simples = [num_id, num_id.lstrip("0"), p.id.replace("#", ""), p.id]
    for n in nomes_simples:
        if not n:
            continue
        for ext in (".jpg", ".jpeg", ".webp", ".png"):
            candidato = assets_path / f"{n}{ext}"
            if candidato.exists() and candidato.is_file():
                return f"assets/{candidato.name}"

    # 1. Checa se já existe no vitrine/assets com o slug exato
    for ext in (".jpg", ".jpeg", ".webp", ".png"):
        candidato = assets_path / f"{slug}{ext}"
        if candidato.exists() and candidato.is_file():
            return f"assets/{candidato.name}"

    # 2. Checa se existe em assets outro arquivo com o mesmo sufixo de nome
    if name_suffix:
        for f in assets_path.iterdir():
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".webp", ".png"):
                if f.stem.endswith(name_suffix):
                    dest = assets_path / f"{slug}{f.suffix}"
                    try:
                        shutil.copy2(f, dest)
                        return f"assets/{dest.name}"
                    except Exception:
                        return f"assets/{f.name}"

    # 3. Busca na pasta de mídias
    pastas_candidatas: list[Path] = []
    if p.pasta_midias:
        pm = m_dir / p.pasta_midias
        if pm.exists() and pm.is_dir():
            pastas_candidatas.append(pm)

    pastas_candidatas.append(m_dir / slug)

    if m_dir.exists():
        # Palavras-chave do nome do produto para evitar associar pasta de outro produto
        nome_tokens = [w for w in re.sub(r"[^a-zA-Z0-9]", " ", p.nome.lower()).split() if len(w) > 3]

        for sub in m_dir.iterdir():
            if not sub.is_dir():
                continue
            sub_lower = sub.name.lower()
            tem_nome_parecido = any(t in sub_lower for t in nome_tokens) if nome_tokens else True

            # Só aceita pasta com mesmo prefixo de ID se também tiver coerência de nome
            if (num_id and sub.name.startswith(f"{num_id}_") and tem_nome_parecido) or (name_suffix and sub.name.endswith(name_suffix)):
                if sub not in pastas_candidatas:
                    pastas_candidatas.append(sub)

    exts = {".jpg", ".jpeg", ".png", ".webp"}
    for pasta in pastas_candidatas:
        if not pasta.exists() or not pasta.is_dir():
            continue

        arquivos = [f for f in pasta.iterdir() if f.is_file() and f.suffix.lower() in exts]
        if not arquivos:
            continue

        def prioridade(f: Path) -> int:
            nome_lower = f.name.lower()
            if "main" in nome_lower:
                return 0
            if "variant" in nome_lower:
                return 1
            return 2

        arquivos.sort(key=prioridade)
        melhor = arquivos[0]

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


def extrair_numero_id(id_str: str) -> str:
    """Extrai apenas os dígitos numéricos do ID (ex: '#06' -> '6', '06')."""
    numeros = re.sub(r"[^\d]", "", id_str)
    return numeros.lstrip("0") or "0" if numeros else ""


def gerar_html_vitrine(
    produtos: list[Produto],
    imagens_map: dict[str, str | None],
    produto_momento: Produto | None = None,
) -> str:
    """Gera o HTML completo, responsivo, mobile-first em 2 colunas com busca e hero card."""
    # Coleta nichos únicos para as pílulas de filtro
    nichos_set = set()
    for p in produtos:
        n = (p.nicho or "").strip()
        if n:
            nichos_set.add(n.title())
    nichos = sorted(nichos_set)

    # Hero Card: Achadinho do Momento (Vídeo de Hoje)
    hero_html = ""
    if produto_momento:
        h_pid = html.escape(produto_momento.id.strip())
        h_num = extrair_numero_id(h_pid)
        h_nome = html.escape(produto_momento.nome.strip())
        h_nicho = html.escape((produto_momento.nicho or "Em Alta").strip().title())
        h_preco = html.escape(formatar_preco(produto_momento.preco))
        h_link = html.escape(produto_momento.link_afiliado.strip())
        h_img = imagens_map.get(produto_momento.id)

        if h_img:
            h_img_html = f'<img src="{h_img}" alt="{h_nome}" class="hero-img" loading="eager" />'
        else:
            h_img_html = f'''
            <div class="card-img-placeholder hero-placeholder">
                <span class="placeholder-icon">🛍️</span>
                <span class="placeholder-id">{h_pid}</span>
            </div>'''

        h_preco_html = f'<div class="hero-price">{h_preco}</div>' if h_preco else ''

        hero_html = f'''
        <section class="hero-wrapper" id="heroSection" 
                 data-id="{h_pid.lower()}" 
                 data-id-num="{h_num}" 
                 data-nome="{h_nome.lower()}" 
                 data-nicho="{h_nicho.lower()}">
            <div class="hero-card">
                <div class="hero-badge-top">
                    <span class="hero-flame">🔥</span>
                    <span>VISTO NO ÚLTIMO VÍDEO</span>
                </div>
                <div class="hero-media">
                    {h_img_html}
                    <span class="card-id-badge hero-id-badge">{h_pid}</span>
                </div>
                <div class="hero-content">
                    <div class="hero-category-tag">{h_nicho}</div>
                    <h2 class="hero-title">{h_nome}</h2>
                    {h_preco_html}
                    <a href="{h_link}" target="_blank" rel="noopener sponsored" class="btn-hero-cta">
                        Abrir no App Shopee
                        <svg class="cta-icon" viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                            <path fill-rule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clip-rule="evenodd" />
                        </svg>
                    </a>
                </div>
            </div>
        </section>'''

    # Cards da grade (2 colunas no celular)
    cards_html = []
    for p in produtos:
        pid = html.escape(p.id.strip())
        num_clean = extrair_numero_id(pid)
        nome = html.escape(p.nome.strip())
        nicho = html.escape((p.nicho or "Achadinho").strip().title())
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

        card = f'''
        <article class="card" 
                 data-id="{pid.lower()}" 
                 data-id-num="{num_clean}" 
                 data-nicho="{nicho.lower()}" 
                 data-nome="{nome.lower()}">
            <div class="card-media">
                {img_html}
                <span class="card-id-badge">{pid}</span>
                <span class="card-category-badge">{nicho}</span>
            </div>
            <div class="card-body">
                <div class="card-price-row">
                    {preco_html}
                </div>
                <h3 class="card-title" title="{nome}">{nome}</h3>
                <a href="{link}" target="_blank" rel="noopener sponsored" class="btn-cta">
                    <span>Ver na Shopee</span>
                    <svg class="cta-icon" viewBox="0 0 20 20" fill="currentColor" width="14" height="14">
                        <path fill-rule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clip-rule="evenodd" />
                    </svg>
                </a>
            </div>
        </article>'''
        cards_html.append(card)

    cards_str = "\n".join(cards_html)

    # Botões de filtro em pílulas deslizáveis
    filtros_html = ['<button class="filter-pill active" data-filter="all">🔥 Todos</button>']
    for n in nichos:
        filtros_html.append(f'<button class="filter-pill" data-filter="{n.lower()}">{n}</button>')
    filtros_str = "\n".join(filtros_html)

    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, viewport-fit=cover">
    <title>Fábrica de Achadinhos — Vitrine Oficial Shopee</title>
    <meta name="description" content="Encontre os achadinhos do vídeo com fotos reais, número exato (#ID) e links diretos para o aplicativo da Shopee!">
    <meta property="og:title" content="Fábrica de Achadinhos — Vitrine Oficial">
    <meta property="og:description" content="Confira os achadinhos testados em nossos vídeos com links diretos da Shopee!">
    <meta property="og:type" content="website">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --primary: #FFD600;
            --primary-glow: rgba(255, 214, 0, 0.25);
            --shopee: #EE4D2D;
            --shopee-hover: #D73211;
            --shopee-glow: rgba(238, 77, 45, 0.35);
            --bg-body: #0A0D14;
            --bg-surface: #131722;
            --bg-card: #181D2B;
            --bg-card-hover: #22293C;
            --text-main: #FFFFFF;
            --text-muted: #94A3B8;
            --text-dark: #0A0D14;
            --accent-cyan: #38BDF8;
            --border: rgba(255, 255, 255, 0.08);
            --border-hover: rgba(255, 214, 0, 0.4);
            --radius-sm: 8px;
            --radius-md: 12px;
            --radius-lg: 18px;
            --transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }}

        body {{
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: var(--bg-body);
            color: var(--text-main);
            min-height: 100vh;
            line-height: 1.45;
            -webkit-font-smoothing: antialiased;
        }}

        /* Banner de Escape do In-App Browser (Instagram/TikTok/YouTube) */
        .inapp-banner {{
            display: none;
            background: linear-gradient(90deg, #1A1F2C 0%, #151922 100%);
            border-bottom: 1px solid rgba(255, 214, 0, 0.35);
            color: #E2E8F0;
            padding: 0.65rem 1rem;
            font-size: 0.78rem;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            position: sticky;
            top: 0;
            z-index: 100;
            backdrop-filter: blur(10px);
        }}

        .inapp-content {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            flex-grow: 1;
        }}

        .inapp-content strong {{
            color: var(--primary);
        }}

        .inapp-close {{
            background: transparent;
            border: none;
            color: var(--text-muted);
            font-size: 1.1rem;
            cursor: pointer;
            padding: 0.2rem 0.4rem;
        }}

        /* Header */
        header {{
            background: linear-gradient(180deg, rgba(19, 23, 34, 0.95) 0%, rgba(10, 13, 20, 0.8) 100%);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--border);
            padding: 1.8rem 1rem 1.4rem;
            text-align: center;
        }}

        .brand-badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: var(--primary-glow);
            color: var(--primary);
            border: 1px solid rgba(255, 214, 0, 0.35);
            padding: 0.3rem 0.85rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 800;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin-bottom: 0.6rem;
        }}

        header h1 {{
            font-size: 1.85rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            margin-bottom: 0.3rem;
            background: linear-gradient(135deg, #FFFFFF 65%, var(--primary) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        header p {{
            color: var(--text-muted);
            font-size: 0.9rem;
            max-width: 480px;
            margin: 0 auto;
        }}

        /* Container Principal */
        .container {{
            max-width: 1050px;
            margin: 0 auto;
            padding: 1.25rem 0.85rem 3.5rem;
        }}

        /* ─── Hero Card: Achadinho do Momento ─── */
        .hero-wrapper {{
            margin-bottom: 1.75rem;
        }}

        @keyframes hero-pulse {{
            0% {{
                box-shadow: 0 0 0 0 rgba(238, 77, 45, 0.5), 0 8px 20px rgba(0, 0, 0, 0.5);
            }}
            70% {{
                box-shadow: 0 0 0 10px rgba(238, 77, 45, 0), 0 12px 25px rgba(0, 0, 0, 0.6);
            }}
            100% {{
                box-shadow: 0 0 0 0 rgba(238, 77, 45, 0), 0 8px 20px rgba(0, 0, 0, 0.5);
            }}
        }}

        @keyframes flame-bounce {{
            0%, 100% {{ transform: scale(1); }}
            50% {{ transform: scale(1.2); }}
        }}

        .hero-card {{
            background: linear-gradient(145deg, #1C2232 0%, #131722 100%);
            border: 2px solid var(--shopee);
            border-radius: var(--radius-lg);
            overflow: hidden;
            display: grid;
            grid-template-columns: 140px 1fr;
            position: relative;
            animation: hero-pulse 2.8s infinite ease-in-out;
            transition: var(--transition);
        }}

        .hero-badge-top {{
            position: absolute;
            top: 0;
            right: 0;
            background: linear-gradient(90deg, var(--shopee) 0%, #FF6B4A 100%);
            color: #FFFFFF;
            font-size: 0.68rem;
            font-weight: 800;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            padding: 0.3rem 0.75rem;
            border-bottom-left-radius: 12px;
            display: inline-flex;
            align-items: center;
            gap: 5px;
            z-index: 3;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        }}

        .hero-flame {{
            display: inline-block;
            animation: flame-bounce 1.5s infinite ease-in-out;
        }}

        .hero-media {{
            position: relative;
            width: 100%;
            height: 100%;
            min-height: 140px;
            background: var(--bg-surface);
            overflow: hidden;
        }}

        .hero-img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }}

        .hero-id-badge {{
            font-size: 0.85rem !important;
            padding: 3px 8px !important;
        }}

        .hero-content {{
            padding: 1.4rem 1rem 1rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }}

        .hero-category-tag {{
            color: var(--text-muted);
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.25rem;
        }}

        .hero-title {{
            font-size: 1rem;
            font-weight: 700;
            line-height: 1.3;
            color: var(--text-main);
            margin-bottom: 0.35rem;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}

        .hero-price {{
            font-size: 1.25rem;
            font-weight: 800;
            color: var(--accent-cyan);
            margin-bottom: 0.75rem;
        }}

        .btn-hero-cta {{
            background: linear-gradient(135deg, var(--shopee) 0%, #FF5A36 100%);
            color: #FFFFFF;
            font-size: 0.9rem;
            font-weight: 800;
            text-decoration: none;
            padding: 0.7rem 1.1rem;
            border-radius: var(--radius-md);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: var(--transition);
            box-shadow: 0 4px 15px var(--shopee-glow);
            width: fit-content;
        }}

        .btn-hero-cta:hover {{
            background: linear-gradient(135deg, var(--shopee-hover) 0%, #EE4D2D 100%);
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(238, 77, 45, 0.5);
        }}

        /* ─── Controles: Busca e Pílulas de Nicho ─── */
        .controls-wrapper {{
            margin-bottom: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 0.85rem;
        }}

        .search-container {{
            position: relative;
            max-width: 580px;
            width: 100%;
            margin: 0 auto;
        }}

        .search-icon {{
            position: absolute;
            left: 1rem;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
            pointer-events: none;
        }}

        .search-input {{
            width: 100%;
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: 9999px;
            padding: 0.85rem 2.8rem 0.85rem 2.85rem;
            color: var(--text-main);
            font-size: 0.92rem;
            font-family: inherit;
            outline: none;
            transition: var(--transition);
        }}

        .search-input:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 0 3px var(--primary-glow);
        }}

        .search-clear {{
            position: absolute;
            right: 0.9rem;
            top: 50%;
            transform: translateY(-50%);
            background: transparent;
            border: none;
            color: var(--text-muted);
            font-size: 1.1rem;
            cursor: pointer;
            display: none;
            padding: 0.2rem;
        }}

        /* Pílulas de Filtro Deslizáveis por Toque */
        .pills-scroll {{
            display: flex;
            gap: 0.5rem;
            overflow-x: auto;
            padding: 0.3rem 0.2rem;
            scrollbar-width: none;
            -ms-overflow-style: none;
            -webkit-overflow-scrolling: touch;
            white-space: nowrap;
        }}

        .pills-scroll::-webkit-scrollbar {{
            display: none;
        }}

        .filter-pill {{
            flex-shrink: 0;
            background: var(--bg-surface);
            color: var(--text-muted);
            border: 1px solid var(--border);
            padding: 0.45rem 0.9rem;
            border-radius: 9999px;
            font-size: 0.8rem;
            font-weight: 600;
            font-family: inherit;
            cursor: pointer;
            transition: var(--transition);
        }}

        .filter-pill:hover {{
            color: var(--text-main);
            border-color: rgba(255, 255, 255, 0.2);
        }}

        .filter-pill.active {{
            background: var(--primary);
            color: var(--text-dark);
            border-color: var(--primary);
            font-weight: 700;
            box-shadow: 0 3px 10px var(--primary-glow);
        }}

        /* Meta de Resultados */
        .results-meta {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-bottom: 0.85rem;
            padding: 0 0.25rem;
        }}

        /* ─── Grade de 2 Colunas Mobile ─── */
        .cards-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
        }}

        .card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            transition: var(--transition);
        }}

        .card:hover {{
            border-color: var(--border-hover);
            transform: translateY(-3px);
            box-shadow: 0 10px 20px -5px rgba(0, 0, 0, 0.5);
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
            transition: transform 0.3s ease;
        }}

        .card:hover .card-img {{
            transform: scale(1.04);
        }}

        /* Badges Sobrepostos na Foto */
        .card-id-badge {{
            position: absolute;
            top: 6px;
            left: 6px;
            background: rgba(10, 13, 20, 0.9);
            border: 1px solid rgba(255, 214, 0, 0.5);
            color: var(--primary);
            font-size: 0.74rem;
            font-weight: 800;
            letter-spacing: 0.04em;
            padding: 2px 7px;
            border-radius: 6px;
            backdrop-filter: blur(4px);
            z-index: 2;
        }}

        .card-category-badge {{
            position: absolute;
            top: 6px;
            right: 6px;
            background: rgba(10, 13, 20, 0.85);
            color: #CBD5E1;
            border: 1px solid var(--border);
            font-size: 0.62rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            padding: 2px 6px;
            border-radius: 6px;
            backdrop-filter: blur(4px);
            max-width: 65%;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            z-index: 2;
        }}

        .card-img-placeholder {{
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: radial-gradient(circle at center, #22283A 0%, #131722 100%);
            color: var(--text-muted);
            gap: 0.4rem;
        }}

        .placeholder-icon {{
            font-size: 2.4rem;
            filter: drop-shadow(0 3px 8px rgba(0,0,0,0.4));
        }}

        .placeholder-id {{
            font-size: 0.75rem;
            font-weight: 800;
            color: var(--primary);
        }}

        .card-body {{
            padding: 0.65rem 0.65rem 0.75rem;
            display: flex;
            flex-direction: column;
            flex-grow: 1;
            justify-content: space-between;
        }}

        .card-price-row {{
            margin-bottom: 0.25rem;
        }}

        .card-price {{
            font-size: 1.05rem;
            font-weight: 800;
            color: var(--accent-cyan);
            letter-spacing: -0.01em;
        }}

        .card-title {{
            font-size: 0.8rem;
            font-weight: 600;
            line-height: 1.25;
            color: var(--text-main);
            margin-bottom: 0.55rem;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            min-height: 2rem;
        }}

        .btn-cta {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 5px;
            background: linear-gradient(135deg, var(--shopee) 0%, #FF5A36 100%);
            color: #FFFFFF;
            text-decoration: none;
            padding: 0.55rem 0.5rem;
            border-radius: var(--radius-sm);
            font-size: 0.8rem;
            font-weight: 700;
            transition: var(--transition);
            width: 100%;
            margin-top: auto;
            box-shadow: 0 2px 8px var(--shopee-glow);
        }}

        .btn-cta:hover {{
            background: linear-gradient(135deg, var(--shopee-hover) 0%, #EE4D2D 100%);
            transform: translateY(-1px);
        }}

        .cta-icon {{
            transition: transform 0.2s ease;
            flex-shrink: 0;
        }}

        .btn-cta:hover .cta-icon,
        .btn-hero-cta:hover .cta-icon {{
            transform: translateX(2px);
        }}

        /* Empty State */
        .empty-state {{
            display: none;
            text-align: center;
            padding: 3.5rem 1rem;
            color: var(--text-muted);
        }}

        .empty-state-icon {{
            font-size: 2.8rem;
            margin-bottom: 0.8rem;
        }}

        /* Footer */
        footer {{
            text-align: center;
            padding: 2rem 1rem;
            border-top: 1px solid var(--border);
            color: var(--text-muted);
            font-size: 0.8rem;
            background: var(--bg-surface);
        }}

        /* Responsividade para Telas Maiores */
        @media (min-width: 641px) {{
            header h1 {{ font-size: 2.2rem; }}
            .container {{ padding: 2rem 1.25rem 4rem; }}
            .pills-scroll {{ justify-content: center; flex-wrap: wrap; }}
            .cards-grid {{
                grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
                gap: 1.25rem;
            }}
            .card-body {{ padding: 0.85rem; }}
            .card-title {{ font-size: 0.9rem; min-height: 2.3rem; }}
            .btn-cta {{ padding: 0.65rem 0.75rem; font-size: 0.85rem; }}
            .hero-card {{ grid-template-columns: 180px 1fr; }}
            .hero-title {{ font-size: 1.2rem; }}
        }}

        @media (max-width: 440px) {{
            .hero-card {{ grid-template-columns: 110px 1fr; }}
            .hero-content {{ padding: 1.5rem 0.75rem 0.75rem; }}
            .btn-hero-cta {{ width: 100%; font-size: 0.82rem; padding: 0.6rem 0.5rem; }}
        }}
    </style>
</head>
<body>
    <!-- Banner de Orientação para In-App Browsers -->
    <div class="inapp-banner" id="inAppNotice">
        <div class="inapp-content">
            <span>💡</span>
            <span>Para abrir direto no <strong>App da Shopee logado</strong>, toque nos <strong>3 pontinhos (⋮)</strong> e selecione <em>"Abrir no navegador"</em>.</span>
        </div>
        <button class="inapp-close" onclick="document.getElementById('inAppNotice').style.display='none'" aria-label="Fechar">✕</button>
    </div>

    <header>
        <div class="brand-badge">⚡ Ofertas Verificadas Shopee</div>
        <h1>Fábrica de Achadinhos</h1>
        <p>Encontre o achadinho do vídeo pelo número (#ID) ou foto com link direto para o app da Shopee!</p>
    </header>

    <main class="container">
        <!-- Achadinho do Momento (Destaque do Vídeo Recente) -->
        {hero_html}

        <!-- Controles: Busca Preditiva e Pílulas de Nicho -->
        <div class="controls-wrapper">
            <div class="search-container">
                <svg class="search-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="11" cy="11" r="8"></circle>
                    <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
                <input type="text" id="searchInput" class="search-input" placeholder="🔍 Digite o # do vídeo (ex: 6) ou nome..." autocomplete="off">
                <button type="button" id="searchClear" class="search-clear" aria-label="Limpar busca">✕</button>
            </div>

            <div class="pills-scroll" id="pillsContainer">
                {filtros_str}
            </div>
        </div>

        <div class="results-meta">
            <span id="resultsCount">Carregando achadinhos...</span>
            <span>Atualizado automaticamente</span>
        </div>

        <!-- Grade de Produtos (2 Colunas no Mobile) -->
        <div class="cards-grid" id="cardsGrid">
            {cards_str}
        </div>

        <div class="empty-state" id="emptyState">
            <div class="empty-state-icon">🔍</div>
            <h3>Nenhum achadinho encontrado</h3>
            <p>Tente buscar por outro número (#) ou selecione a categoria "Todos".</p>
        </div>
    </main>

    <footer>
        <p>© 2026 Fábrica de Achadinhos. Como afiliado Shopee, recebemos comissão por compras qualificadas sem nenhum custo extra para você.</p>
    </footer>

    <script>
        (function() {{
            // 1. Detecção de In-App Browser (Instagram, TikTok, YouTube)
            try {{
                const ua = navigator.userAgent || navigator.vendor || window.opera || '';
                const isInApp = /Instagram|FBAN|FBAV|TikTok|musical_ly|YouTube/i.test(ua);
                if (isInApp) {{
                    const banner = document.getElementById('inAppNotice');
                    if (banner) banner.style.display = 'flex';
                }}
            }} catch (err) {{
                console.warn('Erro ao checar user agent:', err);
            }}

            // 2. Elementos DOM
            const searchInput = document.getElementById('searchInput');
            const searchClear = document.getElementById('searchClear');
            const pills = document.querySelectorAll('.filter-pill');
            const cards = document.querySelectorAll('.card');
            const heroSection = document.getElementById('heroSection');
            const countEl = document.getElementById('resultsCount');
            const emptyState = document.getElementById('emptyState');
            const grid = document.getElementById('cardsGrid');

            let activeFilter = 'all';
            let searchQuery = '';

            function updateFilter() {{
                const cleanQuery = searchQuery.replace('#', '').trim().toLowerCase();
                let visibleCount = 0;

                cards.forEach(card => {{
                    const cardId = (card.getAttribute('data-id') || '').toLowerCase();
                    const cardNum = (card.getAttribute('data-id-num') || '').toLowerCase();
                    const cardNome = (card.getAttribute('data-nome') || '').toLowerCase();
                    const cardNicho = (card.getAttribute('data-nicho') || '').toLowerCase();

                    const matchesFilter = activeFilter === 'all' || cardNicho.includes(activeFilter);
                    
                    let matchesSearch = true;
                    if (cleanQuery) {{
                        matchesSearch = cardId.includes(searchQuery) ||
                                       cardNum === cleanQuery ||
                                       cardNome.includes(searchQuery) ||
                                       cardNome.includes(cleanQuery) ||
                                       cardNicho.includes(cleanQuery);
                    }}

                    if (matchesFilter && matchesSearch) {{
                        card.style.display = 'flex';
                        visibleCount++;
                    }} else {{
                        card.style.display = 'none';
                    }}
                }});

                // Controle do Hero Card: Oculta se houver busca ou filtro que não corresponda ao produto
                if (heroSection) {{
                    if (cleanQuery || activeFilter !== 'all') {{
                        const hId = (heroSection.getAttribute('data-id') || '').toLowerCase();
                        const hNum = (heroSection.getAttribute('data-id-num') || '').toLowerCase();
                        const hNome = (heroSection.getAttribute('data-nome') || '').toLowerCase();
                        const hNicho = (heroSection.getAttribute('data-nicho') || '').toLowerCase();

                        const hMatchesFilter = activeFilter === 'all' || hNicho.includes(activeFilter);
                        const hMatchesSearch = !cleanQuery || hId.includes(searchQuery) || hNum === cleanQuery || hNome.includes(cleanQuery);

                        heroSection.style.display = (hMatchesFilter && hMatchesSearch) ? 'block' : 'none';
                    }} else {{
                        heroSection.style.display = 'block';
                    }}
                }}

                countEl.textContent = `Exibindo ${{visibleCount}} ${{visibleCount === 1 ? 'achadinho' : 'achadinhos'}}`;
                if (visibleCount === 0) {{
                    grid.style.display = 'none';
                    emptyState.style.display = 'block';
                }} else {{
                    grid.style.display = 'grid';
                    emptyState.style.display = 'none';
                }}
            }}

            // Eventos de Busca
            searchInput.addEventListener('input', (e) => {{
                searchQuery = e.target.value.trim().toLowerCase();
                searchClear.style.display = searchQuery ? 'block' : 'none';
                updateFilter();
            }});

            searchClear.addEventListener('click', () => {{
                searchInput.value = '';
                searchQuery = '';
                searchClear.style.display = 'none';
                searchInput.focus();
                updateFilter();
            }});

            // Eventos das Pílulas de Categoria
            pills.forEach(pill => {{
                pill.addEventListener('click', () => {{
                    pills.forEach(p => p.classList.remove('active'));
                    pill.classList.add('active');
                    activeFilter = pill.getAttribute('data-filter');
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

    # Seleciona o 'Produto do Momento' (Opção B)
    produto_momento = selecionar_produto_do_momento(elegiveis)
    if produto_momento:
        logger.info(
            "Produto do Momento selecionado: %s - %s (Status: %s)",
            produto_momento.id, produto_momento.nome, produto_momento.status
        )

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

    html_content = gerar_html_vitrine(
        produtos=elegiveis,
        imagens_map=imagens_map,
        produto_momento=produto_momento,
    )
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
        "produto_momento": f"{produto_momento.id} - {produto_momento.nome}" if produto_momento else None,
        "arquivo": str(index_file),
    }


def sincronizar_e_atualizar_vitrine(hook_url: str = "") -> tuple[bool, str]:
    """Sincroniza a vitrine com o GitHub e a Vercel com 1 clique.

    1. Constrói a vitrine estática local com imagens e dados mais recentes.
    2. Adiciona 'vitrine/assets/' e 'achados.csv' ao Git.
    3. Se houver novas fotos ou arquivos modificados, faz commit e git push para o GitHub.
    4. Se não houve push (ex: nenhuma foto nova local) mas há Deploy Hook, dispara o webhook da Vercel.
    """
    import subprocess
    import requests

    # 1. Constrói vitrine local
    try:
        construir_vitrine()
    except Exception as exc:
        logger.warning("Aviso ao construir vitrine local: %s", exc)

    # 2. Checa e envia novas fotos ou dados locais para o GitHub
    push_feito = False
    try:
        subprocess.run(["git", "add", "vitrine/assets/", "achados.csv"], check=True, cwd=str(BASE_DIR))
        diff_proc = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(BASE_DIR))
        if diff_proc.returncode != 0:
            subprocess.run(
                ["git", "commit", "-m", "auto: atualiza fotos da vitrine e catalogo"],
                check=True,
                cwd=str(BASE_DIR)
            )
            push_proc = subprocess.run(
                ["git", "push", "origin", "main"],
                capture_output=True,
                text=True,
                cwd=str(BASE_DIR)
            )
            if push_proc.returncode == 0:
                push_feito = True
                logger.info("Git push de assets/vitrine executado com sucesso.")
            else:
                logger.warning("Falha ao dar git push: %s", push_proc.stderr)
    except Exception as exc:
        logger.warning("Erro no processo de git push automático: %s", exc)

    # 3. Dispara o Deploy Hook se configurado e não houve push
    if hook_url and not push_feito:
        try:
            resp = requests.post(hook_url.strip(), timeout=12)
            if resp.status_code in (200, 201):
                return True, "Deploy iniciado com sucesso na Vercel! O site estará atualizado em ~30s."
            return False, f"Vercel retornou código {resp.status_code}: {resp.text}"
        except Exception as exc:
            return False, f"Erro ao disparar Deploy Hook: {exc}"

    if push_feito:
        return True, "✅ Novas fotos e dados enviados para o GitHub com sucesso! O deploy na Vercel foi iniciado automaticamente (~30s)."

    return True, "Vitrine já está sincronizada e atualizada!"



if __name__ == "__main__":
    res = construir_vitrine()
    print("\n" + "=" * 50)
    print("✨ VITRINE ESTÁTICA CONSTRUÍDA COM SUCESSO!")
    print(f"📄 Arquivo: {res['arquivo']}")
    print(f"🌟 Produto do Momento: {res['produto_momento']}")
    print(f"📦 Cards: {res['elegiveis']} elegíveis (de {res['total']} cadastrados)")
    print(f"🖼️ Imagens vinculadas: {res['com_imagem']}")
    print(f"🔗 Links com CTA: {res['com_cta']}")
    print("=" * 50)
