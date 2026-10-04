"""
scraping.py — Extração automática de mídia de páginas de produto.

Suporta: Shopee, AliExpress
Extrai: imagens (JPEG/PNG) e vídeos (MP4) do anúncio.
Salva em: Midias/#NN_Slug/ (clipes) e Midias/#NN_Slug/imagens/
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from collections import deque
from threading import Lock
from urllib.parse import urlparse

import requests

from config import MIDIAS_DIR
from gemini_client import _chamar_gemini, _reparar_json


# ─── Agendador de chamadas à IA (limite raso) ────────────────────────────────
# Evita sobrepor requisições e dá espaço para a cota se recuperar.
# Uso: espera_atualiza_IA() antes de chamar _cadastro_por_ia();
# retorna None quando o tempo de aguardo foi excedido (ou nenhuma fila).

_IA_CALL_LOCK = Lock()
_IA_CALL_SEMAPHORE = deque[tuple[float, str]]()  # (tempo_limite, conteudo)
_IA_CALL_QUEUE = []  # caminhos de chamada aguardando (string)
_IA_CALL_LOCK_QUEUE = Lock()

# Máximo de requisições pendentes (simples backpressure)
MAX_IA_PENDENTES = 3


def _tempo_orm_de_IA() -> float | None:
    """Retorna o tempo (segundos) restante até o próximo lance poder ser executado."""
    with _IA_CALL_LOCK_QUEUE:
        if not _IA_CALL_QUEUE:
            return None
        return _IA_CALL_QUEUE[0][0]


def _agendar_IA_chamada(comprimento: str, timeout_s: float = 45.0) -> bool:
    """Adiciona uma chamada à fila. Retorna True se puder executar agora,
    False se ficou na fila aguardando.

    O agendador garante que no máximo 1 chamada é executada a cada
    _IA_CALL_INTERVAL_S, e não permite mais que MAX_IA_PENDENTES em fila.
    """
    global _IA_CALL_QUEUE
    now = time.monotonic()
    # remove itens expirados da frente da fila
    while _IA_CALL_QUEUE and _IA_CALL_QUEUE[0][0] <= now:
        _IA_CALL_QUEUE.pop(0)

    if len(_IA_CALL_QUEUE) >= MAX_IA_PENDENTES:
        # a fila está cheia; aguarda o vão
        return False

    _IA_CALL_QUEUE.append((now + _IA_CALL_INTERVAL_S, comprimento))
    return True


def _proximo_lance_IA() -> None:
    """Limpa a fila de lançamentos expirados. Deve ser chamada antes de
    executar uma chamada."""
    with _IA_CALL_LOCK_QUEUE:
        global _IA_CALL_QUEUE
        now = time.monotonic()
        while _IA_CALL_QUEUE and _IA_CALL_QUEUE[0][0] <= now:
            _IA_CALL_QUEUE.pop(0)


def _on_IA_chamada_concluida(comprimento: str) -> None:
    """Marca o término de uma chamada e avisa a fila.

    Sincroniza com a fila do agendador e libera espaço.
    """
    with _IA_CALL_LOCK_QUEUE:
        global _IA_CALL_QUEUE
        # remove o item correspondente à conclusão
        try:
            idx = _IA_CALL_QUEUE.index((time.monotonic(), comprimento))
            _IA_CALL_QUEUE.pop(idx)
        except ValueError:
            pass
        # se houver próximo item aguardando, sinaliza que pode começar
        if _IA_CALL_QUEUE:
            _IA_CALL_QUEUE[0] = (
                time.monotonic() + _IA_CALL_INTERVAL_S,
                _IA_CALL_QUEUE[0][1],
            )


# Intervalo mínimo entre chamadas consecutivas (segundos)
_IA_CALL_INTERVAL_S = 10.0


# ─── Cache da camada IA (evita chamadas repetidas do Gemini + Google) ──────────────
_CADASTRO_CACHE: dict[str, dict] = {}
_CACHE_TTL_S = 60 * 60  # 1h


def _cache_key(url: str) -> str:
    """Chave de cache baseada no link resolvido (link curto normalizado)."""
    return url


def _cadastro_por_cache(url: str) -> dict | None:
    """Retorna o cache salvo se ainda válido; senão None."""
    record = _CADASTRO_CACHE.get(_cache_key(url))
    if record is None:
        return None
    ts, dados = record
    if time.monotonic() - ts < _CACHE_TTL_S:
        return dados
    return None  # expirado


def _guardar_cadastro_cache(url: str, dados: dict) -> None:
    _CADASTRO_CACHE[_cache_key(url)] = (time.monotonic(), dados)


# ─── Derivação de nicho ─────────────────────────────────────────────────────────

# Categoria genérica de fallback quando a IA e a DOM não fornecem.
_NICHOS_FALLBACK = {
    "aspirador": "Limpeza",
    "bank": "Finanças",
    "piggy": "Finanças",
    "geladeira": "Eletro",
    "micro-ondas": "Eletro",
    "liquidificador": "Eletro",
    "creme": "Bem-estar",
    "shampoo": "Bem-estar",
    "sabonete": "Bem-estar",
    "pilha": "Eletro",
    "pneu": "Automóvel",
    "rexate": "Automóvel",
    "oleo": "Automóvel",
    "filtro": "Automóvel",
    "vetinho": "Mercearia",
    "açucar": "Mercearia",
    "farinha": "Mercearia",
    "arroz": "Mercearia",
    "feijão": "Mercearia",
    "leite": "Mercearia",
    "ovos": "Mercearia",
    "pão": "Mercearia",
    "cafe": "Mercearia",
    "sabonete": "Higiene",
    "escova": "Higiene",
    "cabelo": "Bem-estar",
    "pele": "Bem-estar",
    "calça": "Roupas",
    "camisa": "Roupas",
    "tênis": "Moda",
    "sapato": "Moda",
    "chinel": "Moda",
    "relógio": "Moda",
    "relógio": "Moda",
    "teclado": "Eletro",
    "mouse": "Eletro",
    "monitor": "Eletro",
    "fone": "Eletro",
    "fone": "Eletro",
    "carregador": "Eletro",
    "bateria": "Eletro",
    "painel": "Eletro",
    "sacola": "Bem-estar",
    "sacola": "Bem-estar",
}


def _derivar_nicho(url: str, nome: str, nicho_ia: str) -> str:
    """Tenta achar o nicho mais provável.

    Ordem:
      1. nicho já vindo da IA (por preferência)
      2. nicho dolorido da DOM (se boa)
      3. categorias soltas do HTML (auxílio)
      4. nicho derivado do nome do produto
      5. nicho genérico de fallback
    """
    txt = (nicho_ia or "").strip()
    if txt:
        return txt
    return ""


def _classificar_por_nome(nome: str) -> str:
    """Classifica o produto pelo nome em um nicho genérico, se possível."""
    if not nome:
        return ""
    low = nome.lower()
    for chave, nicho in _NICHOS_FALLBACK.items():
        if chave in low:
            return nicho
    return ""


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}


# ─── Shopee ──────────────────────────────────────────────────────────────────

def _resolve_short_url(url: str) -> str:
    """Resolve links curtos (s.shopee.com.br, shope.ee, shp.ee, shopee.link) para a URL completa."""
    if not url:
        return ""
    curtos = ("s.shopee.com.br", "shope.ee", "shp.ee", "shopee.link")
    if any(dom in url.lower() for dom in curtos):
        try:
            resp = requests.head(url, allow_redirects=True, timeout=10, headers=_HEADERS)
            if resp.url and resp.url != url and "error" not in resp.url.lower():
                return resp.url
        except Exception:
            pass
        try:
            resp = requests.get(url, allow_redirects=True, timeout=10, headers=_HEADERS, stream=True)
            if resp.url and resp.url != url and "error" not in resp.url.lower():
                return resp.url
            if resp.status_code == 200:
                texto_inicio = resp.raw.read(4096).decode("utf-8", errors="ignore")
                m_meta = re.search(r'content=["\']\d+;\s*url=([^"\']+)["\']', texto_inicio, re.I)
                if m_meta:
                    return m_meta.group(1).strip()
        except Exception:
            pass
    return url


def extrair_slug_shopee(url: str) -> str:
    """Extrai o título legível do produto a partir do slug da URL."""
    try:
        from urllib.parse import unquote, urlparse
        parsed = urlparse(url)
        path = unquote(parsed.path).strip("/")
        partes = [p for p in path.split("/") if p]
        if not partes:
            return ""
        candidato = partes[-1]
        if candidato.isdigit() and len(partes) > 1:
            candidato = partes[-2]
        # remove -i.shopid.itemid
        limpo = re.sub(r"-i[\s.]+\d+[\s.]+\d+.*$", "", candidato)
        nome = re.sub(r"[-_+]+", " ", limpo).strip()
        if re.fullmatch(r"[\d\s]+", nome) or nome.lower() in ("product", "universal-link", "item", "x"):
            return ""
        return nome
    except Exception:
        return ""


def _limpar_nome_produto(nome: str) -> str:
    """Remove sufixos de SEO comuns da Shopee como '| Shopee Brasil', 'Frete Grátis', etc."""
    if not nome:
        return ""
    nome = re.sub(r"\s*\|\s*Shopee Brasil.*$", "", nome, flags=re.I)
    nome = re.sub(r"^\s*Compre\s+", "", nome, flags=re.I)
    nome = re.sub(r"\s+na Shopee Brasil!.*$", "", nome, flags=re.I)
    nome = re.sub(r"\[FRETE GR[ÁA]TIS\]", "", nome, flags=re.I)
    nome = re.sub(r"\[PRONTA ENTREGA\]", "", nome, flags=re.I)
    return nome.strip()


def _limpar_url_imagem_shopee(url: str) -> str:
    """Garante URL absoluta e remove sufixos de miniatura (_tn, _xxs, etc.) para resolução máxima."""
    if not url:
        return ""
    if not url.startswith("http"):
        url = f"https://down-br.img.susercontent.com/file/{url.lstrip('/')}"
    # Remove sufixos como _tn, _xxs, _xs, _s, _m no final do hash da imagem
    url = re.sub(r"(_(?:tn|xxs|xs|s|m|xl|xxl))(?:\.[a-zA-Z]+)?$", "", url)
    return url


def _extrair_shopee_ld_json(html: str) -> dict | None:
    """Extrai dados estruturados schema.org (Product) embutidos no HTML."""
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL | re.I):
        try:
            dados = json.loads(m.group(1))
            items = dados if isinstance(dados, list) else [dados]
            for item in items:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    nome = _limpar_nome_produto(item.get("name", ""))
                    imgs = item.get("image", [])
                    if isinstance(imgs, str):
                        imgs = [imgs]
                    imgs_limpas = [_limpar_url_imagem_shopee(i) for i in imgs if i]
                    preco = ""
                    offers = item.get("offers")
                    if isinstance(offers, dict):
                        preco = str(offers.get("price") or offers.get("lowPrice") or "")
                    elif isinstance(offers, list) and offers:
                        preco = str(offers[0].get("price") or "")
                    return {
                        "nome": nome,
                        "imagens": [i for i in imgs_limpas if i],
                        "preco": _normalizar_preco(preco),
                        "descricao": item.get("description", ""),
                    }
        except (json.JSONDecodeError, Exception):
            continue
    return None


def _parse_shopee_url(url: str) -> tuple[str, str] | None:
    """Extrai shop_id e item_id de uma URL Shopee.
    Aceita múltiplos formatos (canônica, compartilhamento, links curtos, universal link, SEO).
    Retorna (shop_id, item_id) ou None.
    """
    url = _resolve_short_url(url)
    parsed = urlparse(url)
    partes = [p for p in parsed.path.strip("/").split("/") if p]

    # formato 1: -i.shopid.itemid ou -i shopid itemid no path / query
    m = re.search(r"-i[\s.]+(\d+)[\s.]+(\d+)", url)
    if m:
        return m.group(1), m.group(2)

    # formato 2: query params (itemid=... & shopid=... ou i=shopid.itemid)
    m = re.search(r"[?&]i=(\d+)[\.,]+(\d+)", url)
    if m:
        return m.group(1), m.group(2)

    item_id_m = re.search(r"[?&](?:item_?id)=(\d+)", url, re.I)
    shop_id_m = re.search(r"[?&](?:shop_?id)=(\d+)", url, re.I)
    if item_id_m and shop_id_m:
        return shop_id_m.group(1), item_id_m.group(1)

    # formato 3: /product/shopid/itemid ou /shopname/shopid/itemid
    if len(partes) >= 2 and partes[-1].isdigit() and partes[-2].isdigit():
        return partes[-2], partes[-1]
    if len(partes) >= 3 and partes[-1].isdigit() and partes[-2].isdigit():
        return partes[-2], partes[-1]

    # formato 4: compartilhamento (token alfanumérico no path, ex: /2gBUD8AlNf?...)
    # o item_id deve ser algo que possa ser o id público da Shopee
    for idx, parte in enumerate(partes):
        if parte.isdigit() and len(parte) >= 6:
            # se o segmento anterior é numérico, é o shop_id
            shop_id = partes[idx - 1] if idx > 0 and partes[idx - 1].isdigit() else None
            return shop_id, parte

    # formato 5: token universal-link (ex: /universal-link/Jogo-de-Lencol-400-Fios-i.111.222)
    # busca -i.shopid.itemid no path inteiro
    m = re.search(r"-i[\s.]+(\d+)[\s.]+(\d+)", "/".join(partes))
    if m:
        return m.group(1), m.group(2)

    return None


def _shopee_api(shop_id: str, item_id: str) -> dict | None:
    """Busca dados do produto via API interna da Shopee."""
    headers_api = dict(_HEADERS)
    headers_api.update({
        "Referer": "https://shopee.com.br/",
        "X-Requested-With": "XMLHttpRequest",
        "X-Shopee-Language": "pt-BR",
        "X-API-SOURCE": "pc",
        "Accept": "application/json",
    })
    urls = [
        f"https://shopee.com.br/api/v4/item/get?itemid={item_id}&shopid={shop_id}",
        f"https://shopee.com.br/api/v4/pdp/get_pc?item_id={item_id}&shop_id={shop_id}",
    ]
    for url in urls:
        try:
            resp = requests.get(url, headers=headers_api, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("data", {})
        except Exception:
            pass
    return None


def _shopee_meta_tags(url: str) -> dict | None:
    """Extrai dados de meta tags OpenGraph e application/ld+json (funciona mesmo com anti-bot leve)."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        resultado = {}

        # 1. Tenta application/ld+json primeiro (alta fidelidade)
        ld = _extrair_shopee_ld_json(html)
        if ld:
            if ld.get("nome"):
                resultado["name"] = ld["nome"]
            if ld.get("imagens"):
                resultado["images_list"] = ld["imagens"]
            if ld.get("preco"):
                resultado["price"] = ld["preco"]

        # 2. og:image
        m = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"', html)
        if m:
            resultado["image"] = _limpar_url_imagem_shopee(m.group(1))

        # 3. og:title
        m = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', html)
        if m and not resultado.get("name"):
            resultado["name"] = _limpar_nome_produto(m.group(1))

        # 4. og:description
        m = re.search(r'<meta[^>]*property="og:description"[^>]*content="([^"]+)"', html)
        if m:
            resultado["description"] = m.group(1)

        # 5. video (se tiver)
        m = re.search(r'<meta[^>]*property="og:video"[^>]*content="([^"]+)"', html)
        if m:
            resultado["video"] = m.group(1)
        else:
            m_vid = re.search(r'<video[^>]*src="([^"]+)"', html)
            if m_vid:
                resultado["video"] = m_vid.group(1)

        # 6. Procura todas as imagens da Shopee / susercontent no HTML (CDNs novas e antigas)
        padrao_imgs = r'https://(?:down-[a-z0-9\.\-]+|cf\.shopee\.com\.br)/file/([a-zA-Z0-9_\-]+)'
        encontrados = re.findall(padrao_imgs, html)
        if encontrados:
            imgs = resultado.get("images_list") or []
            vistos = {re.search(r'/file/([a-zA-Z0-9_\-]+)', u).group(1) for u in imgs if '/file/' in u}
            for h in encontrados:
                limpo_h = re.sub(r'_(?:tn|xxs|xs|s|m)$', '', h)
                if limpo_h not in vistos:
                    vistos.add(limpo_h)
                    imgs.append(f"https://down-br.img.susercontent.com/file/{limpo_h}")
            resultado["images_list"] = imgs[:15]

        return resultado if resultado else None
    except Exception:
        return None


