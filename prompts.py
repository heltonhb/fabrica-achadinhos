"""
prompts.py — Geração de prompts via Gemini.

Cada prompt é gerado pelo Gemini com base nos dados do produto,
resultando em textos mais específicos e criativos que templates genéricos.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict

from config import Produto
from gemini_client import _chamar_gemini
from metricas import PostComDesempenho, formatar_exemplos_para_prompt

logger = logging.getLogger(__name__)


@dataclass
class PromptCriativo:
    produto_id: str
    produto_nome: str
    nicho: str
    preco: str
    gancho: str
    tipo: str
    prompt_texto: str
    metadados: dict

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=indent)

    def to_copy_paste(self) -> str:
        return self.prompt_texto


# ─── Estilos / personas disponíveis ──────────────────────────────────────────

ESTILOS: dict[str, dict] = {
    "chocante": {
        "label": "😱 Chocante",
        "descricao": (
            "Tom de revelação — 'não acredito que isso existe'. "
            "Começa com uma cena de problema exagerado, corte abrupto para solução. "
            "Ritmo acelerado, silêncio dramático antes do preço."
        ),
    },
    "educativo": {
        "label": "🎓 Educativo",
        "descricao": (
            "Tom de dica útil de amigo — 'aprendi isso e preciso te contar'. "
            "Explica o porquê do produto funcionar. "
            "Mais calmo, linguagem clara, sem hipérbole."
        ),
    },
    "lifestyle": {
        "label": "✨ Lifestyle",
        "descricao": (
            "Tom aspiracional — produto integrado a uma rotina organizada/bonita. "
            "Cenas esteticamente agradáveis, casa arrumada, luz natural. "
            "Levemente mais lento, foco no visual."
        ),
    },
    "comparativo": {
        "label": "💰 Comparativo",
        "descricao": (
            "Tom de economia inteligente — 'isso substitui X que custa 10x mais'. "
            "Mostra explicitamente o produto alternativo caro e o preço. "
            "Foco em custo-benefício, prático e direto."
        ),
    },
}


# ─── System prompts ───────────────────────────────────────────────────────────

_SYSTEM_VIDEO_BASE = """\
You are an expert short-form video scriptwriter for TikTok and Instagram Reels,
specialized in "marketplace finds" (Shopee) from Brazil.

Your job is to generate PROMPTS that will be sent to an AI video generator
(like Google Vids). The prompt must describe EXACTLY what the generator should create
— scene by scene, with precise timing.

VISUAL AND AUDIO RULES (always include in the generated prompt):
- Vertical format 9:16, 1080×1920
- Voiceover in Brazilian Portuguese, informal, NO emoji
- No introduction ("Olá, tudo bem?") — go straight to the hook
- Light background music, must NOT overpower the voice
- Badge "ACHADINHO" at the top of the video
- Maximum 30 words of voiceover per part (~10 seconds)
- Describe scene by scene with timing in seconds
- Be visual: describe what appears on screen, not just what is said
- Do NOT include subtitle/caption instructions (generated separately)"""

_SYSTEM_PODCAST = """\
You are a podcast scriptwriter for Brazil, specialized in "marketplace finds."
Generate prompts for audio/podcast that will be created by AI (NotebookLM).
Tone: casual conversation between friends, informal, like showing a great find.
Brazilian Portuguese. Not aggressively salesy."""

_SYSTEM_CARROSSEL = """\
You are an Instagram content designer specialized in "marketplace finds" carousels.
Generate detailed slide-by-slide prompts, describing visuals, text, and colors."""


# ─── Geração de prompts via Gemini ────────────────────────────────────────────

def gerar_prompt_video(
    produto: Produto,
    plataforma: str = "reels",
    estilo: str = "chocante",
    exemplos: list[PostComDesempenho] | None = None,
    uso_inusitado: str | None = None,
    estrategia_parte2: str = "plot_twist",
) -> list[PromptCriativo]:
    """Gera prompts autocontidos para cada parte do vídeo via Gemini.

    Args:
        produto: Dados do produto.
        plataforma: ``"reels"`` ou ``"tiktok"``.
        estilo: Uma das chaves de ``ESTILOS`` (chocante, educativo, lifestyle, comparativo).
        exemplos: Posts anteriores com bom desempenho para usar como few-shot examples.
        uso_inusitado: Descrição opcional de um uso criativo/inusitado do produto.
                       Se None, o Gemini sugere um uso livremente.
        estrategia_parte2: ``"plot_twist"`` (uso inusitado) ou ``"qualidade"`` (reforço de qualidade).
    """
    nome = produto.nome
    nicho = produto.nicho or "general"
    preco = produto.preco or "XX.XX"
    gancho = produto.gancho or f"Check out this find: {produto.nome}"
    plataforma_nome = "Instagram Reels" if plataforma == "reels" else "TikTok"

    estilo_info = ESTILOS.get(estilo, ESTILOS["chocante"])
    estilo_label = estilo_info["label"]
    estilo_desc = estilo_info["descricao"]

    # few-shot: injeta exemplos antes do pedido principal
    bloco_exemplos = formatar_exemplos_para_prompt(exemplos or [])
    prefixo = f"{bloco_exemplos}\n\n" if bloco_exemplos else ""

    # bloco de estratégia para Parte 2
    if estrategia_parte2 == "qualidade":
        bloco_uso = (
            "\nSTRATEGY for Part 2: REINFORCE PRODUCT QUALITY.\n"
            "Focus on: durability, materials, build quality, key differentiators.\n"
            "Show close-ups of the product, compare with cheaper alternatives,\n"
            "highlight what makes it worth the price. Make the viewer think\n"
            "\"this is actually well-made for the price.\"\n"
        )
    elif uso_inusitado:
        bloco_uso = (
            f"\nSTRATEGY for Part 2: PLOT TWIST (unusual use).\n"
            f"UNUSUAL USE: {uso_inusitado}\n"
            f"Use this EXACTLY as described — do not invent a different unusual use.\n"
        )
    else:
        bloco_uso = (
            "\nSTRATEGY for Part 2: PLOT TWIST (unusual/creative use).\n"
            "You may suggest a creative/unexpected use for the product "
            "if it fits naturally. If no unusual use fits well, "
            "fall back to reinforcing product quality instead.\n"
        )

    user_p1 = f"""\
{prefixo}Generate a PROMPT for Part 1 (0-10 seconds) of a 20-second {plataforma_nome} video.

