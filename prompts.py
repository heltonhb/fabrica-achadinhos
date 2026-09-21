"""
prompts.py — Geração de prompts via Gemini.

Cada prompt é gerado pelo Gemini com base nos dados do produto,
resultando em textos mais específicos e criativos que templates genéricos.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict

from google import genai
from google.genai import types
from config import GEMINI_API_KEY, Produto

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


# ─── Chamada ao Gemini ───────────────────────────────────────────────────────

def _chamar_gemini(system_prompt: str, user_prompt: str) -> str:
    """Chama o Gemini e retorna o texto gerado."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ausente no .env")

    client = genai.Client(api_key=GEMINI_API_KEY)
    modelos = ["gemini-3.6-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

    for modelo in modelos:
        for tentativa in range(3):
            try:
                resp = client.models.generate_content(
                    model=modelo,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.8,
                    ),
                )
                if resp.text:
                    return resp.text.strip()
            except Exception as exc:
                if "429" in str(exc) or "500" in str(exc) or "503" in str(exc):
                    time.sleep(2 ** tentativa * 2)
                    continue
                logger.warning("Gemini %s falhou: %s", modelo, str(exc)[:100])
                break

    raise RuntimeError("Gemini não respondeu nenhum modelo")


# ─── System prompts (instruções pro Gemini) ─────────────────────────────────

_SYSTEM_VIDEO = """\
Você é um roteirista especialista em vídeos curtos para TikTok e Instagram Reels,
focado em "achadinhos" de marketplace (Shopee) do Brasil.

Seu trabalho é gerar PROMPTS que serão enviados a um gerador de vídeos por IA
(como Google Vids ou NotebookLM). O prompt deve descrever EXATAMENTE o que
o gerador deve criar — cena por cena, com timing preciso.

REGRAS GERAIS (sempre inclua no prompt):
- Vertical (9:16, 1080x1920)
- Locução em português brasileiro, informal, SEM emoji
- Sem introdução tipo "Olá, tudo bem?" — direto ao gancho
- Trilha sonora leve de fundo (não pode abafar a voz)
- Legendas automáticas estilo CapCut (palavra destacada em amarelo)
- Badge "ACHADINHO" no topo do vídeo
- No máximo 30 palavras de locução por parte (10 segundos)
- Descreva CENA POR CENA com timing em segundos
- Seja visual: descreva o que aparece na tela, não só o que é falado"""

_SYSTEM_PODCAST = """\
Você é um roteirista de podcasts curtos para o Brasil, estilo "achadinhos de marketplace".
Gere prompts para áudio/podcast que serão criados por IA (NotebookLM).
Tom: conversa entre amigos, informal, como se mostrasse um achadinho.
Português brasileiro. Sem ser vendedor agressivo."""

_SYSTEM_CARROSSEL = """\
Você é um designer de conteúdo para Instagram, especializado em carrosséis de "achadinhos".
Gere prompts detalhados slide a slide, descrevendo visual, texto e cores."""


# ─── Geração de prompts via Gemini ───────────────────────────────────────────

