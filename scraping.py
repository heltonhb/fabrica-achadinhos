"""
scraping.py — Extração automática de mídia de páginas de produto.

Suporta: Shopee, AliExpress
Extrai: imagens (JPEG/PNG) e vídeos (MP4) do anúncio.
Salva em: Midias/#NN_Slug/ (clipes) e Midias/#NN_Slug/imagens/
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests

from config import MIDIAS_DIR

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
    """Resolve links curtos (s.shopee.com.br) para a URL completa."""
    if "s.shopee.com.br" in url or "shopee.link" in url:
        try:
            resp = requests.head(url, allow_redirects=True, timeout=10, headers=_HEADERS)
            return resp.url
        except Exception:
            pass
    return url


def _parse_shopee_url(url: str) -> tuple[str, str] | None:
    """Extrai shop_id e item_id de uma URL Shopee.
    Aceita formatos:
      - https://shopee.com.br/product-name-i.shopid.itemid
      - https://shopee.com.br/shopname/shopid/itemid  (link de compartilhamento)
      - https://s.shopee.com.br/...  (link curto)
    Retorna (shop_id, item_id) ou None.
    """
    # resolve link curto primeiro
    url = _resolve_short_url(url)

    # formato 1: -i.shopid.itemid
    m = re.search(r"-i\.(\d+)\.(\d+)", url)
    if m:
        return m.group(1), m.group(2)

    # formato 2: -i shopid itemid (com espaço ou .)
    m = re.search(r"-i[\s.]+(\d+)[\s.]+(\d+)", url)
    if m:
        return m.group(1), m.group(2)

    # formato 3: query params
    parsed = urlparse(url)
    m = re.search(r"i=(\d+)\.(\d+)", parsed.query)
    if m:
        return m.group(1), m.group(2)

    # formato 4: /shopname/shopid/itemid (link de compartilhamento)
    m = re.search(r"/([^/]+)/(\d+)/(\d+)", parsed.path)
    if m:
        return m.group(2), m.group(3)

    return None


def _shopee_api(shop_id: str, item_id: str) -> dict | None:
    """Busca dados do produto via API interna da Shopee."""
    url = f"https://shopee.com.br/api/v4/item/get?itemid={item_id}&shopid={shop_id}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", {})
    except Exception as exc:
        print(f"[shopee] API falhou: {exc}")
    return None


def _shopee_meta_tags(url: str) -> dict | None:
    """Extrai dados de meta tags OpenGraph (funciona mesmo com anti-bot)."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        resultado = {}

        # og:image
        m = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"', html)
        if m:
            resultado["image"] = m.group(1)

        # og:title
        m = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', html)
        if m:
            resultado["name"] = m.group(1)

        # og:description
        m = re.search(r'<meta[^>]*property="og:description"[^>]*content="([^"]+)"', html)
        if m:
            resultado["description"] = m.group(1)

        # video (se tiver)
        m = re.search(r'<meta[^>]*property="og:video"[^>]*content="([^"]+)"', html)
        if m:
            resultado["video"] = m.group(1)

        # procura todas as imagens cf.shopee.com.br no HTML
        imagens = list(set(re.findall(r'https://cf\.shopee\.com\.br/file/[a-f0-9]+', html)))
        if imagens:
            resultado["images_list"] = imagens[:10]

        return resultado if resultado else None
    except Exception:
        return None


def _shopee_direto(url: str) -> dict | None:
    """Fallback: abre a página e extrai dados do script __INITIAL_STATE__."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        # procura o JSON embutido no HTML
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?})\s*;", resp.text)
        if m:
            data = json.loads(m.group(1))
            # navega até os dados do item
            item = data.get("item", {}).get("itemData", {})
            if item:
                return item
    except Exception:
        pass
    return None


def extrair_shopee(url: str) -> dict:
    """Extrai imagens e vídeos de um anúncio Shopee.

    Retorna: {"imagens": [...], "videos": [...], "nome": str}
    """
    resultado = {"imagens": [], "videos": [], "nome": "", "fonte": "shopee", "fallback": False}

    # resolve link curto
    url = _resolve_short_url(url)

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

    # tenta API primeiro
    item = _shopee_api(shop_id, item_id)

    # fallback: HTML direto
    if not item:
        print("[shopee] API falhou, tentando HTML...")
        item = _shopee_direto(url)

    # fallback: meta tags
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
            resultado["nome"] = meta.get("name", "")
            print(f"[shopee] Meta tags: {len(resultado['imagens'])} imagens, {len(resultado['videos'])} vídeos")
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
            if img.startswith("http"):
                resultado["imagens"].append(img)
            else:
                resultado["imagens"].append(f"https://cf.shopee.com.br/file/{img}")

    # extrai vídeos
    videos = item.get("videos", [])
    for vid in videos:
        vurl = vid.get("url", "") if isinstance(vid, dict) else str(vid)
        if vurl:
            if vurl.startswith("http"):
                resultado["videos"].append(vurl)
            else:
                resultado["videos"].append(f"https://cf.shopee.com.br/file/{vurl}")

    # nome
    resultado["nome"] = item.get("name", "")

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