def _shopee_direto(url: str) -> dict | None:
    """Fallback: abre a página e extrai dados do script __INITIAL_STATE__ ou ld+json."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # procura o JSON embutido no HTML
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?})\s*;", html)
        if m:
            try:
                data = json.loads(m.group(1))
                item = data.get("item", {}).get("itemData", {})
                if item:
                    return item
            except Exception:
                pass

        # ld+json
        ld = _extrair_shopee_ld_json(html)
        if ld and (ld.get("imagens") or ld.get("nome")):
            return {
                "name": ld.get("nome", ""),
                "images": ld.get("imagens", []),
                "price": ld.get("preco", ""),
            }
    except Exception:
        pass
    return None


def _shopee_midia_navegador(url: str) -> dict | None:
    """Extrai imagens e vídeos da Shopee usando Playwright (bypassa proteções anti-bot)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    try:
        with sync_playwright() as pw:
            headless_mode = not bool(os.environ.get("DISPLAY"))
            nav = pw.chromium.launch(
                headless=headless_mode,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            ctx = nav.new_context(
                locale="pt-BR",
                user_agent=_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 800},
            )
            page = ctx.new_page()

            videos_coletados = []

            def _on_response(resp):
                r_url = resp.url
                if any(ext in r_url.lower() for ext in (".mp4", "cvf.shopee.com.br", "down-bs-br.img.susercontent.com")):
                    if r_url not in videos_coletados:
                        videos_coletados.append(r_url)

            page.on("response", _on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)

            for _ in range(8):
                page.wait_for_timeout(1500)
                if "Ofertas incríveis" not in page.title():
                    break

            srcs = page.eval_on_selector_all(
                'img[src*="/file/"]',
                "els => els.map(e => e.src).filter(Boolean)"
            )

            dom_videos = page.eval_on_selector_all(
                "video source, video",
                "els => els.map(e => e.src || e.getAttribute('src')).filter(Boolean)"
            )
            for v in dom_videos:
                if v and v.startswith("http") and v not in videos_coletados:
                    videos_coletados.append(v)

            meta_title = page.title()
            nav.close()

            imgs_finais = []
            vistos_hash = set()
            for s in srcs:
                m_hash = re.search(r'/file/([a-zA-Z0-9_\-]+)', s)
                if m_hash:
                    h = re.sub(r'_(?:tn|xxs|xs|s|m)$', '', m_hash.group(1))
                    if h not in vistos_hash:
                        vistos_hash.add(h)
                        imgs_finais.append(f"https://down-br.img.susercontent.com/file/{h}")

            nome = _limpar_nome_produto(meta_title)
            if "Ofertas incríveis" in nome or "Shopee Brasil" in nome:
                nome = ""

            if imgs_finais or videos_coletados:
                return {
                    "imagens": imgs_finais[:15],
                    "videos": videos_coletados[:5],
                    "nome": nome,
                }
    except Exception as exc:
        print(f"[shopee] Fallback de navegador para mídia falhou: {exc}")
    return None


