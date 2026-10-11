"""
analytics.py — Painel de métricas da vitrine via API do GoatCounter.

A vitrine (vitrine/index.html, gerada por scripts/gerar_vitrine.py) envia
eventos ao GoatCounter: clique no CTA por produto, busca (com/sem resultado),
filtro de nicho e visita via in-app browser. Este módulo lê esses dados de
volta pela API oficial (/api/v0) e devolve um resumo pronto pra exibir.

Configuração (via .env / variáveis de ambiente / secrets):
  GOATCOUNTER_API_TOKEN  token gerado em goatcounter.com (usuário → API)
  GOATCOUNTER_CODE       code do site (padrão: helton)

Uso:
    from analytics import estatisticas_vitrine
    resumo = estatisticas_vitrine(dias=30)
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any

import requests

from config import obter_segredo

logger = logging.getLogger(__name__)

# Cache em memória pra não bater na API a cada clique no app
_CACHE: dict[tuple[int, int], tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SEGUNDOS = 60


class ErroAnalytics(Exception):
    """Erro amigável do painel de métricas (token, rede, API)."""


def codigo_site() -> str:
    """Code do GoatCounter (mesmo usado na vitrine)."""
    return (obter_segredo("GOATCOUNTER_CODE") or "helton").strip() or "helton"


def _url_base() -> str:
    return f"https://{codigo_site()}.goatcounter.com/api/v0"


def _token() -> str:
    return obter_segredo("GOATCOUNTER_API_TOKEN").strip()


def _periodo(dias: int) -> tuple[str, str]:
    """Período (início, fim) em ISO, como a API espera."""
    hoje = dt.datetime.now()
    inicio = hoje - dt.timedelta(days=max(1, dias))
    return inicio.strftime("%Y-%m-%d"), hoje.strftime("%Y-%m-%d")


def _get(caminho: str, params: dict[str, Any], _tentativa: int = 0) -> dict[str, Any]:
    """GET autenticado na API do GoatCounter. Levanta ErroAnalytics amigável.

    Erros transitórios (404/429/5xx do edge) são retentados uma vez.
    """
    token = _token()
    if not token:
        raise ErroAnalytics(
            "Token do GoatCounter não configurado. Gere em goatcounter.com "
            "(usuário → API) e salve em GOATCOUNTER_API_TOKEN no .env."
        )
    try:
        resp = requests.get(
            f"{_url_base()}/{caminho}",
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise ErroAnalytics(f"Sem conexão com o GoatCounter: {exc}") from exc

    if resp.status_code in (404, 429, 500, 502, 503, 504) and _tentativa < 1:
        logger.warning("GoatCounter %s em /%s — tentando de novo", resp.status_code, caminho)
        time.sleep(1.5)
        return _get(caminho, params, _tentativa + 1)

    if resp.status_code == 401:
        raise ErroAnalytics(
            "Token do GoatCounter inválido ou expirado. Gere um novo em "
            "goatcounter.com (usuário → API) e atualize GOATCOUNTER_API_TOKEN."
        )
    if resp.status_code >= 400:
        raise ErroAnalytics(
            f"GoatCounter retornou {resp.status_code} em /{caminho}: {resp.text[:200]}"
        )

    try:
        return resp.json()
    except ValueError as exc:
        raise ErroAnalytics(f"Resposta ilegível do GoatCounter em /{caminho}") from exc


# ─── Parsing (puro, testável sem rede) ────────────────────────────────────────

def decompor_evento_cta(caminho: str) -> tuple[str, str] | None:
    """'/cta/grade/20' → ('grade', '20'). None se não for evento de CTA."""
    partes = (caminho or "").strip().split("/")
    # '', 'cta', '{posição}', '{id}'
    if len(partes) >= 4 and partes[1] == "cta" and partes[2] and partes[3]:
        return partes[2], partes[3]
    return None


def resumir_hits(hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrega a lista de paths do GoatCounter no resumo do painel."""
    resumo: dict[str, Any] = {
        "visualizacoes": 0,          # página da vitrine ("/")
        "visitantes": 0,
        "cliques_cta": 0,
        "visitas_inapp": 0,
        "buscas_ok": 0,
        "buscas_sem_resultado": 0,
        "produtos_clicados": [],     # [{id, posicao, cliques}]
        "buscas_falhas": [],         # [{termo, buscas}]
        "filtros": [],               # [{nicho, cliques}]
    }

    produtos: dict[tuple[str, str], int] = {}
    falhas: dict[str, int] = {}
    filtros: dict[str, int] = {}

    for hit in hits or []:
        caminho = (hit.get("path") or "").strip()
        contagem = int(hit.get("count") or 0)

        if caminho in ("/", "/index.html"):
            resumo["visualizacoes"] += int(hit.get("count_raw") or contagem)
            resumo["visitantes"] += contagem
            continue

        cta = decompor_evento_cta(caminho)
        if cta:
            posicao, pid = cta
            resumo["cliques_cta"] += contagem
            chave = (pid, posicao)
            produtos[chave] = produtos.get(chave, 0) + contagem
            continue

        if caminho.startswith("/busca/sem-resultado/"):
            resumo["buscas_sem_resultado"] += contagem
            termo = caminho.split("/busca/sem-resultado/", 1)[1]
            falhas[termo] = falhas.get(termo, 0) + contagem
            continue

        if caminho.startswith("/busca/ok/"):
            resumo["buscas_ok"] += contagem
            continue

        if caminho.startswith("/filtro/"):
            nicho = caminho.split("/filtro/", 1)[1]
            filtros[nicho] = filtros.get(nicho, 0) + contagem
            continue

        if caminho.startswith("/inapp/visita-inapp"):
            resumo["visitas_inapp"] += contagem

    resumo["produtos_clicados"] = [
        {"id": pid, "posicao": posicao, "cliques": cliques}
        for (pid, posicao), cliques in sorted(produtos.items(), key=lambda kv: -kv[1])
    ]
    resumo["buscas_falhas"] = [
        {"termo": termo, "buscas": n}
        for termo, n in sorted(falhas.items(), key=lambda kv: -kv[1])
    ]
    resumo["filtros"] = [
        {"nicho": nicho, "cliques": n}
        for nicho, n in sorted(filtros.items(), key=lambda kv: -kv[1])
    ]
    return resumo


