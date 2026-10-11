"""
prompts.py — Geração de prompts autocontidos para criativos externo (Google Vids, NotebookLM, carrossel).

CONTRATO DE PROMPTS — Fábrica de Achadinhos
=============================================

Este módulo gera PROMPTS, não roteiros de locução em português.
À diferença de roteirista.py (que produz roteiro de referência em PT),
o prompt aqui é a entrega principal que vai para o gerador de vídeo/audio/design.

Regras de contrato (válidas para todos os prompts de criativo):

- Prompt de vídeo (Reels/TikTok):
    * formato vertical 9:16, 1080x1920
    * voz em português brasileiro, informal, sem emoji
    * sem introdução ("Olá", "Ei pessoal") — direto ao gancho
    * gancho em 0:00-0:02 (máx 6 palavras), primeiro frame já em movimento
    * pattern interrupt obrigatório em 0:07-0:08 (corte seco, sem voz)
    * orçamento de palavras POR BEAT, não teto global (32 na P1, 34 na P2)
    * loop é VISUAL (último frame reenquadra o primeiro), nunca verbal
    * descrição cena a cena com tempo em segundos
    * prompt em inglês, mas diálogo e texto na tela em português
    * sem instrução de legendas (gerada separadamente em legenda.py)
    * texto na tela: 1 a 3 palavras por beat, palavra-chave em amarelo
    * deve conter CTA final explícito

- Prompt de podcast (NotebookLM):
    * prompt autocontido em português
    * duração alvo ~2-3 min
    * tom conversacional entre amigos, sem venda agressiva

- Prompt de carrossel:
    * prompt autocontido em português
    * slide a slide (5-7 slides)
    * 1080x1080 ou 1080x1350, fundo escuro, texto branco/amarelo, fonte bold

Validação:
    * prompts de vídeo passam por uma checagem de presença de elementos
      obrigatórios antes de serem considerados entregues na UI.

Uso do few-shot (métricas):
    * Quando houver posts com desempenho medido, o sistema pode injetar
      os melhores como exemplo no prompt do vídeo.
    * O few-shot é opcional e visível na seção Gerar Prompt.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict

from config import Produto
from gemini_client import _chamar_gemini
from metricas import PostComDesempenho, formatar_exemplos_para_prompt

logger = logging.getLogger(__name__)


def _gerar_com_fallback(fn, fallback: str, rotulo: str) -> tuple[str, str | None]:
    """Executa ``fn``; em falha retorna ``(fallback, erro)`` senão ``(texto, None)``."""
    try:
        return fn().strip(), None
    except Exception as exc:  # noqa: BLE001
        logger.error("Gemini falhou em %s: %s", rotulo, exc)
        return fallback, str(exc)


# ─── Validação de contrato do prompt de vídeo ────────────────────────────────

# Palavras/chaves que um prompt de vídeo deve conter para ser considerado
# entregável válido. Não é schema rígido de JSON; é uma checagem de presença.
_VIDEO_PROMPT_REQUISITOS = (
    "vertical",            # formato 9:16 / vertical
    "1080",               # resolução
    "brazilian portuguese",
    "portuguese",
)


def validar_prompt_video(texto: str) -> tuple[bool, list[str]]:
    """Checa se um prompt de vídeo contém os elementos obrigatórios.

    Retorna ``(ok, faltando)``.
    """
    t = texto.lower()
    faltando = [r for r in _VIDEO_PROMPT_REQUISITOS if r not in t]
    # presença de CTA é difícil de checar por regex genérico, mas uma heurística
    # básica ajuda: palavras de chamada à ação costumam estar presentes.
    cta_forte = any(p in t for p in ("cta", "call to action", "comenta", "comentar", "quero", "link", "perfil", "bio", "channel", "vitrine"))
    avisos: list[str] = []
    if not cta_forte:
        avisos.append("possível CTA ausente no prompt de vídeo")
    return (not faltando, faltando + avisos)


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
- Badge "ACHADINHO" at the top of the video, identical position/size in every shot
- Brisk conversational pace: about 3.5 words per second, NOT slower
- Frame 1 must already contain motion (camera move, hands, product in use). No static
  opening frame, no fade-in from black.
- Describe scene by scene with timing in seconds
- Be visual: describe what appears on screen, not just what is said
- Do NOT include subtitle/caption instructions (generated separately)

VOICEOVER BUDGET — the budget is PER BEAT, not a global total. Each beat below
has its own word cap. Never exceed the cap of a single beat. A shorter video with
dead air loses more viewers than a slightly dense one.

  Part 1 (0:00–0:10)                         Part 2 (0:10–0:20)
  0:00–0:02  hook .................. 6 words   0:10–0:11  continuation .... 0 words
  0:02–0:07  product in use ........ 16 words  0:11–0:16  payoff ........ 18 words
  0:07–0:08  PATTERN INTERRUPT ...... 0 words   0:16–0:18  price reveal ... 8 words
  0:08–0:10  setup to payoff ........ 10 words  0:18–0:20  CTA + loop ..... 8 words
  ------------------- 32 words ----------------  ---------------- 34 words
  TOTAL: 66 words ≈ 19s of speech + 1s of silence = a full 20 seconds.
  Do not write less than 60 words total — dead air is wasted reach.

PATTERN INTERRUPT (mandatory, at 0:07–0:08, in every prompt):
- A hard cut or fast punch-in on the product, with NO voiceover during it
- It resets attention roughly two thirds of the way through
- Keep it to one second. It must feel like an accident of editing, not a transition.

ON-SCREEN TEXT:
- One short text per beat, 1 to 3 words. NEVER a full sentence.
- The single most important word of each beat in bold yellow, the rest in white
- Price always visible as plain digits (e.g. "39,90"), never as "só R$"
- Do not repeat what the voiceover already says out loud

SEAMLESS LOOP (visual, not verbal):
- The final frame must match the FIRST frame in framing, product position,
  hand position and lighting — as if the video never stopped
- Audio cuts clean on the last syllable, zero trailing silence or fade-out
- The spoken CTA is a SHORT COMPLETE sentence. Do NOT end on an open grammar
  connector, do NOT trail off, do NOT say "e é exatamente por isso que..." to
  link back to the hook. The loop is carried by the picture, not by a sentence
  that splices two clips together. This is what buys back 3–4 seconds of value.

CALL TO ACTION — write it as a fixed sentence, do not improvise:
- The CTA must name the product number out loud, because the viewer has to find
  that exact product on the storefront page afterwards. Numbers spoken once are
  forgotten; a repeated number is searchable.
- Use one of these exact forms (keep the number, change nothing else):
    "Vai pro perfil e procura o {N}. É esse aqui."
    "Tá no perfil do canal, item {N}."
    "Link no perfil, produto {N}."
- Say the number SLOWLY and SEPARATELY from the rest of the sentence. Never bury it
  inside a long clause.
- NEVER write awkward Portuguese about the link. These are all WRONG:
  "garanta seu link", "garantir o link", "adquira o seu link". You do not
  guarantee, acquire or own a link, you FIND it. A link is "no perfil",
  "tá fixado", "procure".
- Do not invent possessive constructions around the link. Write plain Brazilian
  speech: "tá no perfil", "procura no perfil", "é o {N}".
- If a sentence sounds stilted when read aloud in Portuguese, it is wrong —
  rewrite it, do not ship it."""

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
    loop_infinito: bool | None = None,
) -> list[PromptCriativo]:
    """Gera prompts autocontidos para cada parte do vídeo via Gemini.

    Args:
        produto: Dados do produto.
        plataforma: ``"reels"``, ``"tiktok"`` ou ``"shorts"``.
        estilo: Uma das chaves de ``ESTILOS`` (chocante, educativo, lifestyle, comparativo).
        exemplos: Posts anteriores com bom desempenho para usar como few-shot examples.
        uso_inusitado: Descrição opcional de um uso criativo/inusitado do produto.
                       Se None, o Gemini sugere um uso livremente.
        estrategia_parte2: ``"plot_twist"`` (uso inusitado) ou ``"qualidade"`` (reforço de qualidade).
        loop_infinito: Se True, aplica a técnica de Seamless Loop (o final da Parte 2 conecta
                       sintática e visualmente ao gancho inicial da Parte 1).
                       Se None, ativa automaticamente quando plataforma for Shorts.
    """
    nome = produto.nome
    nicho = produto.nicho or "general"
    preco = produto.preco or "XX.XX"
    gancho = produto.gancho or f"Check out this find: {produto.nome}"
    plat_lower = plataforma.lower()
    if "short" in plat_lower:
        plataforma_nome = "YouTube Shorts"
    elif "tiktok" in plat_lower:
        plataforma_nome = "TikTok"
    else:
        plataforma_nome = "Instagram Reels"

    loop_ativo = ("short" in plat_lower) if loop_infinito is None else bool(loop_infinito)
    num_clean = produto.id.replace("#", "")

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

    # Instrução de abertura / loop para Parte 1
    if loop_ativo:
        instrucao_loop_p1 = (
            "- HOOK at 0:00–0:02 (max 6 words), spoken over motion — frame 1 is already moving, "
            "no static pose, no fade-in. Because this clip loops back into itself, the opening must "
            "land instantly and read clearly when replayed."
        )
    else:
        instrucao_loop_p1 = "- HOOK at 0:00–0:02 (max 6 words), spoken over motion"

    user_p1 = f"""\
{prefixo}Generate a PROMPT for Part 1 (0-10 seconds) of a 20-second {plataforma_nome} video.

PRODUCT: {nome}
NICHE: {nicho}
PRICE: R$ {preco}
OPENING HOOK: {gancho}
VIDEO STYLE: {estilo_label} — {estilo_desc}

IMPORTANT: The prompt you generate must be in ENGLISH.
However, ALL spoken dialogue, on-screen text, and visible text elements must be in BRAZILIAN PORTUGUESE.

Part 1 must contain, with the exact word cap per beat:
{instrucao_loop_p1}
- 0:02–0:07 product in real use (max 16 words) — show the result, not the packaging
- 0:07–0:08 PATTERN INTERRUPT: hard cut or punch-in on the product, NO voiceover
- 0:08–0:10 setup that creates an open loop for Part 2 (max 10 words)
- Part 1 total: exactly 32 words of voiceover

On-screen text: one 1–3 word text per beat, key word in bold yellow.
Total runtime of Part 1: exactly 10 seconds (≈32 words at ~3.5 words/second).
The prompt must be SELF-CONTAINED — ready to copy and paste into a video generator.
Do NOT include subtitle/caption instructions (those are generated separately)."""

    # Partes independentes com fallback: a Parte 1 é gerada primeiro para que a
    # Parte 2 saiba qual é o frame de abertura que o loop visual precisa reenquadrar
    texto_p1, err_p1 = _gerar_com_fallback(
        lambda: _chamar_gemini(_SYSTEM_VIDEO_BASE, user_p1, temperature=0.9),
        f"[ERRO GEMINI] Parte 1 — {plataforma_nome} — {nome}. Gancho: {gancho}",
        rotulo="Parte 1",
    )

    # Se a Parte 1 gerou fala real, usa a frase exata como referência do frame de
    # abertura: o loop visual da Parte 2 precisa reenquadrar aquele mesmo momento.
    gancho_referencia = gancho
    if not err_p1 and texto_p1:
        m = re.search(r'(?:Voiceover|Locu[çc][ãa]o)[^:\n]*:\s*["“]([^"”\n]+)["”]', texto_p1, re.IGNORECASE)
        if m and len(m.group(1).strip()) > 5:
            gancho_referencia = m.group(1).strip()

    # Bloco de CTA e Loop para a Parte 2
    if loop_ativo:
        if "short" in plat_lower:
            bloco_cta = (
                f'- 0:18–0:20 CTA + VISUAL LOOP (max 8 words):\n'
                f'  * Spoken CTA — use this exact sentence, do not improvise: '
                f'"Vai pro perfil e procura o {num_clean}. É esse aqui." '
                f'Say the number {num_clean} slowly and as a separate beat from the rest of the sentence.\n'
                f'  * Do NOT write "garanta seu link", "adquira o seu link" or any other unnatural phrasing about a link. '
                f'A link is "no perfil", "tá fixado", "procure" — never something you guarantee, acquire or own.\n'
                f'  * On-screen badge: "Achadinho {num_clean}" plus "🔗 Link no perfil do canal", with a bright animated arrow pointing to the channel profile/avatar.\n'
                f'  * AUDIO: cut clean on the final syllable, ZERO trailing silence or fade-out.\n'
                f'  * VISUAL: in the final 0.5s, the framing, product position, hand position and lighting '
                f'must snap back to exactly match the opening shot of Part 1.'
            )
        else:
            bloco_cta = (
                f'- 0:18–0:20 CTA + VISUAL LOOP (max 8 words):\n'
                f'  * Spoken CTA — use this exact sentence, do not improvise: '
                f'"Comenta QUERO que eu te mando o link do {num_clean}." '
                f'Say the number {num_clean} slowly and as a separate beat from the rest of the sentence.\n'
                f'  * Do NOT write "garanta seu link", "adquira o seu link" or any other unnatural phrasing about a link.\n'
                f'  * On-screen text: "R$ {preco}" plus "COMENTA QUERO", animated arrow to bio.\n'
                f'  * AUDIO: cut clean on the final syllable, ZERO trailing silence.\n'
                f'  * VISUAL: in the final 0.5s, the framing must snap back to match the opening shot of Part 1.'
            )
    else:
        if "short" in plat_lower:
            bloco_cta = (
                f'- 0:18–0:20 CTA (max 8 words): use this exact sentence — '
                f'"Vai pro perfil e procura o {num_clean}. É esse aqui." — and show the price "R$ {preco}" on screen, '
                f'+ on-screen badge "Achadinho {num_clean}" / "🔗 Link no perfil do canal" with a bright yellow arrow pointing to the channel profile/avatar.'
            )
        else:
            bloco_cta = (
                f'- 0:18–0:20 CTA (max 8 words): "Comenta QUERO que eu te mando o link do {num_clean}!" '
                f'+ yellow arrow to bio'
            )

    user_p2 = f"""\
{prefixo}Generate a PROMPT for Part 2 (10-20 seconds) of a 20-second {plataforma_nome} video.

PRODUCT: {nome}
NICHE: {nicho}
PRICE: R$ {preco}
OPENING HOOK OF PART 1: {gancho_referencia}
VIDEO STYLE: {estilo_label} — {estilo_desc}
{bloco_uso}
IMPORTANT: The prompt you generate must be in ENGLISH.
However, ALL spoken dialogue, on-screen text, and visible text elements must be in BRAZILIAN PORTUGUESE.

Part 2 must contain, with the exact word cap per beat:
- 0:10–0:11 continuation of Part 1, no voiceover, visual only
- 0:11–0:16 CREATIVE/UNUSUAL USE of the product — the "wow" moment (max 18 words)
- 0:16–0:18 price reveal, the number spoken clearly (max 8 words)
{bloco_cta}
- Part 2 total: exactly 34 words of voiceover

On-screen text: one 1–3 word text per beat, key word in bold yellow. The price
must be readable as plain digits on screen at 0:16–0:18.
Total runtime of Part 2: exactly 10 seconds (≈34 words at ~3.5 words/second).

The prompt must be SELF-CONTAINED.
Do NOT include subtitle/caption instructions (those are generated separately)."""

    texto_p2, err_p2 = _gerar_com_fallback(
        lambda: _chamar_gemini(_SYSTEM_VIDEO_BASE, user_p2, temperature=0.9),
        f"[ERRO GEMINI] Parte 2 — {plataforma_nome} — {nome}. Plot twist + CTA.",
        rotulo="Parte 2",
    )
    # validação de contrato do prompt de vídeo (aviso, não bloqueia)
    for parte, texto in [("Parte 1", texto_p1), ("Parte 2", texto_p2)]:
        se_ok, faltando = validar_prompt_video(texto)
        if not se_ok:
            logger.warning(
                "Prompt de vídeo (%s) para %s não atende ao contrato: %s",
                parte, nome, "; ".join(faltando),
            )

    if err_p1 or err_p2:
        logger.error(
            "Gemini falhou ao gerar prompt (%s): parte1=%s | parte2=%s",
            nome, err_p1 or "ok", err_p2 or "ok",
        )

    n_exemplos = len(exemplos) if exemplos else 0
    meta_base = {
        "plataforma": plataforma,
        "estilo": estilo,
        "fonte": "gemini",
        "few_shot": n_exemplos,
        "loop_infinito": loop_ativo,
    }
    meta_p1 = {**meta_base, "parte": "1", "duracao": "10s"}
    meta_p2 = {**meta_base, "parte": "2", "duracao": "10s"}
    if err_p1:
        meta_p1["erro"] = err_p1
    if err_p2:
        meta_p2["erro"] = err_p2
    return [
        PromptCriativo(
            produto_id=produto.id, produto_nome=produto.nome,
            nicho=produto.nicho, preco=produto.preco, gancho=produto.gancho,
            tipo=f"video_{plataforma}_parte1", prompt_texto=texto_p1,
            metadados=meta_p1,
        ),
        PromptCriativo(
            produto_id=produto.id, produto_nome=produto.nome,
            nicho=produto.nicho, preco=produto.preco, gancho=produto.gancho,
            tipo=f"video_{plataforma}_parte2", prompt_texto=texto_p2,
            metadados=meta_p2,
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

    texto, err = _gerar_com_fallback(
        lambda: _chamar_gemini(_SYSTEM_PODCAST, user, temperature=0.8),
        f"[ERRO GEMINI] Gere podcast sobre {produto.nome}.",
        rotulo="Podcast",
    )

    return PromptCriativo(
        produto_id=produto.id, produto_nome=produto.nome,
        nicho=produto.nicho, preco=produto.preco, gancho=produto.gancho,
        tipo="podcast", prompt_texto=texto,
        metadados={"duracao_alvo": "2-3min", "fonte": "gemini", **({"erro": err} if err else {})},
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

    texto, err = _gerar_com_fallback(
        lambda: _chamar_gemini(_SYSTEM_CARROSSEL, user, temperature=0.8),
        f"[ERRO GEMINI] Gere carrossel sobre {produto.nome}.",
        rotulo="Carrossel",
    )

    return PromptCriativo(
        produto_id=produto.id, produto_nome=produto.nome,
        nicho=produto.nicho, preco=produto.preco, gancho=produto.gancho,
        tipo="carrossel", prompt_texto=texto,
        metadados={"formato": "1080x1080 ou 1080x1350", "fonte": "gemini", **({"erro": err} if err else {})},
    )


def gerar_todos_prompts(
    produto: Produto,
    estilo: str = "chocante",
    uso_inusitado: str | None = None,
    estrategia_parte2: str = "plot_twist",
) -> list[PromptCriativo]:
    prompts: list[PromptCriativo] = []
    prompts.extend(gerar_prompt_video(
        produto, "shorts", estilo,
        uso_inusitado=uso_inusitado, estrategia_parte2=estrategia_parte2,
    ))
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
