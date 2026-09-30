"""
visual.py — Geradores de overlay e legendas estilo CapCut.

- badge PNG "ACHADINHO #NN" (PIL, Montserrat Bold)
- PNG de CTA "COMENTA QUERO" com seta (overlay só no fim do vídeo)
- legendas .ass karaoke: janela de ~3 palavras, palavra ativa em amarelo
  com contorno preto (a partir dos timings do edge-tts — sem transcrição)
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import COR_DESTAQUE, FONTS_DIR

AMARELO_ASS = "&H0000D6FF&"   # FFD600 em BGR (formato ASS)
BRANCO_ASS = "&H00FFFFFF&"


def _fonte(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS_DIR / "Montserrat-Bold.ttf"), size)


def _texto_centralizado(d: ImageDraw.ImageDraw, xy, txt, font, fill) -> None:
    d.text(xy, txt, font=font, fill=fill, anchor="mm", stroke_width=0)


def gerar_badge(pasta: Path, numero: str, largura: int = 1080) -> Path:
    """PNG 1080xH transparente com 'ACHADINHO #NN' (retângulo preto arredondado)."""
    h = 170
    img = Image.new("RGBA", (largura, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = largura // 2, h // 2
    caixa_w, caixa_h = 640, 120
    d.rounded_rectangle(
        [cx - caixa_w // 2, cy - caixa_h // 2, cx + caixa_w // 2, cy + caixa_h // 2],
        radius=28, fill=(0, 0, 0, 165),
    )
    # barra amarela de acento à esquerda da caixa
    d.rounded_rectangle(
        [cx - caixa_w // 2 + 18, cy - 46, cx - caixa_w // 2 + 30, cy + 46],
        radius=6, fill=COR_DESTAQUE + (255,),
    )
    f = _fonte(62)
    _texto_centralizado(d, (cx + 15, cy), f"ACHADINHO {numero}", f, (255, 255, 255, 255))
    out = pasta / "badge.png"
    img.save(out)
    return out


def gerar_cta(pasta: Path) -> Path:
    """PNG de CTA com texto 'COMENTA "QUERO"' + seta amarela para a bio."""
    largura, h = 1080, 300
    img = Image.new("RGBA", (largura, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = largura // 2, 110
    caixa_w, caixa_h = 860, 130
    d.rounded_rectangle(
        [cx - caixa_w // 2, cy - caixa_h // 2, cx + caixa_w // 2, cy + caixa_h // 2],
        radius=30, fill=(0, 0, 0, 175),
    )
    f = _fonte(64)
    _texto_centralizado(d, (cx, cy), 'COMENTA "QUERO"', f, (255, 255, 255, 255))
    # seta amarela para baixo (haste + ponta)
    am = COR_DESTAQUE + (255,)
    hx, hy = largura // 2, cy + caixa_h // 2 + 8
    d.rounded_rectangle([hx - 14, hy, hx + 14, hy + 78], radius=12, fill=am)
    d.polygon([(hx - 46, hy + 74), (hx + 46, hy + 74), (hx, hy + 130)], fill=am)
    out = pasta / "cta.png"
    img.save(out)
    return out


def _ts(seg: float) -> str:
    """Segundos -> timestamp ASS 'H:MM:SS.cc'."""
    if seg < 0:
        seg = 0
    m, s = divmod(seg, 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{int(m):02d}:{s:05.2f}"


def gerar_legendas(pasta: Path, palavras: list[dict], path: Path | None = None) -> Path:
    """Gera legendas .ass karaoke a partir dos word boundaries.

    Janelas de até 3 palavras / 1,5s; a palavra ativa fica amarela,
    as demais brancas; contorno preto estilo CapCut.
    """
    eventos: list[str] = []
    i = 0
    n = len(palavras)
    while i < n:
        # monta a janela (chunk): até 3 palavras, no máximo 1,5s
        j = i
        while j + 1 < n and (j + 1 - i) < 3 and palavras[j + 1]["inicio"] - palavras[i]["inicio"] < 1.5:
            j += 1
        janela = palavras[i:j + 1]

        for k, w in enumerate(janela):
            ini = w["inicio"]
            fim = janela[k + 1]["inicio"] if k + 1 < len(janela) else w["fim"]
            fim = max(fim, w["fim"], ini + 0.14)  # evita flicker em palavras curtas
            partes = []
            for m_, ww in enumerate(janela):
                palavra = ww["palavra"]
                if m_ == k:
                    partes.append(f"{{\\c{AMARELO_ASS}}}{palavra}{{\\c{BRANCO_ASS}}}")
                else:
                    partes.append(palavra)
            texto = " ".join(partes)
            eventos.append(f"Dialogue: 0,{_ts(ini)},{_ts(fim)},Kara,,0,0,0,,{texto}")
        i = j + 1

    ass = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Kara,Montserrat,82,{BRANCO_ASS[1:]},{AMARELO_ASS[1:]},&H00000000,&H96000000,-1,0,0,0,100,100,0.6,0,1,6,2,2,60,60,430,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(eventos) + "\n"

    out = path or (pasta / "legendas.ass")
    out.write_text(ass, encoding="utf-8")
    return out


if __name__ == "__main__":
    # autoteste: python visual.py
    demo = Path("/tmp/teste_visual")
    demo.mkdir(exist_ok=True)
    gerar_badge(demo, "#42")
    gerar_cta(demo)
    palavras = json.loads(
        Path("/home/helton/Loja_online/Produtos/_teste_palavras.json").read_text()
    ) if Path("/home/helton/Loja_online/Produtos/_teste_palavras.json").exists() else [
        {"palavra": "Isso", "inicio": 0.1, "fim": 0.36},
        {"palavra": "aqui", "inicio": 0.37, "fim": 0.62},
        {"palavra": "salvou", "inicio": 0.63, "fim": 1.03},
        {"palavra": "minha", "inicio": 1.1, "fim": 1.4},
        {"palavra": "mesa", "inicio": 1.41, "fim": 1.8},
    ]
    gerar_legendas(demo, palavras)
    for f in sorted(demo.iterdir()):
        print(f.name, f.stat().st_size, "bytes")
