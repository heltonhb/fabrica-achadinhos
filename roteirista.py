"""
roteirista.py — Geração de gancho e ROTEIRO DE REFERÊNCIA (em português) via Gemini.

CONTRATO DE PROMPTS — ver prompts.py:
  - Este módulo gera ROTEIRO DE REFERÊNCIA em português para o produto.
    Ele NÃO é o prompt que vai para o Google Vids / gerador externo.
  - O prompt de vídeo autocontido (em inglês, com descrição de cena) é
    gerado por prompts.py e entregue na seção Gerar Prompt do app.

Fluxo recomendado:
  1. gerar_ganchos(produto)  → 3 opções de gancho para o usuário escolher
  2. gerar_roteiro(produto)  → roteiro JSON de referência (PT)
     Se produto.gancho já estiver preenchido (pelo usuário ou pelo passo 1),
     o roteiro o usa como âncora criativa.
     Se clipes estiverem disponíveis em Midias/, o Gemini adapta os cortes
     ao material real.

Saída JSON do roteiro de referência:
  locucao            — texto sugerido da locução (60-66 palavras, ~19s a 3,5 pal/s)
  cortes             — lista descrevendo o que mostrar em cada trecho
  texto_na_tela      — 1 a 3 palavras por beat, palavra-chave em amarelo
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
Atue como roteirista de vídeos curtos de vendas para YouTube Shorts, TikTok e Instagram Reels,
especialista em achadinhos de marketplace (Shopee) do Brasil.
Seu foco é retenção máxima (gancho em 2s, pattern interrupt no meio, loop visual) e conversão direta para o link do perfil/canal.
Responda APENAS com JSON válido, sem markdown, sem texto extra."""