# ─── API pública ──────────────────────────────────────────────────────────────

def estatisticas_vitrine(dias: int = 30, limite: int = 200, usar_cache: bool = True) -> dict[str, Any]:
    """Resumo de métricas da vitrine para exibição no app.

    Levanta ErroAnalytics quando o token está ausente/inválido ou sem rede.
    """
    dias = max(1, int(dias))
    chave_cache = (dias, limite)
    import time

    if usar_cache:
        entrada = _CACHE.get(chave_cache)
        if entrada and time.time() - entrada[0] < _CACHE_TTL_SEGUNDOS:
            return {**entrada[1], "cache": True}

    inicio, fim = _periodo(dias)
    # A API espera horários arredondados à hora; janela cobre o fuso local (-3).
    inicio = f"{inicio}T00:00:00Z"
    fim_dt = dt.datetime.now() + dt.timedelta(hours=2)
    fim = fim_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    dados_total = _get("stats/total", {"start": inicio, "end": fim})
    dados_hits = _get(
        "stats/hits",
        {"start": inicio, "end": fim, "limit": limite, "group": "day"},
    )
    dados_refs = _get("stats/toprefs", {"start": inicio, "end": fim, "limit": 10})

    resumo = resumir_hits(dados_hits.get("hits") or [])
    resumo["visitas_total_periodo"] = int(dados_total.get("total") or 0)
    resumo["eventos_total_periodo"] = int(dados_total.get("total_events") or 0)
    resumo["referrers"] = [
        {"url": (ref.get("path") or "").strip(), "visitas": int(ref.get("count") or 0)}
        for ref in (dados_refs.get("stats") or [])
        if (ref.get("path") or "").strip()
    ]

    visitas = resumo["visitantes"]
    resumo["ctr_pct"] = (
        round(100.0 * resumo["cliques_cta"] / visitas, 1) if visitas else 0.0
    )
    resumo["periodo"] = {"inicio": inicio[:10], "fim": fim[:10], "dias": dias}
    resumo["site"] = codigo_site()
    resumo["cache"] = False

    _CACHE[chave_cache] = (time.time(), resumo)
    return resumo


def limpar_cache() -> None:
    """Esquece o cache (útil após mudar período/token)."""
    _CACHE.clear()