PRODUCT: {nome}
NICHE: {nicho}
PRICE: R$ {preco}
OPENING HOOK: {gancho}
VIDEO STYLE: {estilo_label} — {estilo_desc}

IMPORTANT: The prompt you generate must be in ENGLISH.
However, ALL spoken dialogue, on-screen text, and visible text elements must be in BRAZILIAN PORTUGUESE.

Part 1 must contain:
- HOOK in the first 3 seconds (use the provided hook, adapt to the style)
- Product shown in real use (3-7s)
- A second unexpected feature (7-10s) — something surprising
- Ending that keeps the viewer watching

The prompt must be SELF-CONTAINED — ready to copy and paste into a video generator.
Do NOT include subtitle/caption instructions (those are generated separately)."""

    user_p2 = f"""\
{prefixo}Generate a PROMPT for Part 2 (10-20 seconds) of a 20-second {plataforma_nome} video.

PRODUCT: {nome}
NICHE: {nicho}
PRICE: R$ {preco}
OPENING HOOK: {gancho}
VIDEO STYLE: {estilo_label} — {estilo_desc}
{bloco_uso}
IMPORTANT: The prompt you generate must be in ENGLISH.
However, ALL spoken dialogue, on-screen text, and visible text elements must be in BRAZILIAN PORTUGUESE.

Part 2 must contain:
- TRANSITION at the start (consistent with the style)
- CREATIVE/UNUSUAL USE of the product (12-17s) — the "wow" moment
- CTA in the last 3 seconds: "Comenta QUERO que eu te mando o link!" + yellow arrow to bio
- Faster rhythm than Part 1

The prompt must be SELF-CONTAINED.
Do NOT include subtitle/caption instructions (those are generated separately)."""

    try:
        texto_p1 = _chamar_gemini(_SYSTEM_VIDEO_BASE, user_p1, temperature=0.9)
        texto_p2 = _chamar_gemini(_SYSTEM_VIDEO_BASE, user_p2, temperature=0.9)
    except Exception as exc:
        logger.error("Gemini falhou: %s", exc)
        texto_p1 = f"[ERRO GEMINI] Parte 1 — {plataforma_nome} — {nome}. Gancho: {gancho}"
        texto_p2 = f"[ERRO GEMINI] Parte 2 — {plataforma_nome} — {nome}. Plot twist + CTA."

    n_exemplos = len(exemplos) if exemplos else 0
    meta_base = {"plataforma": plataforma, "estilo": estilo, "fonte": "gemini", "few_shot": n_exemplos}
    return [
        PromptCriativo(
            produto_id=produto.id, produto_nome=produto.nome,
            nicho=produto.nicho, preco=produto.preco, gancho=produto.gancho,
            tipo=f"video_{plataforma}_parte1", prompt_texto=texto_p1,
            metadados={**meta_base, "parte": "1", "duracao": "10s"},
        ),
        PromptCriativo(
            produto_id=produto.id, produto_nome=produto.nome,
            nicho=produto.nicho, preco=produto.preco, gancho=produto.gancho,
            tipo=f"video_{plataforma}_parte2", prompt_texto=texto_p2,
            metadados={**meta_base, "parte": "2", "duracao": "10s"},
        ),
    ]


def gerar_prompt_podcast(produto: Produto) -> PromptCriativo:
    """Gera prompt para podcast/áudio via Gemini."""
    user = f"""\
