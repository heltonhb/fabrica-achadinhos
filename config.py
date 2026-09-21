"""
config.py — Constantes, pastas e utilidades da Fábrica de Achadinhos.

Padrões visuais/sonoros validados (mesma linguagem dos vídeos de achadinhos
que funcionam no Reels/TikTok): 1080x1920, locução no primeiro plano,
trilha a -20 dB com ducking, loudness final -14 LUFS.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path

# ─── Caminhos base ───────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
MIDIAS_DIR = BASE_DIR / "Midias"          # clipes brutos baixados manualmente
PRODUTOS_DIR = BASE_DIR / "Produtos"      # roteiros, vozes, legendas, renders
RENDERS_DIR = BASE_DIR / "renders"        # vídeos finais prontos para postar
FONTS_DIR = BASE_DIR / "fonts"
CSV_PATH = BASE_DIR / "achados.csv"
ENV_PATH = BASE_DIR / ".env"

# ─── Formato do vídeo ───────────────────────────────────────────────────────
W, H = 1080, 1920
FPS = 30
DURACAO_ALVO = 20.0          # segundos (~20s padrão Reels de achadinho)
CLIPES_POR_VIDEO = 5         # clipes de ~4s cada (com margem para cortes)
XFADE = 0.25                 # transição entre clipes (validada: rápida/suave)

# ─── Áudio ──────────────────────────────────────────────────────────────────
VOZ_PADRAO = "pt-BR-AntonioNeural"
VOZ_RATE = "+8%"              # locução levemente acelerada (padrão UGC)
BGM_VOLUME = 0.20             # trilha a ~-20 dB sob a voz (ducking)
LUFS_ALVO = -14.0             # padrão Instagram/Reels

# ─── Visual (estilo CapCut: barra "Achadinho #NN" + seta CTA) ────────────────
COR_DESTAQUE = (255, 214, 0)        # amarelo destaque
COR_TEXTO = (255, 255, 255)         # branco
COR_CONTORNO = (0, 0, 0)           # preto (contorno legendas)
COR_BADGE_BG = (0, 0, 0)           # fundo do badge (semi-transparente no PNG)

# ─── Estados do fluxo (coluna Status da planilha) ───────────────────────────
ESTADOS = ["Ideia", "Roteiro Pronto", "Mídias Baixadas", "Editado", "Postado"]

# ─── Colunas da planilha (achados.csv / Sheets) ─────────────────────────────
COLUNAS = [
    "ID", "Status", "Data Postagem", "Nome do Produto", "Nicho",
    "Preco Medio (R$)", "Comissao Est (R$)", "Link Afiliado Shopee",
    "Link Vitrine (Bio)", "Pasta Midias", "Roteiro / Gancho", "Post Agendado",
]


@dataclass
class Produto:
    """Um achadinho da planilha."""
    id: str
    status: str = "Ideia"
    data_postagem: str = ""
    nome: str = ""
    nicho: str = ""
    preco: str = ""
    comissao: str = ""
    link_afiliado: str = ""
    link_vitrine: str = ""
    pasta_midias: str = ""
    gancho: str = ""
    post_agendado: str = "Nao"

    # preenchidos pelo pipeline (não estão no CSV)
    roteiro: dict = field(default_factory=dict)

    @property
    def slug(self) -> str:
        """Nome da pasta do produto: #37_MiniAspirador (sem espaços/acentos)."""
        import re as _re
        import unicodedata as _ud
        txt = _ud.normalize("NFKD", self.nome)
        txt = "".join(c for c in txt if not _ud.combining(c))
        txt = _re.sub(r"[^A-Za-z0-9]+", "", txt)[:30] or "Produto"
        return f"{self.id.replace('#', '')}_{txt}"

    @property
    def pasta(self) -> Path:
        """Pasta de trabalho do produto em Produtos/#NN_Slug/."""
        return PRODUTOS_DIR / self.slug

    @property
    def pasta_clipes(self) -> Path:
        """Onde o usuário joga os clipes brutos (Midias/#NN_Slug/)."""
        return MIDIAS_DIR / self.slug

    def clipes(self) -> list[Path]:
        """Clipes brutos disponíveis, ordenados numericamente."""
        if not self.pasta_clipes.exists():
            return []
        exts = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
        arqs = [p for p in self.pasta_clipes.iterdir() if p.suffix.lower() in exts]
        import re as _re
        def num(p: Path) -> int:
            m = _re.search(r"(\d+)", p.stem)
            return int(m.group(1)) if m else 10**9
        return sorted(arqs, key=num)


# ─── Planilha: leitura/escrita (CSV local; Sheets entra por esta mesma porta) ─
def ler_produtos(csv_path: Path | None = None) -> list[Produto]:
    """Lê a planilha base. Aceita CSV local; retorna lista de Produto."""
    path = csv_path or CSV_PATH
    prods = []
    with open(path, newline="", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            p = Produto(
                id=(linha.get("ID") or "").strip(),
                status=(linha.get("Status") or "Ideia").strip(),
                data_postagem=(linha.get("Data Postagem") or "").strip(),
                nome=(linha.get("Nome do Produto") or "").strip(),
                nicho=(linha.get("Nicho") or "").strip(),
                preco=(linha.get("Preco Medio (R$)") or "").strip(),
                comissao=(linha.get("Comissao Est (R$)") or "").strip(),
                link_afiliado=(linha.get("Link Afiliado Shopee") or "").strip(),
                link_vitrine=(linha.get("Link Vitrine (Bio)") or "").strip(),
                pasta_midias=(linha.get("Pasta Midias") or "").strip(),
                gancho=(linha.get("Roteiro / Gancho") or "").strip(),
                post_agendado=(linha.get("Post Agendado") or "Nao").strip(),
            )
            if p.id:
                prods.append(p)
    return prods


def salvar_produtos(prods: list[Produto], csv_path: Path | None = None) -> None:
    """Salva a lista de produtos de volta no CSV (planilha local)."""
    path = csv_path or CSV_PATH
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUNAS)
        for p in prods:
            w.writerow([
                p.id, p.status, p.data_postagem, p.nome, p.nicho,
                p.preco, p.comissao, p.link_afiliado, p.link_vitrine,
                p.pasta_midias or f"Midias/{p.slug}", p.gancho, p.post_agendado,
            ])


def carregar_env() -> dict[str, str]:
    """Carrega o .env local (GEMINI_API_KEY etc.) sem pacotes extras."""
    env = {}
    if ENV_PATH.exists():
        for ln in ENV_PATH.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, _, v = ln.partition("=")
                env[k.strip()] = v.strip()
    return env


ENV = carregar_env()
GEMINI_API_KEY = ENV.get("GEMINI_API_KEY", "")

if __name__ == "__main__":
    # autoteste rápido: python config.py
    for p in ler_produtos():
        print(p.id, "|", p.nome, "|", p.status, "| clipes:", len(p.clipes()))
