"""
roteirista.py — Geração de gancho e roteiro de 20s via Gemini (JSON estruturado).

Fluxo recomendado:
  1. gerar_ganchos(produto)  → 3 opções de gancho para o usuário escolher
  2. gerar_roteiro(produto)  → roteiro JSON completo
     Se produto.gancho já estiver preenchido (pelo usuário ou pelo passo 1),
     o roteiro o usa como âncora criativa.
     Se clipes estiverem disponíveis em Midias/, o Gemini adapta os cortes
     ao material real.

Saída JSON do roteiro:
  locucao            — texto exato da locução (≤60 palavras, ~17s)
  cortes             — lista descrevendo o que mostrar em cada trecho
  legenda            — caption para Instagram Reels / TikTok
  hashtags           — lista de hashtags (sem #)
  comentario_fixo    — comentário fixado com link da bio
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from config import Produto
from gemini_client import _chamar_gemini
from prompts import ESTILOS

logger = logging.getLogger(__name__)

# ─── System prompts ───────────────────────────────────────────────────────────

_SYSTEM_ROTEIRO = """\
Atue como roteirista de vídeos curtos de vendas para TikTok e Reels,
especialista em achadinhos de marketplace (Shopee) do Brasil.
Responda APENAS com JSON válido, sem markdown, sem texto extra."""

_SYSTEM_GANCHOS = """\
Você é um copywriter especialista em vídeos curtos de "achadinhos" para TikTok e Reels.
Seu trabalho é criar GANCHOS de abertura de 3 segundos — a primeira frase falada no vídeo.

Regras do gancho:
- Máximo 10 palavras
- Sem apresentação ("Olá", "Ei pessoal", etc.)
- Voz direta e firme, como quem acabou de descobrir algo incrível
- Deve gerar curiosidade ou apontar uma dor imediata
- Português brasileiro informal, SEM emoji
- Cada opção deve ter um ÂNGULO diferente (ex: dor, surpresa, comparação, economia)

Responda APENAS com JSON válido."""

# ─── Templates ────────────────────────────────────────────────────────────────

_USER_GANCHOS = """\
Gere 3 opções de gancho para o vídeo do produto: {nome}
Nicho: {nicho}
Preço: R$ {preco}

Ângulos obrigatoriamente diferentes entre si:
- Um focado na DOR que o produto resolve
- Um focado na SURPRESA / "não sabia que isso existia"
- Um focado em ECONOMIA / comparação com alternativa mais cara

Responda com este JSON:
{{
  "ganchos": [
    {{"angulo": "dor",      "texto": "...", "explicacao": "por que este gancho funciona"}},
    {{"angulo": "surpresa", "texto": "...", "explicacao": "por que este gancho funciona"}},
    {{"angulo": "economia", "texto": "...", "explicacao": "por que este gancho funciona"}}
  ]
}}"""

_USER_ROTEIRO = """\
Escreva um roteiro de exatamente 20 segundos para o produto: {nome}
Dor / utilidade principal: {dor}
Estilo/persona do vídeo: {estilo_label} — {estilo_desc}
{secao_clipes}
O vídeo deve seguir esta estrutura:
1. GANCHO nos primeiros 3 segundos — use exatamente: "{gancho}"
2. DEMONSTRAÇÃO de duas funcionalidades práticas
3. CTA: comentar "QUERO" para receber o link por DM

Adapte ritmo, vocabulário e tom à persona acima sem violar as regras de formato.