def gerar_prompt_video(produto: Produto, plataforma: str = "reels") -> list[PromptCriativo]:
    """Gera prompts autocontidos para cada parte do vídeo via Gemini."""
    nome = produto.nome
    nicho = produto.nicho or "geral"
    preco = produto.preco or "XX,XX"
    gancho = produto.gancho or f"Olha só esse achadinho: {produto.nome}"
    plataforma_nome = "Instagram Reels" if plataforma == "reels" else "TikTok"

    user_p1 = f"""\
Gere o PROMPT para a PARTE 1 (0 a 10 segundos) de um vídeo de 20 segundos no {plataforma_nome}.

PRODUTO: {nome}
NICHO: {nicho}
PREÇO: R$ {preco}
GANCHO: {gancho}

A PARTE 1 deve conter:
- GANCHO nos primeiros 3 segundos (voz firme, sem apresentador)
- Apresentação do produto em uso real (3-7s)
- Uma segunda utilidade que o comprador não esperava (7-10s)
- Tom empolgado, como quem acabou de descobrir algo incrível
- Ritmo mais calmo e informativo
- Final que prenda o espectador pra continuar assistindo

INCLUA no prompt todas as regras visuais e de áudio (vertical 9:16, legendas CapCut, badge ACHADINHO, etc).
O prompt deve ser AUTOCONTIDO — pronto pra copiar e colar no gerador de vídeos."""

    user_p2 = f"""\
Gere o PROMPT para a PARTE 2 (10 a 20 segundos) de um vídeo de 20 segundos no {plataforma_nome}.

PRODUTO: {nome}
NICHO: {nicho}
PREÇO: R$ {preco}
GANCHO: {gancho}

A PARTE 2 deve conter:
- TRANSIÇÃO no início ("Mas o melhor vem agora..." ou equivalente)
- USO CRIATIVO/INUSITADO do produto (12-17s) — algo que ninguém esperaria.
  Exemplo real: se é um mini aspirador, mostrar que serve pra limpar o teclado do notebook,
  ou que dá pra usar pra aspirar pelos de animal, etc.
  Este é o CLÍMAX — o momento "uau" que faz pessoa salvar o post
- CTA nos últimos 3 segundos: "Comenta QUERO que eu te mando o link!" + seta amarela pra bio
- O CTA deve ser DIFERENTE do gancho da Parte 1
- Ritmo mais DINÂMICO — aqui é a entrega, o turbo

INCLUA no prompt todas as regras visuais e de áudio.
O prompt deve ser AUTOCONTIDO."""

    try:
        texto_p1 = _chamar_gemini(_SYSTEM_VIDEO, user_p1)
        texto_p2 = _chamar_gemini(_SYSTEM_VIDEO, user_p2)
    except Exception as exc:
        logger.error("Gemini falhou: %s", exc)
        # fallback: prompt básico
        texto_p1 = f"[ERRO GEMINI] Gere vídeo de 10s no {plataforma_nome} sobre {nome}. Gancho: {gancho}"
        texto_p2 = f"[ERRO GEMINI] Gere vídeo de 10s no {plataforma_nome} — plot twist + CTA sobre {nome}."

    return [
        PromptCriativo(
            produto_id=produto.id, produto_nome=produto.nome,
            nicho=produto.nicho, preco=produto.preco, gancho=produto.gancho,
            tipo=f"video_{plataforma}_parte1", prompt_texto=texto_p1,
            metadados={"plataforma": plataforma, "parte": "1", "duracao": "10s", "fonte": "gemini"},
        ),
        PromptCriativo(
            produto_id=produto.id, produto_nome=produto.nome,
            nicho=produto.nicho, preco=produto.preco, gancho=produto.gancho,
            tipo=f"video_{plataforma}_parte2", prompt_texto=texto_p2,
            metadados={"plataforma": plataforma, "parte": "2", "duracao": "10s", "fonte": "gemini"},
        ),
    ]


def gerar_prompt_podcast(produto: Produto) -> PromptCriativo:
    """Gera prompt para podcast/áudio via Gemini."""
    user = f"""\
Gere o PROMPT para um podcast curto (2-3 minutos) sobre o produto "{produto.nome}".

PRODUTO: {produto.nome}
NICHO: {produto.nicho or 'geral'}
PREÇO: R$ {produto.preco or 'XX,XX'}
GANCHO: {produto.gancho or f'Um achadinho: {produto.nome}'}

O podcast deve:
1. Abrir apresentando o produto como "achadinho" que vale muito pelo preço
2. Explicar por que é útil no dia a dia
3. Descrever 2-3 usos práticos com exemplos reais
4. Comparar com soluções mais caras (se aplicável)
5. Fechar com CTA (link na bio)

Tom: conversa entre amigos, informal. Português brasileiro. Sem ser vendedor agressivo.
O prompt deve ser AUTOCONTIDO."""

    try:
        texto = _chamar_gemini(_SYSTEM_PODCAST, user)
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
Gere o PROMPT para um carrossel de 5-7 imagens para Instagram sobre "{produto.nome}".

PRODUTO: {produto.nome}
NICHO: {produto.nicho or 'geral'}
PREÇO: R$ {produto.preco or 'XX,XX'}
GANCHO: {produto.gancho or f'Achadinho: {produto.nome}'}

O carrossel deve ter:
1. CAPA chamativa com badge "ACHADINHO"
2. PROBLEMA que o produto resolve
3. SOLUÇÃO (foto do produto em uso)
4. FUNCIONALIDADE 1
5. FUNCIONALIDADE 2 (surpresa)
6. PREÇO + VALOR
7. CTA: "Salva esse post! Link na bio"

Formato: 1080x1080 ou 1080x1350. Fundo escuro, texto branco/amarelo, fonte bold.
O prompt deve ser AUTOCONTIDO."""

    try:
        texto = _chamar_gemini(_SYSTEM_CARROSSEL, user)
    except Exception as exc:
        logger.error("Gemini falhou: %s", exc)
        texto = f"[ERRO GEMINI] Gere carrossel sobre {produto.nome}."

    return PromptCriativo(
        produto_id=produto.id, produto_nome=produto.nome,
        nicho=produto.nicho, preco=produto.preco, gancho=produto.gancho,
        tipo="carrossel", prompt_texto=texto,
        metadados={"formato": "1080x1080 ou 1080x1350", "fonte": "gemini"},
    )


def gerar_todos_prompts(produto: Produto) -> list[PromptCriativo]:
    prompts = []
    prompts.extend(gerar_prompt_video(produto, "reels"))
    prompts.extend(gerar_prompt_video(produto, "tiktok"))
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
    for pr in gerar_todos_prompts(p):
        print(f"\n{'='*50}\n{pr.tipo}\n{'='*50}")
        print(pr.prompt_texto[:500])
        print("..." if len(pr.prompt_texto) > 500 else "")