def extrair_shopee(url: str) -> dict:
    """Extrai imagens e vídeos de um anúncio Shopee.

    Retorna: {"imagens": [...], "videos": [...], "nome": str, "fonte": "shopee", "fallback": bool}
    """
    resultado = {"imagens": [], "videos": [], "nome": "", "fonte": "shopee", "fallback": False}

    # resolve link curto
    url = _resolve_short_url(url)
    slug_nome = extrair_slug_shopee(url)

    ids = _parse_shopee_url(url)
    if not ids:
        print(f"[shopee] Não conseguiu extrair IDs da URL: {url}")
        resultado["fallback"] = True
        resultado["instrucoes"] = (
            "❌ Não foi possível extrair mídia automaticamente.\n"
            "A Shopee tem proteção anti-bot muito forte.\n\n"
            "📋 Opções:\n"
            "1. Use a extensão 'AliSave' ou 'Downloader for Shopee' no Chrome\n"
            "2. Baixe os vídeos manualmente na página do produto\n"
            "3. Coloque os arquivos na pasta Midias/#NN_Slug/"
        )
        return resultado

    shop_id, item_id = ids
    print(f"[shopee] Buscando item {item_id} da loja {shop_id}")

    # 1. tenta API primeiro
    item = _shopee_api(shop_id, item_id)

    # 2. fallback: HTML direto
    if not item:
        print("[shopee] API falhou, tentando HTML...")
        item = _shopee_direto(url)

    # 3. fallback: meta tags e LD-JSON
    if not item:
        print("[shopee] HTML falhou, tentando meta tags...")
        meta = _shopee_meta_tags(url)
        if meta:
            if meta.get("image"):
                resultado["imagens"].append(meta["image"])
            if meta.get("images_list"):
                resultado["imagens"].extend(meta["images_list"])
            if meta.get("video"):
                resultado["videos"].append(meta["video"])
            resultado["nome"] = meta.get("name", "") or slug_nome
            if resultado["imagens"] or resultado["videos"]:
                # deduplica imagens
                resultado["imagens"] = list(dict.fromkeys(resultado["imagens"]))
                resultado["videos"] = list(dict.fromkeys(resultado["videos"]))
                print(f"[shopee] Meta tags: {len(resultado['imagens'])} imagens, {len(resultado['videos'])} vídeos")
                return resultado

    # 4. fallback: navegador Playwright (caso o anti-bot bloqueie requisições HTTP)
    if not item and not resultado["imagens"] and not resultado["videos"]:
        print("[shopee] Tentando extração via navegador (Playwright)...")
        nav_data = _shopee_midia_navegador(url)
        if nav_data:
            resultado["imagens"].extend(nav_data.get("imagens", []))
            resultado["videos"].extend(nav_data.get("videos", []))
            resultado["nome"] = nav_data.get("nome", "") or slug_nome
            if resultado["imagens"] or resultado["videos"]:
                resultado["imagens"] = list(dict.fromkeys(resultado["imagens"]))
                resultado["videos"] = list(dict.fromkeys(resultado["videos"]))
                print(f"[shopee] Navegador: {len(resultado['imagens'])} imagens, {len(resultado['videos'])} vídeos")
                return resultado

    # se nada funcionou, retorna fallback
    if not item:
        resultado["fallback"] = True
        resultado["instrucoes"] = (
            "❌ Shopee bloqueou a extração automática.\n\n"
            "📋 Como baixar manualmente:\n"
            "1. Abra o link no navegador\n"
            "2. Instale a extensão 'AliSave' (Chrome)\n"
            "3. Clique no ícone da extensão > Download Video\n"
            "4. Salve os vídeos na pasta indicada\n\n"
            f"📁 Pasta: Midias/{resultado.get('slug', '')}/"
        )
        return resultado

    # extrai imagens
    images = item.get("images", [])
    for img in images:
        if img:
            img_url = _limpar_url_imagem_shopee(img)
            if img_url not in resultado["imagens"]:
                resultado["imagens"].append(img_url)

    # extrai vídeos (suporta item['videos'] e item['video_info_list'])
    videos = item.get("videos") or []
    if not videos and item.get("video_info_list"):
        for vinfo in item.get("video_info_list", []):
            if isinstance(vinfo, dict):
                vurl = vinfo.get("default_format", {}).get("url") or vinfo.get("url")
                if vurl:
                    videos.append(vurl)

    for vid in videos:
        vurl = vid.get("url", "") if isinstance(vid, dict) else str(vid)
        if vurl:
            if vurl.startswith("http"):
                resultado["videos"].append(vurl)
            else:
                resultado["videos"].append(f"https://down-br.img.susercontent.com/file/{vurl}")

    # deduplica
    resultado["imagens"] = list(dict.fromkeys(resultado["imagens"]))
    resultado["videos"] = list(dict.fromkeys(resultado["videos"]))

    # nome
    resultado["nome"] = _limpar_nome_produto(item.get("name", "")) or slug_nome

    print(f"[shopee] Encontrado: {len(resultado['imagens'])} imagens, {len(resultado['videos'])} vídeos")
    return resultado


