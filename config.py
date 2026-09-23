"""
config.py — Constantes, pastas e utilidades da Fábrica de Achadinhos.

Padrões visuais/sonoros validados (mesma linguagem dos vídeos de achadinhos
que funcionam no Reels/TikTok): 1080x1920, locução no primeiro plano,
trilha a -20 dB com ducking, loudness final -14 LUFS.
"""

from __future__ import annotations

import csv
import os
import re
import sys
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
    "Prompt Criativo", "Observacoes", "Media ID Instagram",
    # ── métricas de desempenho (preenchidas após postar) ──────────────────
    "Comentarios QUERO", "Alcance", "Salvamentos", "Nota Manual",
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
    # campos gerados pelo pipeline / app (não estão no CSV base)
    prompt_criativo: str = ""
    observacoes: str = ""
    media_id_instagram: str = ""
    # métricas de desempenho (preenchidas após postar)
    comentarios_quero: str = ""   # quantos comentaram "QUERO"
    alcance: str = ""             # impressões / alcance do post
    salvamentos: str = ""         # número de salvamentos
    nota_manual: str = ""         # sua nota subjetiva 1-5
    roteiro: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ID": self.id,
            "Status": self.status,
            "Data Postagem": self.data_postagem,
            "Nome do Produto": self.nome,
            "Nicho": self.nicho,
            "Preco Medio (R$)": self.preco,
            "Comissao Est (R$)": self.comissao,
            "Link Afiliado Shopee": self.link_afiliado,
            "Link Vitrine (Bio)": self.link_vitrine,
            "Pasta Midias": self.pasta_midias,
            "Roteiro / Gancho": self.gancho,
            "Post Agendado": self.post_agendado,
            "Prompt Criativo": self.prompt_criativo,
            "Observacoes": self.observacoes,
            "Media ID Instagram": self.media_id_instagram,
            "Comentarios QUERO": self.comentarios_quero,
            "Alcance": self.alcance,
            "Salvamentos": self.salvamentos,
            "Nota Manual": self.nota_manual,
        }

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


# ─── Planilha: parse e CSV local (API pública fica em sheets.py) ────────────
def produto_de_linha(linha: dict) -> Produto | None:
    """Converte uma linha (CSV/Sheets) em Produto. Retorna None se sem ID."""
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
        prompt_criativo=(linha.get("Prompt Criativo") or "").strip(),
        observacoes=(linha.get("Observacoes") or "").strip(),
        media_id_instagram=(linha.get("Media ID Instagram") or "").strip(),
        comentarios_quero=(linha.get("Comentarios QUERO") or "").strip(),
        alcance=(linha.get("Alcance") or "").strip(),
        salvamentos=(linha.get("Salvamentos") or "").strip(),
        nota_manual=(linha.get("Nota Manual") or "").strip(),
    )
    return p if p.id else None


def validar_ids_unicos(prods: list[Produto]) -> None:
    """Impede ID vazio ou duplicado antes de persistir."""
    vistos: set[str] = set()
    for p in prods:
        pid = (p.id or "").strip()
        if not pid:
            raise ValueError("Produto sem ID não pode ser salvo.")
        if pid in vistos:
            raise ValueError(f"ID duplicado: {pid}")
        vistos.add(pid)


def proximo_id(prods: list[Produto]) -> str:
    """Próximo ID livre da planilha (ex.: [#03, #07] → "#08")."""
    nums = []
    for p in prods:
        m = re.search(r"\d+", p.id or "")
        if m:
            nums.append(int(m.group()))
    return f"#{(max(nums) if nums else 0) + 1:02d}"


def ler_csv_local(csv_path: Path | None = None) -> list[Produto]:
    """Lê o CSV local (fallback da porta única em sheets.py)."""
    path = csv_path or CSV_PATH
    if not path.exists():
        return []
    prods = []
    with open(path, newline="", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            p = produto_de_linha(linha)
            if p:
                prods.append(p)
    return prods


def salvar_csv_local(prods: list[Produto], csv_path: Path | None = None) -> None:
    """Grava a lista no CSV local (backup). Não sincroniza com o Sheets."""
    validar_ids_unicos(prods)
    path = csv_path or CSV_PATH
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        for p in prods:
            w.writerow(p.to_dict())


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


def _segredo_streamlit(chave: str) -> str:
    """Lê .streamlit/secrets.toml (Streamlit Community Cloud), se disponível.

    Só consulta o streamlit já importado (roda sob `streamlit run`);
    scripts de linha de comando não pagam o custo de importá-lo.
    """
    st = sys.modules.get("streamlit")
    if st is None:
        return ""
    try:
        return str(st.secrets.get(chave, "")).strip()
    except Exception:
        return ""


def obter_segredo(chave: str) -> str:
    """Resolve um segredo na ordem: variável de ambiente → .env → st.secrets."""
    return (
        (os.environ.get(chave) or "").strip()
        or (ENV.get(chave) or "").strip()
        or _segredo_streamlit(chave)
    )
GEMINI_API_KEY = obter_segredo("GEMINI_API_KEY")

if __name__ == "__main__":
    # autoteste rápido: python config.py
    for p in ler_csv_local():
        print(p.id, "|", p.nome, "|", p.status, "| clipes:", len(p.clipes()))