Gere o PROMPT para um podcast curto (2–3 minutos) sobre o produto "{produto.nome}".

PRODUTO: {produto.nome}
NICHO: {produto.nicho or 'geral'}
PREÇO: R$ {produto.preco or 'XX,XX'}
GANCHO: {produto.gancho or f'Um achadinho: {produto.nome}'}

O podcast deve:
1. Abrir apresentando o produto como "achadinho" que vale muito pelo preço
2. Explicar por que é útil no dia a dia
3. Descrever 2–3 usos práticos com exemplos reais e cotidianos
4. Comparar com solução mais cara quando aplicável
5. Fechar com CTA natural (link na bio)

Tom: conversa entre dois amigos descobrindo juntos. Informal, sem ser vendedor agressivo.
O prompt deve ser AUTOCONTIDO."""

    try:
        texto = _chamar_gemini(_SYSTEM_PODCAST, user, temperature=0.8)
    except Exception as exc:
        logger.error("Gemini falhou: %s", exc)
        texto = f"[ERRO GEMINI] Gere podcast sobre {produto.nome}."

    return PromptCriativo(
        produto_id=produto.id, produto_nome=produto.nome,
        nicho=produto.nicho, preco=produto.preco, gancho=produto.gancho,
        tipo="podcast", prompt_texto=texto,
        metadados={"duracao_alvo": "2-3min", "fonte": "gemini"},
    )


def gerar_prompt_carrossel(produto: Produto) -> PromptCriativo:
    """Gera prompt para carrossel via Gemini."""
    user = f"""\
Gere o PROMPT para um carrossel de 5–7 slides para Instagram sobre "{produto.nome}".

PRODUTO: {produto.nome}
NICHO: {produto.nicho or 'geral'}
PREÇO: R$ {produto.preco or 'XX,XX'}
GANCHO: {produto.gancho or f'Achadinho: {produto.nome}'}

Slides obrigatórios:
1. CAPA — badge "ACHADINHO", headline impactante com o gancho
2. PROBLEMA — situação que o leitor reconhece no próprio dia a dia
3. SOLUÇÃO — produto em uso real, foto limpa
4. FUNCIONALIDADE 1 — detalhe prático com ícone ou seta
5. FUNCIONALIDADE 2 (surpresa) — o uso que ninguém esperava
6. PREÇO + VALOR — "R$ {produto.preco or 'XX'} vs alternativa de R$ ???"
7. CTA — "Salva esse post! Comenta QUERO pelo link"

Design: 1080×1080 ou 1080×1350. Fundo escuro, texto branco/amarelo, fonte bold sem serifa.
O prompt deve ser AUTOCONTIDO."""

    try:
        texto = _chamar_gemini(_SYSTEM_CARROSSEL, user, temperature=0.8)
    except Exception as exc:
        logger.error("Gemini falhou: %s", exc)
        texto = f"[ERRO GEMINI] Gere carrossel sobre {produto.nome}."

    return PromptCriativo(
        produto_id=produto.id, produto_nome=produto.nome,
        nicho=produto.nicho, preco=produto.preco, gancho=produto.gancho,
        tipo="carrossel", prompt_texto=texto,
        metadados={"formato": "1080x1080 ou 1080x1350", "fonte": "gemini"},
    )


def gerar_todos_prompts(
    produto: Produto,
    estilo: str = "chocante",
    uso_inusitado: str | None = None,
    estrategia_parte2: str = "plot_twist",
) -> list[PromptCriativo]:
    prompts: list[PromptCriativo] = []
    prompts.extend(gerar_prompt_video(
        produto, "reels", estilo,
        uso_inusitado=uso_inusitado, estrategia_parte2=estrategia_parte2,
    ))
    prompts.extend(gerar_prompt_video(
        produto, "tiktok", estilo,
        uso_inusitado=uso_inusitado, estrategia_parte2=estrategia_parte2,
    ))
    prompts.append(gerar_prompt_podcast(produto))
    prompts.append(gerar_prompt_carrossel(produto))
    return prompts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    p = Produto(
        id="#99", nome="Fones de Ouvido Bluetooth TWS",
        nicho="Tech", preco="39.90",
        gancho="Esquece os AirPods, esse custa 10x menos",
    )
    for estilo in ESTILOS:
        print(f"\n{'='*60}\nESTILO: {estilo}\n{'='*60}")
        pr = gerar_prompt_video(p, "reels", estilo)[0]
        print(pr.prompt_texto[:400])
        print("...")
