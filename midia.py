"""
midia.py — Gerenciamento de mídia (B-Roll de fornecedores).

Verifica clipes por produto, gera links de busca,
valida formato (9:16, mp4) e lista o que falta.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from config import BASE_DIR, MIDIAS_DIR


@dataclass
class InfoClip:
    """Info de um clipe de vídeo."""
    arquivo: str
    duracao: float  # segundos
    largura: int
    altura: int
    fps: float
    orientacao: str  # "vertical" (9:16) ou "horizontal" (16:9) ou "quadrado"

    @property
    def ok(self) -> bool:
        """True se o clipe é vertical (9:16) e tem pelo menos 2s."""
        return self.orientacao == "vertical" and self.duracao >= 2.0


def _ffprobe_info(path: Path) -> InfoClip | None:
    """Lê informações do vídeo via ffprobe."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "stream=width,height,r_frame_rate,duration",
                "-show_entries", "format=duration",
                "-of", "json",
                str(path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return None

        import json
        data = json.loads(r.stdout)

        # stream de vídeo
        vs = None
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                vs = s
                break
        if not vs:
            return None

        w = int(vs.get("width", 0))
        h = int(vs.get("height", 0))

        # duração
        dur = float(data.get("format", {}).get("duration", 0))
        if dur == 0:
            dur = float(vs.get("duration", 0))

        # fps
        fps_str = vs.get("r_frame_rate", "30/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) > 0 else 30.0
        else:
            fps = float(fps_str)

        # orientação
        if h > w * 1.2:
            orient = "vertical"
        elif w > h * 1.2:
            orient = "horizontal"
        else:
            orient = "quadrado"

        return InfoClip(
            arquivo=path.name,
            duracao=round(dur, 2),
            largura=w,
            altura=h,
            fps=round(fps, 1),
            orientacao=orient,
        )
    except Exception:
        return None


def listar_clipes(slug: str) -> list[InfoClip]:
    """Lista clipes na pasta Midias/#NN_Slug/ com informações detalhadas."""
    pasta = MIDIAS_DIR / slug
    if not pasta.exists():
        return []

    exts = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
    clipes = []
    for f in sorted(pasta.iterdir()):
        if f.suffix.lower() in exts:
            info = _ffprobe_info(f)
            if info:
                clipes.append(info)
    return clipes


def resumo_midia(slug: str) -> dict:
    """Resumo da mídia de um produto."""
    clipes = listar_clipes(slug)
    pasta = MIDIAS_DIR / slug
    existe_pasta = pasta.exists()

    total_dur = sum(c.duracao for c in clipes)
    verticais = sum(1 for c in clipes if c.orientacao == "vertical")
    horizontais = sum(1 for c in clipes if c.orientacao == "horizontal")

    return {
        "slug": slug,
        "pasta": str(pasta),
        "existe_pasta": existe_pasta,
        "total_clipes": len(clipes),
        "verticais": verticais,
        "horizontais": horizontais,
        "duracao_total": round(total_dur, 1),
        "clipes": clipes,
        "pronto": len(clipes) >= 3 and verticais >= 2,  # precisa de pelo menos 2 verticais
    }


def gerar_links_busca(nome_produto: str) -> dict[str, str]:
    """Gera URLs de busca para encontrar B-Roll do produto."""
    termo_en = nome_produto  # em inglês (ideal)
    termo_br = nome_produto

    return {
        "Shopee": f"https://shopee.com.br/search?keyword={termo_br.replace(' ', '%20')}",
        "AliExpress": f"https://pt.aliexpress.com/w/wholesale-{termo_en.replace(' ', '-')}.html",
        "TikTok": f"https://www.tiktok.com/search?q={termo_en.replace(' ', '%20')}&t=1",
        "Pinterest": f"https://www.pinterest.com/search/pins/?q={termo_en.replace(' ', '%20')}",
        "YouTube": f"https://www.youtube.com/results?search_query={termo_en.replace(' ', '+')}+demo",
        "Douyin (Search)": f"https://www.douyin.com/search/{termo_en.replace(' ', '%20')}",
    }


def _slugificar(nome: str) -> str:
    """Gera slug do nome do produto (sem acentos, sem espaços)."""
    import unicodedata
    txt = unicodedata.normalize("NFKD", nome)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = re.sub(r"[^A-Za-z0-9]+", "", txt)
    return txt[:30] or "Produto"


def criar_pasta_midia(slug: str) -> Path:
    """Cria a pasta Midias/#NN_Slug/ se não existir."""
    pasta = MIDIAS_DIR / slug
    pasta.mkdir(parents=True, exist_ok=True)
    # cria um README com instruções
    readme = pasta / "LEIA_ME.txt"
    if not readme.exists():
        readme.write_text(
            f"Pasta de clipes do produto: {slug}\n\n"
            "Coloque aqui os vídeos brutos do produto:\n"
            "  - clipe1.mp4\n"
            "  - clipe2.mp4\n"
            "  - clipe3.mp4\n"
            "  etc.\n\n"
            "Formato ideal: vertical (9:16, 1080x1920)\n"
            "Mínimo: 3 clipes, pelo menos 2 verticais\n",
            encoding="utf-8",
        )
    return pasta