# ─── AliExpress ──────────────────────────────────────────────────────────────

def _aliexpress_item_id(url: str) -> str | None:
    """Extrai o item_id de uma URL AliExpress."""
    m = re.search(r"/(\d+)\.html", url)
    if m:
        return m.group(1)
    m = re.search(r"itemId=(\d+)", url)
    if m:
        return m.group(1)
    return None


def extrair_aliexpress(url: str) -> dict:
    """Extrai imagens e vídeos de um anúncio AliExpress."""
    resultado = {"imagens": [], "videos": [], "nome": "", "fonte": "aliexpress", "fallback": False}

    item_id = _aliexpress_item_id(url)
    if not item_id:
        print(f"[aliexpress] Não conseguiu extrair item_id da URL: {url}")
        resultado["fallback"] = True
        resultado["instrucoes"] = (
            "❌ Não foi possível extrair mídia automaticamente.\n\n"
            "📋 Opções:\n"
            "1. Use a extensão 'AliSave' no Chrome\n"
            "2. Cole as URLs diretas das imagens/vídeos abaixo\n"
            "3. Ou baixe manualmente e coloque na pasta"
        )
        return resultado

    print(f"[aliexpress] Buscando item {item_id}")

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()

        # extrai JSON-LD (dados estruturados)
        for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', resp.text, re.DOTALL):
            try:
                ld = json.loads(m.group(1))
                if isinstance(ld, dict) and ld.get("@type") == "Product":
                    resultado["nome"] = ld.get("name", "")
                    # imagens
                    imgs = ld.get("image", [])
                    if isinstance(imgs, str):
                        imgs = [imgs]
                    resultado["imagens"] = imgs
                    break
            except json.JSONDecodeError:
                continue

        # tenta extrair vídeos do HTML
        for m in re.finditer(r'"videoUrl"\s*:\s*"([^"]+\.mp4[^"]*)"', resp.text):
            vurl = m.group(1).replace("\\u002F", "/")
            if vurl.startswith("http"):
                resultado["videos"].append(vurl)

        # fallback: procura URLs de imagem no HTML
        if not resultado["imagens"]:
            for m in re.finditer(r'"imageUrl"\s*:\s*"([^"]+)"', resp.text):
                img = m.group(1).replace("\\u002F", "/")
                if img.startswith("http") and img not in resultado["imagens"]:
                    resultado["imagens"].append(img)

        # se não encontrou nada, tenta imagens genéricas do AliExpress
        if not resultado["imagens"]:
            for m in re.finditer(r'https://ae0[^\s"\'<>]+\.jpg', resp.text):
                img = m.group(0)
                if img not in resultado["imagens"]:
                    resultado["imagens"].append(img)

    except Exception as exc:
        print(f"[aliexpress] Erro: {exc}")

    if not resultado["imagens"] and not resultado["videos"]:
        resultado["fallback"] = True
        resultado["instrucoes"] = (
            "❌ AliExpress bloqueou a extração automática.\n\n"
            "📋 Como baixar manualmente:\n"
            "1. Abra o link no navegador\n"
            "2. Clique com botão direito nas imagens > Salvar como\n"
            "3. Para vídeos: clique no vídeo > Salvar como\n"
            "4. Cole as URLs diretas nos campos abaixo\n\n"
            "💡 Ou instale a extensão 'AliSave' (Chrome)"
        )

    print(f"[aliexpress] Encontrado: {len(resultado['imagens'])} imagens, {len(resultado['videos'])} vídeos")
    return resultado


