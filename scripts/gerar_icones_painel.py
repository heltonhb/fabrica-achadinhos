"""
scripts/gerar_icones_painel.py — Ícones do PWA do painel (uma vez só; commitados).

Gera public/icon-192.png, public/icon-512.png e public/apple-touch-icon.png
na identidade visual do painel: fundo escuro #131722 com sacola amarela #FFD600.
Requer Pillow. Não faz parte do build/deploy — os PNGs são commitados no repo.
"""

from pathlib import Path

from PIL import Image, ImageDraw

DESTINO = Path(__file__).resolve().parents[1] / "painel" / "public"

# Cores da identidade do painel (public/index.html)
FUNDO = (19, 23, 34, 255)        # #131722 (bg-surface)
AMARELO = (255, 214, 0, 255)     # #FFD600 (primary)
BORDA = (255, 255, 255, 26)      # border sutil


def _arredondar(img: Image.Image, raio: int) -> Image.Image:
    """Máscara de retângulo arredondado (cantos iOS-style)."""
    mascara = Image.new("L", img.size, 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1], raio, fill=255)
    saida = Image.new("RGBA", img.size, (0, 0, 0, 0))
    saida.paste(img, (0, 0), mascara)
    return saida


def _desenhar(tamanho: int) -> Image.Image:
    img = Image.new("RGBA", (tamanho, tamanho), FUNDO)
    d = ImageDraw.Draw(img)
    cx = tamanho / 2

    # Anel sutil de borda (mesma vibe do login-card)
    d.rounded_rectangle(
        [tamanho * 0.02, tamanho * 0.02, tamanho * 0.98, tamanho * 0.98],
        radius=tamanho * 0.22,
        outline=BORDA, width=max(2, tamanho // 128),
    )

    # Sacola de compras minimalista (traço grosso estilo header do painel)
    t = max(6, tamanho // 32)          # espessura do traço
    w = tamanho * 0.52                 # largura do corpo
    h = tamanho * 0.42                 # altura do corpo
    top = cx - h * 0.28                # topo do corpo
    corpo_l = cx - w / 2
    corpo_r = cx + w / 2
    corpo_b = top + h
    raio = t * 1.6

    # Corpo: retângulo arredondado
    d.rounded_rectangle([corpo_l, top, corpo_r, corpo_b], radius=raio, outline=AMARELO, width=t)

    # Alça: arco (semicírculo superior)
    alca_r = w * 0.27
    alca_cx = cx
    alca_cy = top + t // 2
    caixa_alca = [alca_cx - alca_r, alca_cy - alca_r, alca_cx + alca_r, alca_cy + alca_r]
    d.arc(caixa_alca, start=180, end=360, fill=AMARELO, width=t)

    return img


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    for nome, tamanho in [("icon-192", 192), ("icon-512", 512), ("apple-touch-icon", 180)]:
        img = _desenhar(tamanho)
        if nome != "apple-touch-icon":  # PWA: cantos arredondados transparentes
            img = _arredondar(img, raio=int(tamanho * 0.22))
        # apple-touch-icon: quadrado cheio (o iOS arredonda sozinho)
        caminho = DESTINO / f"{nome}.png"
        img.save(caminho, "PNG")
        print(f"gerado {caminho} ({tamanho}x{tamanho})")


if __name__ == "__main__":
    main()