Regras:
- Locução em português brasileiro, informal, estilo UGC, SEM emoji
- Máximo 60 palavras no total
- Sem introdução ("Olá", "Ei pessoal"), direto ao gancho
{instrucao_clipes}
Responda com exatamente este JSON:
{{
 "locucao": "texto completo da locução, sem marcações de tempo",
 "cortes": ["gancho (0-3s)", "funcionalidade 1 (3-8s)", "funcionalidade 2 (8-13s)", "CTA (13-20s)"],
 "legenda": "legenda para Instagram Reels e TikTok com gatilho de curiosidade e CTA de comentar QUERO",
 "hashtags": ["achadinhos", "shopee"],
 "comentario_fixo": "Link do produto {num} disponível no link da minha bio!"
}}"""


# ─── Funções públicas ─────────────────────────────────────────────────────────

def gerar_ganchos(produto: Produto) -> list[dict]:
    """Gera 3 opções de gancho via Gemini para o usuário escolher.

    Retorna lista de dicts com keys: angulo, texto, explicacao.
    Em caso de falha, retorna lista vazia.
    """
    user_prompt = _USER_GANCHOS.format(
        nome=produto.nome,
        nicho=produto.nicho or "geral",
        preco=produto.preco or "XX,XX",
    )

    try:
        texto = _chamar_gemini(
            system_prompt=_SYSTEM_GANCHOS,
            user_prompt=user_prompt,
            temperature=0.9,          # ganchos pedem máxima criatividade
            response_mime_type="application/json",
        )
        dados = json.loads(texto)
        ganchos = dados.get("ganchos", [])
        if not ganchos or not isinstance(ganchos, list):
            raise ValueError("JSON sem chave 'ganchos' ou vazia")
        logger.info("Gerados %d ganchos para %s", len(ganchos), produto.id)
        return ganchos
    except json.JSONDecodeError as exc:
        logger.warning("JSON inválido ao gerar ganchos: %s", exc)
    except Exception as exc:
        logger.error("Gemini falhou ao gerar ganchos para %s: %s", produto.id, exc)

    return []


def gerar_roteiro(produto: Produto, estilo: str = "chocante") -> dict | None:
    """Gera roteiro JSON para o produto.

    Se ``produto.gancho`` estiver preenchido, usa-o como âncora.
    Se existirem clipes em ``produto.pasta_clipes``, passa a lista ao Gemini
    para que os cortes sejam adaptados ao material real disponível.
    ``estilo`` é a persona de ``prompts.ESTILOS`` e entra no prompt do Gemini.

    Retorna dict ou None em falha total.
    """
    dor = produto.gancho or f"utilidade de {produto.nome} no dia a dia"
    gancho = produto.gancho or f"Esse produto vai mudar sua rotina"
    num = produto.id.replace("#", "")
    estilo_info = ESTILOS.get(estilo, ESTILOS["chocante"])
    estilo_label = estilo_info["label"]
    estilo_desc = estilo_info["descricao"]

    # ── Clipes disponíveis ───────────────────────────────────────────────────
    clipes = produto.clipes()
    if clipes:
        nomes = [c.name for c in clipes]
        secao_clipes = (
            f"Clipes disponíveis (arquivos reais que serão usados na edição):\n"
            + "\n".join(f"  - {n}" for n in nomes)
            + "\n\n"
        )
        instrucao_clipes = (
            "- Cada corte descrito deve referenciar UM dos clipes listados acima "
            "pelo nome do arquivo (ex: 'clipe2.mp4 — mostrar...')\n"
            "- Não invente cenas que não existem nos clipes disponíveis\n"
        )
        logger.info("Roteiro com %d clipes disponíveis para %s", len(clipes), produto.id)
    else:
        secao_clipes = ""
        instrucao_clipes = "- Descreva cortes visuais genéricos para cada trecho\n"

    user_prompt = _USER_ROTEIRO.format(
        nome=produto.nome,
        dor=dor,
        gancho=gancho,
        num=num,
        estilo_label=estilo_label,
        estilo_desc=estilo_desc,
        secao_clipes=secao_clipes,
        instrucao_clipes=instrucao_clipes,
    )

    try:
        texto = _chamar_gemini(
            system_prompt=_SYSTEM_ROTEIRO,
            user_prompt=user_prompt,
            temperature=0.8,
            response_mime_type="application/json",
        )
        dados = json.loads(texto)
        if "locucao" not in dados:
            raise ValueError("JSON sem chave 'locucao'")
        if "comentario_fixo" in dados:
            dados["comentario_fixo"] = dados["comentario_fixo"].replace("NN", num)
        # registra se foi gerado com clipes reais e o estilo usado
        dados["_meta"] = {
            "com_clipes": bool(clipes),
            "n_clipes": len(clipes),
            "estilo": estilo,
        }
        return dados
    except json.JSONDecodeError as exc:
        logger.warning("JSON inválido do Gemini: %s", exc)
    except Exception as exc:
        logger.error("Gemini falhou ao gerar roteiro para %s: %s", produto.id, exc)

    return None