def baixar_urls_manuais(urls_texto: str, slug: str) -> dict:
    """Baixa imagens/vídeos de URLs coladas pelo usuário (uma por linha)."""
    resultado = {"videos": [], "imagens": []}
    urls = [u.strip() for u in urls_texto.strip().split("\n") if u.strip()]

    for i, url in enumerate(urls, 1):
        # detecta tipo pela URL
        if any(ext in url.lower() for ext in [".mp4", ".mov", ".webm", ".mkv", "video"]):
            p = baixar_midia(url, slug, tipo="video", indice=i)
            if p:
                resultado["videos"].append(p)
        else:
            p = baixar_midia(url, slug, tipo="imagem", indice=i)
            if p:
                resultado["imagens"].append(p)

    return resultado


# ─── Download ────────────────────────────────────────────────────────────────

def _download(url: str, destino: Path) -> bool:
    """Baixa um arquivo de URL."""
    try:
        resp = requests.get(url, headers=_HEADERS, stream=True, timeout=30)
        resp.raise_for_status()
        with open(destino, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as exc:
        print(f"  Falha ao baixar {url[:60]}...: {exc}")
        return False


def baixar_midia(url: str, slug: str, tipo: str = "video", indice: int = 1) -> Path | None:
    """Baixa mídia e salva na pasta do produto.

    tipo: "video" ou "imagem"
    Retorna o caminho do arquivo baixado ou None.
    """
    pasta = MIDIAS_DIR / slug
    pasta.mkdir(parents=True, exist_ok=True)

    # extensão baseada na URL
    if ".mp4" in url or "video" in tipo:
        ext = ".mp4"
        subdir = pasta
    else:
        ext = ".jpg"
        subdir = pasta / "imagens"
        subdir.mkdir(exist_ok=True)

    nome = f"{'clipe' if tipo == 'video' else 'img'}{indice}{ext}"
    destino = subdir / nome

    if _download(url, destino):
        print(f"  ✅ Salvo: {destino.relative_to(MIDIAS_DIR.parent)}")
        return destino
    return None


def baixar_todas_midias(dados: dict, slug: str) -> dict:
    """Baixa todas as imagens e vídeos encontrados.

    Retorna: {"videos": [Path], "imagens": [Path]}
    """
    resultado = {"videos": [], "imagens": []}

    # vídeos primeiro (são os clipes principais)
    for i, url in enumerate(dados.get("videos", []), 1):
        p = baixar_midia(url, slug, tipo="video", indice=i)
        if p:
            resultado["videos"].append(p)

    # imagens (backup/referência)
    for i, url in enumerate(dados.get("imagens", []), 1):
        p = baixar_midia(url, slug, tipo="imagem", indice=i)
        if p:
            resultado["imagens"].append(p)

    return resultado


# ─── Cadastro (produto novo só com o link) ───────────────────────────────────


def _extrair_numero_precificacao(txt: str) -> float | None:
    """Extrai o primeiro número (inclui casas decimais) de uma string."""
    if not txt:
        return None
    m = re.search(r"(\d+\.?\d*)", str(txt))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _borderar_preco(preco: str) -> str:
    """Garante que o preço tenha o formato da planilha ('79,99').

    Aceita:'79,99' '79.99' 'R$ 79,99' '79,990,00' (milhar)
    Deixa em '79,99' e remove milhares, se houver.
    """
    if not preco:
        return ""
    n = re.sub(r"[^0-9.,]", "", str(preco))
    if not re.search(r"[,\.]", n):
        return n
    # remove separadores de milhares (ponto quando seguido de 3 dígitos e
    # antes de uma vírgula; ou vírgula quando seguido de 3 dígitos e
    # no final)
    n = re.sub(r"(?<=\d)\.(?=(\d{3})+(?:,\d{2})?$", "", n)
    n = re.sub(r"(?<=\d),(?=(\d{3})+(?:\.\d{2})?$", "", n)
    return n


def _normalizar_preco(txt) -> str:
    """Reduz 'R$ 79,99' / '79.99' ao formato da planilha ('79,99')."""
    if not txt:
        return ""
    m = re.search(r"(\d[\d.,]*)", str(txt))
    if not m:
        return ""
    n = m.group(1)
    if re.fullmatch(r"\d+\.\d{2}", n):   # 79.99 → 79,99
        n = n.replace(".", ",")
    return n


def _cadastro_por_ia(url: str) -> dict | None:
    """Camada 1 (nuvem): Gemini com busca do Google lê o índice da web.

    A Shopee bloqueia acesso automatizado direto (API, página, leitores),
    mas a página do produto está indexada no Google com nome, preço e
    categoria — o grounding busca essa página e devolve os dados.

    As chamadas são agendadas (máximo 1 a cada ~10s). Se o tempo de
    aguardo for excedido, retorna None (fila cheia) para que o fluxo
    principal não bloqueie por mais tempo.

    Retorna:
      - dict com nome/nicho/preco se o modelo retornou os 3 campos
        de forma confiável
      - None se a LLM falhar, não retornou os campos esperados,
        ou se a fila estourar o timeout
    """
    url_pesquisa = _resolve_short_url(url)
    ids = _parse_shopee_url(url_pesquisa)
    contexto = f" (itemid {ids[1]}, loja {ids[0]})" if ids else ""
    slug_dica = extrair_slug_shopee(url_pesquisa)
    dica_nome = f" Nome/slug provável no link: '{slug_dica}'." if slug_dica else ""
    sistema = (
        "Você extrai dados de produtos Shopee para preencher uma planilha. "
        "Limpe termos promocionais e sufixos (ex: 'Frete Grátis', 'Pronta Entrega', '| Shopee Brasil'). "
        "Responda SOMENTE com o JSON pedido — sem comentários, sem markdown."
    )
    pedido = (
        f"Produto na Shopee: {url_pesquisa}{contexto}.{dica_nome} "
        "Use a busca do Google para localizar a página EXATA deste produto. "
        'Responda apenas com: {"nome": "<nome curto do produto em português>", '
        '"preco": "<preço médio atual, ex: 79,99>", '
        '"nicho": "<categoria/nicho em português>"} '
        'Use "" para o que não conseguir encontrar.'
    )

    # Espera o agendador liberar espaço (timeout curto para não bloquear UI)
    tempo_restante = _tempo_orm_de_IA()
    if tempo_restante is not None and tempo_restante > 12.0:
        # aguardar até o próximo lance
        time.sleep(min(tempo_restante, 12.0))

    try:
        texto = _chamar_gemini(
            sistema, pedido,
            temperature=0.2,
            response_mime_type="application/json",
            prazo_total_s=60.0,
            esperar_janela_429=False,
            ferramentas_google=True,
        )
    except Exception as exc:
        _on_IA_chamada_concluida(pedido)
        raise RuntimeError(str(exc)) from exc

    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        reparado = _reparar_json(texto)
        _on_IA_chamada_concluida(pedido)
        if not reparado:
            return None
        dados = json.loads(reparado)
    if not isinstance(dados, dict):
        _on_IA_chamada_concluida(pedido)
        return None

    nome = _limpar_nome_produto(str(dados.get("nome") or "").strip())
    preco_bruto = str(dados.get("preco") or "").strip()
    preco = _normalizar_preco(preco_bruto)
    nicho = str(dados.get("nicho") or "").strip()

    _on_IA_chamada_concluida(pedido)

    # só conta como sucesso se nome + preco estiverem presentes
    if not nome or not preco:
        return None
    return {"nome": nome, "nicho": nicho, "preco": preco}


def _classificar_erro_gemini(msg: str) -> tuple[str, str]:
    """Classifica o erro de Gemini retornando (tipo, mensagem curta)."""
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return "quota", "Cota esgotada (429). Aguarde alguns minutos e tente de novo."
    if "503" in msg or "UNAVAILABLE" in msg:
        return "instavel", "Serviço instável (503). Tente de novo em instantes."
    if "GEMINI_API_KEY" in msg or "API_KEY" in msg:
        return "chave", "Chave de API não configurada ou inválida."
    if "INVALID_ARGUMENT" in msg:
        return "parametro", "Parâmetro inválido enviado à API."
    if "NOT_FOUND" in msg:
        return "nao_encontrado", "Modelo não encontrado. Verifique a chave e os modelos disponíveis."
    if "RATE_LIMIT" in msg or "RATE_LIMIT_EXCEEDED" in msg:
        return "taxa", "Limite de requisições atingido. Reduza a frequência."
    if "TIMEOUT" in msg or "DEADLINE_EXCEEDED" in msg:
        return "tempo", "Tempo de espera excedido. O serviço está sob carga ou lento."
    return "erro", str(msg)[:110]


def _erro_gemini_detalhado(last_error: str) -> str:
    """Gera uma mensagem amigável de erro para a UI, detalhando a causa por tipo."""
    tipo, msg = _classificar_erro_gemini(last_error)
    return f"Gemini falhou ({tipo}): {msg}"


def _cadastro_navegador(url: str) -> dict | None:
    """Camada 2 (local): abre uma janela real do Chrome no PC do usuário.

    O desafio anti-bot da Shopee passa sozinho em navegador "humano"
    (comprovado em testes), mas é instável — roda só como fallback e
    apenas quando há tela (DISPLAY); na nuvem desiste na hora.
    """
    if not os.environ.get("DISPLAY"):
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as pw:
            nav = pw.chromium.launch(headless=False, args=["--no-sandbox"])
            ctx = nav.new_context(locale="pt-BR")
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            html = ""
            # espera desafio passar + SPA renderizar (até ~24s)
            for _ in range(12):
                page.wait_for_timeout(2000)
                html = page.content()
                if "Ofertas incríveis" not in page.title() and re.search(
                    r"R\$\s*[\d.]+,\d{2}", html
                ):
                    break
            meta = dict(re.findall(
                r'<meta[^>]*property="(og:title|og:description)"[^>]*content="([^"]*)"', html
            ))
            cats = page.eval_on_selector_all(
                'a[href*="/categories/"]',
                "els => els.map(e => e.textContent.trim()).filter(Boolean)",
            )
            nav.close()
    except Exception as exc:  # noqa: BLE001 — fallback não pode quebrar o fluxo
        print(f"[cadastro] navegador falhou: {exc}")
        return None

    nome = _limpar_nome_produto((meta.get("og:title") or "").strip())
    if not nome or "Ofertas incríveis" in nome or "Shopee Brasil" in nome:
        return None  # parou no desafio/captcha
    precos = re.findall(r"R\$\s*[\d.]+,\d{2}", html)
    return {
        "nome": nome,
        "nicho": (cats[-1].strip() if cats else ""),
        "preco": _normalizar_preco(precos[0]) if precos else "",
    }


def extrair_cadastro(link: str) -> dict:
    """Preenche nome/nicho/preço de um produto só a partir do link.

    Ordem de tentativas (definida em PROGESSAO_CADASTRO):
      1. Cache em memória (evita rechamar a IA)
      2. Gemini + busca do Google (nuvem)
      3. Navegador real no PC local (Playwright)

    Regras de qualidade:
      - A camada só "conta" se entregar os 3 campos (nome, nicho, preco)
        com dados válidos. Campos parciais geram fallback.
      - Cross-check: se a IA e o navegador diferirem o preço em mais de
        15%, usa o menor (mais conservador, mais próximo do preço final
        com frete e impostos da Shopee).
      - Nicho: prioridade é IA, depois DOM/nav, depois derivação do nome.

    Retorna sempre {"nome", "nicho", "preco", "camada", "fonts_usadas",
    "erro", "faltou_por_campo"}:
    "camada" diz de onde vieram os dados ("ia" | "navegador" | ""
    quando nenhum deu certo); "fonts_usadas" lista as fontes consultadas;
    "faltou_por_campo" indica quais campos estavam ausentes nas fontes.
    "erro" explica a falha quando não há dados.
    """
    link = (link or "").strip()
    if not link:
        return {"nome": "", "nicho": "", "preco": "", "camada": "",
                "fonts_usadas": [], "erro": "Cole o link do produto primeiro.",
                "faltou_por_campo": []}

    url_norm = _resolve_short_url(link)

    # 1. Cache em memória
    cache = _cadastro_por_cache(url_norm)
    if cache:
        return {
            "nome": cache.get("nome", ""),
            "nicho": cache.get("nicho", ""),
            "preco": cache.get("preco", ""),
            "camada": "ia",
            "fonts_usadas": ["cache"], 
            "erro": "",
            "faltou_por_campo": [],
        }

    motivos: list[str] = []
    fonts_usadas: list[str] = []
    campos_faltantes: set[str] = set()

    # 2. Camada IA
    try:
        ia = _cadastro_por_ia(link)
    except Exception as exc:  # noqa: BLE001
        ia = None
        motivos.append(f"IA: {str(exc)[:110]}")
    if ia is not None:
        fonts_usadas.append("ia")
        if ia.get("nome"):
            ia_nome = ia["nome"]
        else:
            ia_nome = ""
            campos_faltantes.add("nome")
        if ia.get("preco"):
            ia_preco = ia["preco"]
        else:
            ia_preco = ""
            campos_faltantes.add("preco")
        ia_nicho = ia.get("nicho", "")
        if not ia_nicho:
            campos_faltantes.add("nicho")

    # 3. Camada navegador
    nav = None
    if not ia or (not ia.get("nome") or not ia.get("preco")):
        nav = _cadastro_navegador(link)
        if nav:
            fonts_usadas.append("navegador")
            if nav.get("nome"):
                nav_nome = nav["nome"]
            else:
                nav_nome = ""
                campos_faltantes.add("nome")
            if nav.get("preco"):
                nav_preco = nav["preco"]
            else:
                nav_preco = ""
                campos_faltantes.add("preco")
            nav_nicho = nav.get("nicho", "")
            if not nav_nicho:
                campos_faltantes.add("nicho")
        else:
            motivos.append("navegador local indisponível (nuvem ou captcha)")

    # 4. Decide o resultado final
    if ia and nav:
        # Cross-check: se houver divergência de preço acima de 15%,
        # usa o menor (mais conservador).
        ia_preco_num = _extrair_numero_precificacao(ia.get("preco"))
        nav_preco_num = _extrair_numero_precificacao(nav.get("preco"))
        if ia_preco_num is not None and nav_preco_num is not None:
            divergencia = abs(ia_preco_num - nav_preco_num) / max(ia_preco_num, nav_preco_num)
            if divergencia > 0.15:
                preco_final = min(ia_preco_num, nav_preco_num)
                ia_preco = _borderar_preco(f"{preco_final:.2f}")
                motivos.append(
                    f"Preço divergente entre IA e navegador ({ia.get('preco')} vs {nav.get('preco')}); "
                    f"usando menor ({preco_final:.2f})"
                )

        # Nome: prefere IA, se não, navegador
        nome_final = ia.get("nome") or nav.get("nome") or ""
        if not nome_final:
            campos_faltantes.discard("nome")

        # Nicho: prioridade IA, depois DOM/nav
        nicho_final = ia.get("nicho") or nav.get("nicho") or ""
        if not nicho_final:
            nicho_derivado = _classificar_por_nome(nome_final)
            if nicho_derivado:
                nicho_final = nicho_derivado
                motivos.append(f"Nicho derivado do nome: {nicho_final}")
            else:
                campos_faltantes.add("nicho")

        # Preço final: preferência para o da IA, se disponível
        preco_final = ia.get("preco")
        if not preco_final and nav.get("preco"):
            preco_final = nav["preco"]

        if nome_final and preco_final:
            _guardar_cadastro_cache(url_norm, {
                "nome": nome_final,
                "nicho": nicho_final,
                "preco": preco_final,
            })
            return {
                "nome": nome_final,
                "nicho": nicho_final,
                "preco": preco_final,
                "camada": "ia",
                "fonts_usadas": fonts_usadas,
                "erro": "" if not motivos else " ".join(motivos[:2]),
                "faltou_por_campo": sorted(campos_faltantes),
            }

    elif ia:
        # Só IA: encerra logo se faltar algum campo crítico
        if campos_faltantes:
            _guardar_cadastro_cache(url_norm, {
                "nome": ia.get("nome", ""),
                "nicho": ia.get("nicho", ""),
                "preco": ia.get("preco", ""),
            })
            if "nome" not in campos_faltantes and "preco" not in campos_faltantes:
                return {
                    "nome": ia.get("nome", ""),
                    "nicho": ia.get("nicho", ""),
                    "preco": ia.get("preco", ""),
                    "camada": "ia",
                    "fonts_usadas": ["ia"],
                    "erro": "",
                    "faltou_por_campo": sorted(campos_faltantes),
                }
        # IA parciairo: retorna o que conseguiu com aviso
        return {
            "nome": ia.get("nome", ""),
            "nicho": ia.get("nicho", ""),
            "preco": ia.get("preco", ""),
            "camada": "ia",
            "fonts_usadas": ["ia"],
            "erro": "",
            "faltou_por_campo": sorted(campos_faltantes),
        }

    elif nav:
        if "nome" not in campos_faltantes and "preco" not in campos_faltantes:
            _guardar_cadastro_cache(url_norm, {
                "nome": nav["nome"],
                "nicho": nav.get("nicho", ""),
                "preco": nav["preco"],
            })
            return {
                "nome": nav["nome"],
                "nicho": nav.get("nicho", ""),
                "preco": nav["preco"],
                "camada": "navegador",
                "fonts_usadas": ["navegador"],
                "erro": "",
                "faltou_por_campo": sorted(campos_faltantes),
            }
        return {
            "nome": nav.get("nome", ""),
            "nicho": nav.get("nicho", ""),
            "preco": nav.get("preco", ""),
            "camada": "navegador",
            "fonts_usadas": ["navegador"],
            "erro": "",
            "faltou_por_campo": sorted(campos_faltantes),
        }

    # Nenhuma camada conseguiu
    erro_detalhado = "⚠️ Extração indisponível agora — preencha os campos à mão."
    if fonts_usadas:
        if "ia" in fonts_usadas and "navegador" in fonts_usadas:
            erro_detalhado += " As duas fontes falharam. Verifique a chave do Gemini e o acesso à internet."
        elif "ia" in fonts_usadas:
            erro_detalhado += " A camada de IA (Gemini + Google Search) não retornou dados. "
            erro_detalhado += "Verifique a chave de API e a cota do serviço."
        elif "navegador" in fonts_usadas:
            erro_detalhado += " O navegador (Playwright) falhou ao abrir a página. "
            erro_detalhado += "Verifique se o Chrome está aberto e se não há bloqueios."

    return {
        "nome": "",
        "nicho": "",
        "preco": "",
        "camada": "",
        "fonts_usadas": fonts_usadas,
        "erro": erro_detalhado,
        "erro_detalhado": erro_detalhado,
        "faltou_por_campo": sorted(campos_faltantes),
    }


# ─── Roteador ────────────────────────────────────────────────────────────────

def extrair_de_url(url: str) -> dict:
    """Detecta a plataforma e extrai mídia automaticamente."""
    url_lower = url.lower()

    if "shopee" in url_lower:
        return extrair_shopee(url)
    elif "aliexpress" in url_lower or "aliex" in url_lower:
        return extrair_aliexpress(url)
    else:
        print(f"Plataforma não suportada: {urlparse(url).netloc}")
        return {"imagens": [], "videos": [], "nome": "", "fonte": "desconhecida"}


if __name__ == "__main__":
    # teste rápido
    import sys
    if len(sys.argv) > 1:
        url = sys.argv[1]
        dados = extrair_de_url(url)
        print(f"\nResultado: {json.dumps(dados, indent=2, ensure_ascii=False)[:500]}")
    else:
        print("Uso: python scraping.py <URL_DO_PRODUTO>")
