"""
roteirista.py — Geração de roteiro de 20s via Gemini (JSON estruturado).

Estrutura rígida do roteiro (mesma do SOP do Helton):
  Gancho 3s (sem apresentador) → 2 funcionalidades (2 cortes de ~2s)
  → CTA ("comenta QUERO" / link na bio).

Saída JSON do Gemini:
  locucao            — texto exato da locução (50-60 palavras, ~17s)
  cortes             — lista com o que mostrar em cada trecho
  legenda            — caption do post no Instagram/TikTok
  hashtags           — lista de hashtags (sem #)
  comentario_fixo    — texto do comentário fixado com o link da bio
"""

from __future__ import annotations

import json
import logging
import time

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, Produto

logger = logging.getLogger(__name__)

PROMPT_ROTEIRO = """Atue como roteirista de vídeos curtos de vendas para TikTok e Reels, especialista em achadinhos de marketplace (Shopee) do Brasil.

Escreva um roteiro de exatamente 20 segundos para o produto: [NOME_DO_PRODUTO], que resolve a seguinte dor: [DOR/UTILIDADE].

O vídeo deve seguir rigorosamente esta estrutura:
1. GANCHO nos primeiros 3 segundos, sem apresentador, voz firme e direta;
2. DEMONSTRAÇÃO de duas funcionalidades práticas (cortes de 2s cada);
3. CTA para comentar "QUERO" (o link vai por DM) ou clicar no link da bio.

Regras:
- Locução em português brasileiro, informal, estilo UGC (vídeo de pessoa real mostrando achadinho), SEM emoji.
- Texto da locução com no máximo 60 palavras no total.
- Nada de "Olá, tudo bem?", sem introdução, direto ao gancho.
- Cortes visuais descrevem o que aparece na tela em cada trecho (são clipes reais do produto em uso, já baixados do anúncio do fornecedor).

Responda APENAS com um JSON válido, sem markdown, com exatamente estas chaves:
{
 "locucao": "texto exato da locução, uma frase só, sem marcações de tempo",
 "cortes": ["o que mostrar no trecho do gancho (0-3s)", "funcionalidade 1 (3-8s)", "funcionalidade 2 (8-13s)", "CTA (13-20s)"],
 "legenda": "legenda do post para Instagram Reels e TikTok, com gatilho de curiosidade e CTA de comentar QUERO",
 "hashtags": ["achadinhos", "shopee", "..."],
 "comentario_fixo": "Link do produto NN disponível no link da minha bio!"
}"""


def gerar_roteiro(produto: Produto) -> dict | None:
    """Gera roteiro JSON para o produto. Retorna dict ou None em falha total."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ausente no .env")

    dor = produto.gancho or f"utilidade de {produto.nome} no dia a dia"
    prompt = PROMPT_ROTEIRO.replace("[NOME_DO_PRODUTO]", produto.nome)
    prompt = prompt.replace("[DOR/UTILIDADE]", dor)
    prompt = prompt.replace("NN", produto.id.replace("#", ""))

    client = genai.Client(api_key=GEMINI_API_KEY)
    modelos = ["gemini-3.5-flash", "gemini-flash-latest", "gemini-2.5-flash"]

    for modelo in modelos:
        for tentativa in range(3):
            try:
                resp = client.models.generate_content(
                    model=modelo,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.8,
                    ),
                )
                texto = resp.text or ""
                if texto:
                    dados = json.loads(texto)
                    if "locucao" not in dados:
                        raise ValueError("JSON sem chave 'locucao'")
                    # garante comentário com o número do produto
                    dados["comentario_fixo"] = dados.get("comentario_fixo", "").replace(
                        "NN", produto.id.replace("#", "")
                    )
                    return dados
            except json.JSONDecodeError:
                logger.warning("JSON inválido de %s, tentando de novo", modelo)
            except Exception as exc:  # 429/5xx → backoff
                if "429" in str(exc) or "500" in str(exc) or "503" in str(exc):
                    time.sleep(2 ** tentativa * 2)
                    continue
                logger.warning("Modelo %s falhou: %s", modelo, str(exc)[:150])
                break  # próximo modelo

    return None
