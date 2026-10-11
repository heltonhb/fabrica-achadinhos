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

def _obter_url_canonica_shopee(url: str) -> str:
    """Retorna a URL canônica desktop direta da Shopee (/product/{shop_id}/{item_id})."""
    ids = _parse_shopee_url(url)
    if ids and ids[0] and ids[1]:
        return f"https://shopee.com.br/product/{ids[0]}/{ids[1]}"
    return url


def _resolve_short_url(url: str) -> str:
    """Resolve links curtos de afiliado (Shopee, Mercado Livre, Amazon, Magalu, etc.) para a URL completa."""
    if not url:
        return ""
    curtos = (
        "s.shopee.com.br", "shope.ee", "shp.ee", "shopee.link",
        "meli.la", "mercadolivre.com/sec", "mercadolivre.com.br/sec",
        "amzn.to", "a.co", "amzn.eu",
        "magalu.me", "maga.lu",
        "bit.ly", "tinyurl.com", "t.ly", "cutt.ly", "is.gd",
    )
    url_lower = url.lower()
    if any(dom in url_lower for dom in curtos):
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

    url_canonica = _obter_url_canonica_shopee(_resolve_short_url(url))
    try:
        with sync_playwright() as pw:
            nav = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                ],
            )
            ctx = nav.new_context(
                locale="pt-BR",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            page = ctx.new_page()

            videos_coletados = []

            def _on_response(resp):
                r_url = resp.url
                if any(ext in r_url.lower() for ext in (".mp4", "cvf.shopee.com.br", "down-bs-br.img.susercontent.com")):
                    if r_url not in videos_coletados:
                        videos_coletados.append(r_url)

            page.on("response", _on_response)
            page.goto(url_canonica, wait_until="domcontentloaded", timeout=45_000)

            for _ in range(20):
                page.wait_for_timeout(400)
                t = page.title()
                if t and "ofertas incríveis" not in t.lower() and "loading" not in t.lower():
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


def _cadastro_por_ia(
    url: str,
    titulo: str = "",
    descricao: str = "",
    nicho_base: str = "",
) -> dict | None:
    """Camada 1 (nuvem): Gemini lê o índice da web ou refina dados já extraídos.

    Se titulo/descricao já foram obtidos pelo scraper/navegador, o Gemini
    apenas formata o nome comercial limpo, define o nicho comercial perfeito
    e estima o preço (caso não tenha vindo da página), sem precisar de
    grounding externo pesado.

    Se nenhum dado estiver disponível, tenta localizar via busca/link.
    """
    url_pesquisa = _resolve_short_url(url)
    ids = _parse_shopee_url(url_pesquisa)
    contexto = f" (itemid {ids[1]}, loja {ids[0]})" if ids else ""
    slug_dica = extrair_slug_shopee(url_pesquisa)

    sistema = (
        "Você extrai e organiza dados de produtos para um catálogo/planilha de achadinhos. "
        "Limpe termos promocionais e sufixos desnecessários (ex: 'Frete Grátis', 'Pronta Entrega', '| Shopee Brasil'). "
        "Responda SOMENTE com o JSON pedido — sem comentários, sem markdown."
    )

    if titulo:
        pedido = (
            f"Analise estes dados do produto coletados da loja:\n"
            f"Título original: {titulo}\n"
            f"Categoria detectada: {nicho_base}\n"
            f"Descrição: {descricao[:400]}\n"
            f"Link: {url_pesquisa}\n\n"
            'Responda apenas com: {"nome": "<nome curto e atraente do produto em português>", '
            '"preco": "<preço médio atual estimado em formato 00,00, ex: 79,90>", '
            '"nicho": "<categoria/nicho comercial em português>"}'
        )
    else:
        dica_nome = f" Nome/slug provável no link: '{slug_dica}'." if slug_dica else ""
        pedido = (
            f"Produto na Shopee/loja: {url_pesquisa}{contexto}.{dica_nome}\n"
            "Se o link contiver o nome do produto no slug, use-o para extrair os dados.\n"
            "ATENÇÃO: Se você não sabe com certeza qual é o produto real deste link "
            "(ex: link curto ou apenas IDs numéricos sem o nome no link), retorne obrigatoriamente:\n"
            '{"nome": "", "preco": "", "nicho": ""}\n'
            "NUNCA invente ou alucine um produto.\n"
            'Responda apenas com: {"nome": "<nome curto em português>", '
            '"preco": "<preço médio atual>", "nicho": "<nicho em português>"}'
        )

    # Espera o agendador liberar espaço (timeout curto para não bloquear UI)
    tempo_restante = _tempo_orm_de_IA()
    if tempo_restante is not None and tempo_restante > 12.0:
        time.sleep(min(tempo_restante, 12.0))

    try:
        texto = _chamar_gemini(
            sistema, pedido,
            temperature=0.2,
            response_mime_type="application/json",
            prazo_total_s=30.0,
            esperar_janela_429=False,
            ferramentas_google=False,
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

    # só conta como sucesso se pelo menos o nome estiver presente
    if not nome:
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


def _extrair_shopee_navegador(page, url_final: str, nav) -> dict | None:
    """Extrai dados de produto Shopee usando a página canônica e Playwright stealth."""
    url_alvo = _obter_url_canonica_shopee(url_final)
    try:
        page.goto(url_alvo, wait_until="domcontentloaded", timeout=45_000)
    except Exception:
        pass

    html = ""
    title = ""
    for _ in range(25):
        page.wait_for_timeout(350)
        try:
            t = page.title()
            if t and "ofertas incríveis" not in t.lower() and "loading" not in t.lower():
                title = t
                html = page.content()
                break
        except Exception:
            continue

    if not html:
        try:
            html = page.content()
            title = page.title()
        except Exception:
            pass

    meta = dict(re.findall(
        r'<meta[^>]*property="(og:title|og:description|og:image)"[^>]*content="([^"]*)"', html
    ))
    nome = _limpar_nome_produto((meta.get("og:title") or title or "").strip())
    if not nome or "Ofertas incríveis" in nome or "Shopee Brasil" in nome:
        nav.close()
        return None

    # Nicho: Schema.org BreadcrumbList primeiro
    nicho = ""
    for b in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL):
        try:
            obj = json.loads(b)
            if obj.get("@type") == "BreadcrumbList":
                crumbs = [x.get("item", {}).get("name") for x in obj.get("itemListElement", []) if x.get("item", {}).get("name")]
                if len(crumbs) >= 3:
                    nicho = crumbs[2] if len(crumbs) > 3 else crumbs[1]
                elif len(crumbs) >= 2:
                    nicho = crumbs[1]
        except Exception:
            pass

    if not nicho:
        try:
            dom_cats = page.eval_on_selector_all(
                'a[href*="/categories/"], a[href*="/category/"], nav a',
                "els => els.map(e => e.textContent.trim()).filter(Boolean)",
            )
            if dom_cats:
                nicho = dom_cats[-1]
        except Exception:
            pass

    if not nicho:
        nicho = _classificar_por_nome(nome)

    # Preço: HTML regex com centavos obrigatórios (R$ 123,45) para não capturar cupons
    precos = re.findall(r"R\$\s*[\d.]+(?:,\d{2})", html)
    preco = ""
    if precos:
        preco = _normalizar_preco(precos[0])
    if not preco:
        try:
            dom_precos = page.eval_on_selector_all(
                'div[class*="price" i], span[class*="price" i]',
                "els => els.map(e => e.textContent.trim()).filter(Boolean)",
            )
            for dp in dom_precos:
                np = _normalizar_preco(dp)
                if np:
                    preco = np
                    break
        except Exception:
            pass

    nav.close()
    return {
        "nome": nome,
        "nicho": nicho,
        "preco": preco,
        "descricao": meta.get("og:description", ""),
        "imagem": meta.get("og:image", ""),
    }


def _extrair_mercadolivre_navegador(page, url: str, nav) -> dict | None:
    """Extrai dados de produto Mercado Livre via Playwright."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(1000)
        html = page.content()
    except Exception:
        html = ""

    meta = dict(re.findall(r'<meta[^>]*property="(og:title|og:description|og:image)"[^>]*content="([^"]*)"', html))
    nome = meta.get("og:title") or page.title()
    nome = re.sub(r"\s*\|\s*Mercado\s*Livre.*$", "", nome, flags=re.I).strip()

    preco = ""
    ld = _extrair_shopee_ld_json(html)
    if ld and ld.get("preco"):
        preco = ld["preco"]
    if not preco:
        m_preco = re.search(r'class="andes-money-amount__fraction"[^>]*>([\d.]+)<', html)
        if m_preco:
            m_cents = re.search(r'class="andes-money-amount__cents"[^>]*>(\d+)<', html)
            cents = m_cents.group(1) if m_cents else "00"
            preco = f"{m_preco.group(1)},{cents}"
    if not preco:
        precos = re.findall(r"R\$\s*[\d.]+(?:,\d{2})?", html)
        if precos:
            preco = _normalizar_preco(precos[0])

    cats = page.eval_on_selector_all(
        ".andes-breadcrumb__item a, a[class*='breadcrumb']",
        "els => els.map(e => e.textContent.trim()).filter(Boolean)",
    )
    nicho = cats[-1] if cats else _classificar_por_nome(nome)

    nav.close()
    return {
        "nome": nome,
        "nicho": nicho,
        "preco": _normalizar_preco(preco),
        "descricao": meta.get("og:description", ""),
        "imagem": meta.get("og:image", ""),
    }


def _extrair_amazon_navegador(page, url: str, nav) -> dict | None:
    """Extrai dados de produto Amazon via Playwright."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(1000)
        html = page.content()
    except Exception:
        html = ""

    meta = dict(re.findall(r'<meta[^>]*property="(og:title|og:description|og:image)"[^>]*content="([^"]*)"', html))
    nome = meta.get("og:title") or page.title()
    nome = re.sub(r"\s*:\s*Amazon\.com\.br.*$", "", nome, flags=re.I).strip()

    preco = ""
    try:
        m_whole = page.eval_on_selector(".a-price-whole", "el => el.textContent.trim()")
        m_fraction = page.eval_on_selector(".a-price-fraction", "el => el.textContent.trim()")
        if m_whole:
            preco = f"{m_whole},{m_fraction or '00'}"
    except Exception:
        pass
    if not preco:
        precos = re.findall(r"R\$\s*[\d.]+(?:,\d{2})?", html)
        if precos:
            preco = _normalizar_preco(precos[0])

    try:
        cats = page.eval_on_selector_all(
            "#wayfinding-breadcrumbs_container a",
            "els => els.map(e => e.textContent.trim()).filter(Boolean)",
        )
        nicho = cats[-1] if cats else _classificar_por_nome(nome)
    except Exception:
        nicho = _classificar_por_nome(nome)

    nav.close()
    return {
        "nome": nome,
        "nicho": nicho,
        "preco": _normalizar_preco(preco),
        "descricao": meta.get("og:description", ""),
        "imagem": meta.get("og:image", ""),
    }


def _extrair_magalu_navegador(page, url: str, nav) -> dict | None:
    """Extrai dados de produto Magazine Luiza via Playwright."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(1000)
        html = page.content()
    except Exception:
        html = ""

    meta = dict(re.findall(r'<meta[^>]*property="(og:title|og:description|og:image)"[^>]*content="([^"]*)"', html))
    nome = meta.get("og:title") or page.title()
    nome = re.sub(r"\s*-\s*Magazine\s*Luiza.*$", "", nome, flags=re.I).strip()

    ld = _extrair_shopee_ld_json(html)
    preco = ld.get("preco", "") if ld else ""
    if not preco:
        precos = re.findall(r"R\$\s*[\d.]+(?:,\d{2})?", html)
        if precos:
            preco = _normalizar_preco(precos[0])

    try:
        cats = page.eval_on_selector_all(
            "[data-testid='breadcrumb-item'] a, nav a",
            "els => els.map(e => e.textContent.trim()).filter(Boolean)",
        )
        nicho = cats[-1] if cats else _classificar_por_nome(nome)
    except Exception:
        nicho = _classificar_por_nome(nome)

    nav.close()
    return {
        "nome": nome,
        "nicho": nicho,
        "preco": _normalizar_preco(preco),
        "descricao": meta.get("og:description", ""),
        "imagem": meta.get("og:image", ""),
    }


def _cadastro_navegador(url: str) -> dict | None:
    """Camada 2 (local): abre o navegador Playwright stealth para capturar dados da página."""
    if not os.environ.get("DISPLAY"):
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    url_final = _resolve_short_url(url)
    url_lower = url_final.lower()

    try:
        with sync_playwright() as pw:
            nav = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                ],
            )
            ctx = nav.new_context(
                locale="pt-BR",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            page = ctx.new_page()

            if "mercadolivre" in url_lower or "meli." in url_lower:
                return _extrair_mercadolivre_navegador(page, url_final, nav)
            elif "amazon" in url_lower or "amzn" in url_lower:
                return _extrair_amazon_navegador(page, url_final, nav)
            elif "magalu" in url_lower or "magazinevoce" in url_lower:
                return _extrair_magalu_navegador(page, url_final, nav)
            else:
                return _extrair_shopee_navegador(page, url_final, nav)
    except Exception as exc:  # noqa: BLE001 — fallback não pode quebrar o fluxo
        print(f"[cadastro] navegador falhou: {exc}")
        return None


def extrair_cadastro(link: str) -> dict:
    """Preenche nome/nicho/preço de um produto só a partir do link.

    Ordem de tentativas (definida em PROGESSAO_CADASTRO):
      1. Cache em memória (evita rechamar a IA)
      2. Gemini (nuvem)
      3. Navegador stealth no PC local (Playwright)

    Retorna sempre {"nome", "nicho", "preco", "camada", "fonts_usadas",
    "erro", "faltou_por_campo"}.
    """
    link = (link or "").strip()
    if not link:
        return {
            "nome": "", "nicho": "", "preco": "", "camada": "",
            "fonts_usadas": [], "erro": "Cole o link do produto primeiro.",
            "faltou_por_campo": [],
        }

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

    # 2. Camada IA direta
    ia = None
    try:
        ia = _cadastro_por_ia(link)
    except Exception as exc:  # noqa: BLE001
        ia = None
        motivos.append(f"IA: {str(exc)[:110]}")

    if ia and ia.get("nome") and ia.get("preco"):
        fonts_usadas.append("ia")
        _guardar_cadastro_cache(url_norm, ia)
        return {
            "nome": ia["nome"],
            "nicho": ia.get("nicho", ""),
            "preco": ia["preco"],
            "camada": "ia",
            "fonts_usadas": fonts_usadas,
            "erro": "",
            "faltou_por_campo": [],
        }

    # 3. Camada Navegador local stealth
    nav = None
    try:
        nav = _cadastro_navegador(link)
    except Exception as exc:  # noqa: BLE001
        nav = None
        motivos.append(f"Navegador: {str(exc)[:110]}")

    if nav and nav.get("nome"):
        fonts_usadas.append("navegador")
        nome_nav = nav["nome"]
        nicho_nav = nav.get("nicho", "") or _classificar_por_nome(nome_nav)
        preco_nav = nav.get("preco", "")

        # Se faltou preço válido com centavos ou nicho, usa IA para refinar com os dados reais
        preco_incompleto = not preco_nav or ("," not in preco_nav)
        if preco_incompleto or not nicho_nav:
            try:
                ia_refino = _cadastro_por_ia(
                    link,
                    titulo=nome_nav,
                    descricao=nav.get("descricao", ""),
                    nicho_base=nicho_nav,
                )
                if ia_refino:
                    if preco_incompleto and ia_refino.get("preco"):
                        preco_nav = ia_refino["preco"]
                    if not nicho_nav and ia_refino.get("nicho"):
                        nicho_nav = ia_refino["nicho"]
                    fonts_usadas.append("ia")
            except Exception:
                pass

        if not preco_nav:
            campos_faltantes.add("preco")
        if not nicho_nav:
            campos_faltantes.add("nicho")

        res_final = {
            "nome": nome_nav,
            "nicho": nicho_nav,
            "preco": preco_nav,
            "camada": "navegador",
            "fonts_usadas": fonts_usadas,
            "erro": "",
            "faltou_por_campo": sorted(campos_faltantes),
        }
        _guardar_cadastro_cache(url_norm, res_final)
        return res_final

    # Se a IA retornou pelo menos o nome
    if ia and ia.get("nome"):
        if not ia.get("preco"):
            campos_faltantes.add("preco")
        if not ia.get("nicho"):
            campos_faltantes.add("nicho")
        return {
            "nome": ia["nome"],
            "nicho": ia.get("nicho", ""),
            "preco": ia.get("preco", ""),
            "camada": "ia",
            "fonts_usadas": ["ia"],
            "erro": "",
            "faltou_por_campo": sorted(campos_faltantes),
        }

    # Nenhuma camada conseguiu
    erro_detalhado = "⚠️ Extração indisponível agora — preencha os campos à mão."
    return {
        "nome": "",
        "nicho": "",
        "preco": "",
        "camada": "",
        "fonts_usadas": fonts_usadas,
        "erro": erro_detalhado,
        "erro_detalhado": erro_detalhado,
        "faltou_por_campo": ["nome", "nicho", "preco"],
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
