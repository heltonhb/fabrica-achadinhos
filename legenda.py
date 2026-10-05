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


# ─── Gerador por Templates de Alta Conversão (Fallback Instantâneo) ──────────

def gerar_legenda_template(produto: Produto, estilo: str = "reels") -> LegendaInstagram:
    """Gera legenda de alta conversão instantaneamente usando padrões validados de achadinhos."""
    nome = produto.nome or "Achadinho Secreto"
    preco = produto.preco or "XX,XX"
    gancho = produto.gancho or f"Gente, achei esse {nome} e fiquei chocada com a qualidade!"
    link = produto.link_vitrine or "no link da bio"
    pid = produto.id or "01"
    
    # Nicho hashtags
    nicho_raw = (produto.nicho or "achadinhos").lower().replace(" ", "").replace("&", "")
    nicho_tag = f"#{nicho_raw}" if nicho_raw else "#achadinhos"
    
    hashtags_base = f"#achadinhos #achadosdashopee #shopeebrasil #comprinhas {nicho_tag} #dicas #comprasonline"

    if estilo == "shorts":
        num_clean = pid.replace("#", "")
        texto = (
            f"{gancho}\n\n"
            f"Achadinho indispensável da Shopee por apenas R$ {preco}! {nome} com custo-benefício surreal.\n\n"
            f"🛒 Link oficial com desconto no perfil do canal! É o produto #{num_clean} na nossa vitrine."
        )
        comentario = f"🛒 O link oficial desse achadinho tá fixado no perfil do canal! É o produto #{num_clean} na vitrine."
        hashtags = f"#Shorts #achadinhos #shopeebrasil #achadosdashopee #comprinhas {nicho_tag}"

    elif estilo == "carrossel":
        texto = (
            f"Passa pro lado pra ver todos os detalhes desse achadinho que viralizou! ✨\n\n"
            f"📌 {nome} — por apenas R$ {preco}\n\n"
            f"Motivos pra garantir o seu hoje:\n"
            f"✅ Custo-benefício que vale cada centavo\n"
            f"✅ Produto super bem avaliado na plataforma\n"
            f"✅ Praticidade garantida no dia a dia\n\n"
            f"👉 Comente 'QUERO' que te mando o link direto no direct! Ou pegue no link da bio."
        )
        comentario = f"Link do {nome} (Achado {pid}) 👇\n{link}"
        hashtags = f"{hashtags_base} #carrossel #reviewshopee #achadinhosreais"

    elif estilo == "feed":
        texto = (
            f"Dica de ouro pra você economizar e ter o melhor em casa: conheça o {nome}!\n\n"
            f"Preço promocional: R$ {preco} (aproveite enquanto durar o cupom).\n"
            f"A qualidade surpreende e entrega muito mais do que promete.\n\n"
            f"🔗 Link direto no link da nossa bio ou comente 'LINK' abaixo que te enviamos na hora!"
        )
        comentario = f"Comente LINK para receber o cupom exclusivo do {nome}!"
        hashtags = f"{hashtags_base} #ofertas #descontos #feed #achados"

    elif estilo == "stories":
        texto = (
            f"ALERTA PROMOÇÃO RELÂMPAGO! 🔥\n\n"
            f"{nome} por apenas R$ {preco}!\n"
            f"Restam poucas unidades com esse valor no estoque.\n\n"
            f"Arrasta pra cima ou responda com 'QUERO' pra receber o link agora!"
        )
        comentario = f"Link rápido: {link}"
        hashtags = f"{hashtags_base} #promocao #achadinho #urgente"

    else:  # reels / tiktok (padrão)
        texto = (
            f"{gancho}\n\n"
            f"Esse {nome} foi um dos melhores que já peguei na Shopee, custando apenas R$ {preco}. "
            f"Resolve de verdade e o custo-benefício é surreal!\n\n"
            f"🔥 Comente 'QUERO' que te envio o link direto no seu direct agora mesmo! 👇"
        )
        comentario = f"Link oficial aqui! 👇 {link} (Achado {pid})"
        hashtags = f"{hashtags_base} #reelsbrasil #tiktokbrasil #achadinhosvirais"

    return LegendaInstagram(
        texto=texto,
        hashtags=hashtags,
        comentario_fixo=comentario,
        estilo=estilo,
    )


# ─── Geração via Gemini ──────────────────────────────────────────────────────

def _gerar_legenda_gemini(produto: Produto, estilo: str) -> LegendaInstagram:
    """Gera legenda via Gemini com fallback automático para template."""
    estilo_desc = {
        "shorts": "YouTube Shorts — gancho rápido, link no perfil do canal e código na vitrine, hashtags com #Shorts",
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
        limpo = resposta.strip()
        if limpo.startswith("```"):
            limpo = limpo.split("\n", 1)[1]
        if limpo.endswith("```"):
            limpo = limpo.rsplit("```", 1)[0]
        limpo = limpo.strip()

        dados = json.loads(limpo)
        texto = dados.get("texto", "").strip()
        if not texto:
            raise ValueError("Resposta Gemini não continha campo texto válido")
            
        return LegendaInstagram(
            texto=texto,
            hashtags=dados.get("hashtags", "").strip() or "#achadinhos #shopee",
            comentario_fixo=dados.get("comentario_fixo", "").strip() or f"Link na bio (Achado {produto.id})",
            estilo=estilo,
        )
    except Exception as exc:
        logger.warning("Gemini falhou na legenda (%s) — acionando template otimizado", exc)
        return gerar_legenda_template(produto, estilo)


def gerar_legenda(produto: Produto, estilo: str = "reels") -> LegendaInstagram:
    """Gera legenda para o produto no estilo escolhido."""
    return _gerar_legenda_gemini(produto, estilo)


def gerar_todas_legendas(produto: Produto) -> dict[str, LegendaInstagram]:
    """Gera legendas para todos os estilos."""
    return {
        estilo: gerar_legenda(produto, estilo)
        for estilo in ["shorts", "reels", "carrossel", "feed", "stories"]
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
