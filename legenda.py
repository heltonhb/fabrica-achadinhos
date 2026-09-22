"""
legenda.py — Geração de legendas para Instagram via Gemini.

Gera legendas criativas e específicas para cada produto,
incluindo hashtags, CTA e formatação pronta pra copiar e colar.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from config import Produto
from gemini_client import _chamar_gemini

logger = logging.getLogger(__name__)


@dataclass
class LegendaInstagram:
    """Legenda formatada para Instagram."""
    texto: str
    hashtags: str
    comentario_fixo: str
    estilo: str

    @property
    def completa(self) -> str:
        return f"{self.texto}\n\n{self.hashtags}"

    @property
    def copy_paste(self) -> str:
        return self.texto


# ─── System prompts ──────────────────────────────────────────────────────────

_SYSTEM_LEGENDA = """\
Você é um especialista em marketing de conteúdo para Instagram e TikTok,
focado em "achadinhos" de marketplace (Shopee) do Brasil.

Gere legendas que:
- Sejam curtas e diretas (máximo 3-4 linhas de texto principal)
- Usem linguagem informal brasileira
- Tenham gatilho de curiosidade ou urgência
- Incluam CTA claro (comentar "QUERO", salvar, compartilhar)
- NÃO use emoji no início da legenda
- Sejam específicas pro produto (não genéricas)

Formato de saída (JSON exato):
{
  "texto": "texto da legenda",
  "hashtags": "#achadinhos #shopee #tag1 #tag2",
  "comentario_fixo": "comentário pra fixar com link"
}"""


# ─── Geração via Gemini ──────────────────────────────────────────────────────

def _gerar_legenda_gemini(produto: Produto, estilo: str) -> LegendaInstagram:
    """Gera legenda via Gemini."""
    estilo_desc = {
        "reels": "Reels/TikTok — curta, direta, com CTA de comentar QUERO",
        "carrossel": "Carrossel — mais detalhada, com checklist e engajamento",
        "feed": "Post no Feed — equilibrada, profissional mas informal",
        "stories": "Stories — muito curta, urgência, call to action rápido",
    }

    user = f"""\
Gere uma legenda para Instagram no estilo "{estilo_desc.get(estilo, estilo)}".

PRODUTO: {produto.nome}
NICHO: {produto.nicho or 'geral'}
PREÇO: R$ {produto.preco or 'XX,XX'}
GANCHO: {produto.gancho or f'Achadinho: {produto.nome}'}
LINK VITRINE: {produto.link_vitrine or 'link na bio'}

Responda APENAS com JSON válido (sem markdown):
{{
  "texto": "texto da legenda",
  "hashtags": "#achadinhos #shopee #tag1 #tag2",
  "comentario_fixo": "comentário pra fixar com link"
}}"""

    try:
        resposta = _chamar_gemini(
            _SYSTEM_LEGENDA, user, temperature=0.5, response_mime_type="application/json"
        )
        # tenta extrair JSON
        # remove markdown code block se tiver
        limpo = resposta.strip()
        if limpo.startswith("```"):
            limpo = limpo.split("\n", 1)[1]
        if limpo.endswith("```"):
            limpo = limpo.rsplit("```", 1)[0]
        limpo = limpo.strip()

        dados = json.loads(limpo)
        return LegendaInstagram(
            texto=dados.get("texto", ""),
            hashtags=dados.get("hashtags", ""),
            comentario_fixo=dados.get("comentario_fixo", ""),
            estilo=estilo,
        )
    except Exception as exc:
        logger.error("Gemini falhou na legenda: %s", exc)
        return LegendaInstagram(
            texto=f"[ERRO GEMINI] Não foi possível gerar legenda para {produto.nome}",
            hashtags="#achadinhos #shopee",
            comentario_fixo="",
            estilo=estilo,
        )


def gerar_legenda(produto: Produto, estilo: str = "reels") -> LegendaInstagram:
    """Gera legenda para o produto no estilo escolhido."""
    return _gerar_legenda_gemini(produto, estilo)


def gerar_todas_legendas(produto: Produto) -> dict[str, LegendaInstagram]:
    """Gera legendas para todos os estilos."""
    return {
        estilo: gerar_legenda(produto, estilo)
        for estilo in ["reels", "carrossel", "feed", "stories"]
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    p = Produto(
        id="#99", nome="Fones de Ouvido Bluetooth TWS",
        nicho="Tech", preco="39.90",
        gancho="Esquece os AirPods, esse custa 10x menos",
        link_vitrine="https://beacons.ai/sualoja#99",
    )
    for estilo in ["reels", "stories"]:
        leg = gerar_legenda(p, estilo)
        print(f"\n{'='*50}\n{estilo.upper()}\n{'='*50}")
        print(leg.completa)
        if leg.comentario_fixo:
            print(f"\nComentário: {leg.comentario_fixo}")
