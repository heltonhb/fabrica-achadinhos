"""
metricas.py — Memória de desempenho dos posts para melhorar prompts futuros.

Fluxo:
  1. Após postar, preencha as métricas no app (tab 📊 Desempenho).
  2. metricas.py calcula a nota composta de cada post.
  3. prompts.py / roteirista.py chamam `obter_exemplos()` e injetam os
     melhores posts como few-shot examples no prompt do Gemini.

Nota composta (0–100):
  - Comentários "QUERO"  → peso 50%  (principal KPI de conversão)
  - Salvamentos          → peso 30%  (sinal de conteúdo valioso)
  - Alcance              → peso 20%  (distribuição orgânica)
  - Nota manual          → bônus/penalidade de até ±10 pontos (escala 1–5)

Posts sem nenhuma métrica preenchida são ignorados no ranking.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Produto

logger = logging.getLogger(__name__)

# Pesos da nota composta (devem somar 1.0)
_PESO_QUERO = 0.50
_PESO_SALV  = 0.30
_PESO_ALC   = 0.20

# Quantos exemplos injetar por padrão nos prompts
EXEMPLOS_PADRAO = 3


@dataclass
class PostComDesempenho:
    """Um post com métricas já calculadas."""
    produto_id: str
    produto_nome: str
    nicho: str
    gancho: str
    locucao: str          # locução real do roteiro gerado
    legenda: str          # legenda usada no post
    estilo: str           # estilo/persona usado
    comentarios_quero: int
    alcance: int
    salvamentos: int
    nota_manual: float    # 1–5 (0 = não preenchida)
    nota_composta: float  # 0–100, calculada


def _int(v: str) -> int:
    """Converte string para int, retorna 0 em falha."""
    try:
        return max(0, int(str(v).strip().replace(".", "").replace(",", "")))
    except (ValueError, TypeError):
        return 0


def _float(v: str) -> float:
    try:
        return float(str(v).strip().replace(",", "."))
    except (ValueError, TypeError):
        return 0.0


def calcular_nota(
    comentarios_quero: int,
    alcance: int,
    salvamentos: int,
    nota_manual: float,
    *,
    max_quero: int = 500,
    max_alc: int = 50_000,
    max_salv: int = 1_000,
) -> float:
    """Calcula nota composta 0–100.

    Os máximos são usados para normalização. Ajuste conforme seu nicho crescer.
    """
    score_quero = min(comentarios_quero / max(max_quero, 1), 1.0) * 100
    score_alc   = min(alcance          / max(max_alc,   1), 1.0) * 100
    score_salv  = min(salvamentos      / max(max_salv,  1), 1.0) * 100

    nota = (
        score_quero * _PESO_QUERO
        + score_salv  * _PESO_SALV
        + score_alc   * _PESO_ALC
    )

    # bônus/penalidade da nota manual (1–5 → -10 a +10 pontos)
    if 1.0 <= nota_manual <= 5.0:
        nota += (nota_manual - 3.0) * 5.0   # 3 = neutro, 5 = +10, 1 = -10

    return round(min(max(nota, 0.0), 100.0), 1)


def listar_posts_com_metricas(produtos: "list[Produto]") -> list[PostComDesempenho]:
    """Converte a lista de Produto em PostComDesempenho, filtrando os sem métricas."""
    resultado = []
    for p in produtos:
        quero = _int(p.comentarios_quero)
        alc   = _int(p.alcance)
        salv  = _int(p.salvamentos)
        nota  = _float(p.nota_manual)

        # ignora posts sem nenhuma métrica
        if quero == 0 and alc == 0 and salv == 0 and nota == 0:
            continue

        # tenta ler locução e estilo do roteiro salvo
        locucao = ""
        legenda = ""
        estilo  = ""
        arq_roteiro = p.pasta / "roteiro.json"
        if arq_roteiro.exists():
            try:
                r = json.loads(arq_roteiro.read_text(encoding="utf-8"))
                locucao = r.get("locucao", "")
                legenda = r.get("legenda", "")
                estilo  = r.get("_meta", {}).get("estilo", "")
            except Exception:
                pass

        # tenta ler estilo do gancho.json se não veio do roteiro
        if not estilo:
            arq_gancho = p.pasta / "gancho.json"
            if arq_gancho.exists():
                try:
                    estilo = json.loads(
                        arq_gancho.read_text(encoding="utf-8")
                    ).get("estilo", "")
                except Exception:
                    pass

        nota_comp = calcular_nota(quero, alc, salv, nota)

        resultado.append(PostComDesempenho(
            produto_id=p.id,
            produto_nome=p.nome,
            nicho=p.nicho,
            gancho=p.gancho,
            locucao=locucao,
            legenda=legenda,
            estilo=estilo,
            comentarios_quero=quero,
            alcance=alc,
            salvamentos=salv,
            nota_manual=nota,
            nota_composta=nota_comp,
        ))

    return sorted(resultado, key=lambda x: x.nota_composta, reverse=True)


def obter_exemplos(
    produtos: "list[Produto]",
    n: int = EXEMPLOS_PADRAO,
    nicho: str | None = None,
) -> list[PostComDesempenho]:
    """Retorna os N melhores posts para usar como few-shot examples.

    Args:
        produtos: Lista completa de produtos da planilha.
        n: Quantos exemplos retornar.
        nicho: Se informado, prioriza posts do mesmo nicho; completa com outros.
    """
    todos = listar_posts_com_metricas(produtos)

    if not todos:
        return []

    if nicho:
        mesmo_nicho = [p for p in todos if nicho.lower() in p.nicho.lower()]
        outros       = [p for p in todos if p not in mesmo_nicho]
        candidatos   = (mesmo_nicho + outros)[:n]
    else:
        candidatos = todos[:n]

    logger.info(
        "Few-shot: %d exemplos disponíveis, retornando %d (nicho=%s)",
        len(todos), len(candidatos), nicho or "todos",
    )
    return candidatos


def formatar_exemplos_para_prompt(exemplos: list[PostComDesempenho]) -> str:
    """Formata os exemplos em texto pronto para injetar no prompt do Gemini."""
    if not exemplos:
        return ""

    linhas = [
        "EXEMPLOS DE POSTS QUE PERFORMARAM BEM (use como referência de tom e estrutura):",
        "",
    ]
    for i, ex in enumerate(exemplos, 1):
        linhas += [
            f"── Exemplo {i} (nota {ex.nota_composta}/100, {ex.comentarios_quero} 'QUERO', {ex.salvamentos} salvamentos) ──",
            f"Produto: {ex.produto_nome} | Nicho: {ex.nicho}",
            f"Gancho: {ex.gancho}",
        ]
        if ex.locucao:
            linhas.append(f"Locução: {ex.locucao}")
        if ex.legenda:
            linhas.append(f"Legenda: {ex.legenda[:120]}{'...' if len(ex.legenda) > 120 else ''}")
        linhas.append("")

    linhas.append("Agora gere para o produto abaixo seguindo o mesmo padrão de qualidade:")
    return "\n".join(linhas)