_SYSTEM_GANCHOS = """\
Você é um copywriter especialista em vídeos curtos de "achadinhos" para TikTok e Reels.
Seu trabalho é criar GANCHOS de abertura — a primeira frase falada, nos 2 primeiros segundos do vídeo.

Regras do gancho:
- Máximo 6 palavras
- Sem apresentação ("Olá", "Ei pessoal", etc.)
- Voz direta e firme, como quem acabou de descobrir algo incrível
- Deve gerar curiosidade ou apontar uma dor imediata
- Tem que caber nos 2 primeiros segundos do vídeo
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
Código do produto / ID: #{num}
Preço: R$ {preco}
Dor / utilidade principal: {dor}
Estilo/persona do vídeo: {estilo_label} — {estilo_desc}
{secao_clipes}
O vídeo deve seguir esta estrutura, com o orçamento de palavras POR TRECHO:

1. GANCHO 0:00–0:02 — use exatamente: "{gancho}" (no máximo 6 palavras)
2. PRODUTO EM USO 0:02–0:07 — mostra o resultado, não a embalagem (no máximo 16 palavras)
3. CORTINA (pattern interrupt) 0:07–0:08 — corte seco ou zoom rápido no produto, SEM voz
4. GANCHO ABERTO 0:08–0:10 — deixa uma pergunta sem resposta que a Parte 2 responde (no máximo 10 palavras)
5. USO INUSITADO 0:11–0:16 — o momento "wow" (no máximo 18 palavras)
6. PREÇO 0:16–0:18 — o número dito com clareza (no máximo 8 palavras)
{instrucao_cta_loop}

Adapte ritmo, vocabulário e tom à persona acima sem violar as regras de formato.

Regras:
- Locução em português brasileiro, informal, estilo UGC, SEM emoji
- Ritmo acelerado de conversa: cerca de 3,5 palavras por segundo
- Total entre 60 e 66 palavras — abaixo de 60 sobra tempo morto, acima de 66 o vídeo passa de 20s
- Sem introdução ("Olá", "Ei pessoal"), direto ao gancho
- O gancho cai em até 2 segundos: o primeiro frame já mostra movimento, sem pose parada
{instrucao_clipes}
Responda com exatamente este JSON:
{{
 "locucao": "texto completo da locução (60-66 palavras), começando pelo gancho e terminando com a frase de CTA que cita o código #{num} em voz alta",
 "cortes": ["gancho (0-2s)", "produto em uso (2-7s)", "cortina sem voz (7-8s)", "gancho aberto (8-10s)", "uso inusitado (11-16s)", "preço (16-18s)", "CTA e loop (18-20s)"],
 "texto_na_tela": ["1 a 3 palavras no máximo, palavra-chave em amarelo", "corte 2", "corte 3", "R$ {preco}", "corte 5", "corte 6", "🔗 Link no perfil"],
 "titulos_shorts": [
   "Título curto 1 para Shorts com gancho (máx 40 carac)",
   "Título curto 2 focado em curiosidade, sem #Shorts (máx 40 carac)",
   "Título curto 3 com preço (máx 40 carac)"
 ],
 "legenda": "legenda para Instagram Reels e TikTok com gatilho de curiosidade e CTA de comentar QUERO",
 "hashtags": ["achadinhos", "shopee", "comprinhas"],
 "comentario_fixo_shorts": "🛒 Tá no perfil do canal! Procura o achadinho #{num} — é esse aqui.",
 "comentario_fixo": "Link do produto #{num} disponível no perfil/bio!"
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
        if isinstance(dados, list):
            ganchos_brutos = dados
        elif isinstance(dados, dict):
            ganchos_brutos = dados.get("ganchos", [])
            if not ganchos_brutos and "texto" in dados:
                ganchos_brutos = [dados]
        else:
            ganchos_brutos = []

        if not ganchos_brutos or not isinstance(ganchos_brutos, list):
            raise ValueError("JSON sem chave 'ganchos' ou vazia")

        angulos_padrao = ["dor", "surpresa", "economia"]
        ganchos = []
        for idx, g in enumerate(ganchos_brutos):
            if isinstance(g, dict):
                angulo = str(g.get("angulo") or angulos_padrao[idx % len(angulos_padrao)]).strip().lower()
                texto_g = str(g.get("texto") or "").strip()
                explicacao = str(g.get("explicacao") or "").strip()
                if texto_g:
                    ganchos.append({"angulo": angulo, "texto": texto_g, "explicacao": explicacao})
            elif isinstance(g, str) and g.strip():
                ganchos.append({
                    "angulo": angulos_padrao[idx % len(angulos_padrao)],
                    "texto": g.strip(),
                    "explicacao": "",
                })

        if not ganchos:
            raise ValueError("Nenhum gancho válido encontrado na resposta do Gemini")

        logger.info("Gerados %d ganchos para %s", len(ganchos), produto.id)
        return ganchos
    except json.JSONDecodeError as exc:
        logger.warning("JSON inválido ao gerar ganchos: %s", exc)
    except Exception as exc:
        logger.error("Gemini falhou ao gerar ganchos para %s: %s", produto.id, exc)

    return []


def gerar_roteiro(produto: Produto, estilo: str = "chocante", loop_infinito: bool = True) -> dict | None:
    """Gera roteiro JSON para o produto.

    Se ``produto.gancho`` estiver preenchido, usa-o como âncora.
    Se existirem clipes em ``produto.pasta_clipes``, passa a lista ao Gemini
    para que os cortes sejam adaptados ao material real disponível.
    ``estilo`` é a persona de ``prompts.ESTILOS`` e entra no prompt do Gemini.
    ``loop_infinito`` se True ativa técnica de seamless loop conectando o final ao gancho.

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

    if loop_infinito:
        instrucao_cta_loop = (
            "7. CTA e LOOP nos últimos 2 segundos (18-20s):\n"
            f"   - YouTube Shorts: use EXATAMENTE esta frase, sem improvisar: "
            f'"Vai pro perfil e procura o {num}. É esse aqui." '
            f"O número {num} precisa ser falado em voz alta, devagar e separado do resto da frase, "
            f"porque é assim que o espectador acha o produto exato na vitrine depois.\n"
            f"   - NUNCA escreva português estranho sobre o link. 'Garantir o link', 'garanta seu link' e "
            f"'adquira o seu link' estão ERRADOS — ninguém garante nem adquire um link, ele se procura. "
            f"Link é 'no perfil', 'tá fixado', 'procure'.\n"
            f"   - Texto na tela no CTA: 'Achadinho {num}' + '🔗 Link no perfil do canal'.\n"
            "   - LOOP VISUAL (Seamless Loop): o ÚLTIMO FRAME deve reenquadrar exatamente o PRIMEIRO FRAME — mesmo ângulo, "
            "mesma posição do produto, mesma luz — como se o vídeo nunca tivesse parado. A locução fecha com uma frase CURTA E COMPLETA, "
            "NUNCA em conectivo gramatical aberto (nada de 'e é exatamente por isso que...', 'então corre no perfil porque...') "
            "nem despedida ('tchau', 'curta e compartilha'). O rewatch é carregado pelo QUADRO, não pela frase."
        )
    else:
        instrucao_cta_loop = (
            "7. CTA nos últimos 2 segundos (18-20s):\n"
            f"   - Use exatamente: 'Vai pro perfil e procura o {num}. É esse aqui.' "
            f"O número {num} é obrigatório, falado devagar e separado do resto da frase."
        )

    user_prompt = _USER_ROTEIRO.format(
        nome=produto.nome,
        preco=produto.preco or "XX,XX",
        dor=dor,
        gancho=gancho,
        num=num,
        estilo_label=estilo_label,
        estilo_desc=estilo_desc,
        secao_clipes=secao_clipes,
        instrucao_clipes=instrucao_clipes,
        instrucao_cta_loop=instrucao_cta_loop,
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
            dados["comentario_fixo"] = str(dados["comentario_fixo"]).replace("NN", num)
        else:
            dados["comentario_fixo"] = f"Link do produto #{num} disponível no link do perfil!"

        # Garante campos para Shorts e texto na tela se a IA omitir
        if not dados.get("comentario_fixo_shorts"):
            dados["comentario_fixo_shorts"] = (
                f"🛒 Tá no perfil do canal! Procura o achadinho {num} — é esse aqui."
            )
        if not dados.get("titulos_shorts"):
            dados["titulos_shorts"] = [
                f"Esse achadinho me surpreendeu! #{num}",
                f"Não compre #{num} antes de ver isso",
                f"Achadinho por R$ {produto.preco or 'XX'} — vale ver",
            ]
        if not dados.get("texto_na_tela"):
            dados["texto_na_tela"] = [
                "🔥 ACHADINHO",
                "Olha isso",
                f"R$ {produto.preco or 'XX,XX'}",
                "🔗 Link no perfil",
            ]

        # mede a locução contra o orçamento de 20s (~3,5 palavras/s)
        palavras = len(str(dados["locucao"]).split())
        if palavras > 75:
            logger.warning(
                "Locução de %s tem %d palavras (~%.0fs em 3,5 w/s): acima do orçamento de 20s",
                produto.id, palavras, palavras / 3.5,
            )
        elif palavras < 45:
            logger.warning(
                "Locução de %s tem só %d palavras (~%.0fs): sobra tempo morto no vídeo",
                produto.id, palavras, palavras / 3.5,
            )

        # registra se foi gerado com clipes reais, estilo usado e técnica de loop
        dados["_meta"] = {
            "com_clipes": bool(clipes),
            "n_clipes": len(clipes),
            "estilo": estilo,
            "loop_infinito": loop_infinito,
            "palavras_locucao": palavras,
        }
        return dados
    except json.JSONDecodeError as exc:
        logger.warning("JSON inválido do Gemini: %s", exc)
    except Exception as exc:
        logger.error("Gemini falhou ao gerar roteiro para %s: %s", produto.id, exc)

    return None
