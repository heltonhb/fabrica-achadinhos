"""
painel/api/index.py — Mini-app de métricas da vitrine (GoatCounter) pra celular.

Projeto Vercel SEPARADO (Settings → Root Directory: `painel`). O build copia
`../analytics.py` e `../config.py` para `api/` (ver `painel/vercel.json`), então
o backend é exatamente o mesmo módulo usado pelo app Stitch — zero duplicação.

Variáveis de ambiente (Vercel → Settings → Environment Variables):
  PAINEL_PIN             obrigatório — PIN de acesso ao painel (ex.: 6 dígitos)
  GOATCOUNTER_API_TOKEN  obrigatório — mesmo token usado no app Stitch
  GOATCOUNTER_CODE       opcional    — code do site (padrão: helton)
  GOOGLE_SHEETS_ID       opcional    — CSV export público da planilha; quando
                                       definido, cliques em produtos já removidos
                                       aparecem marcados como "removido"
"""

from __future__ import annotations

import csv
import hmac
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response

# Localmente (pytest / uvicorn na raiz do repo) analytics.py está na raiz;
# na Vercel ele é copiado para api/ no build. Diretório inexistente no
# sys.path é inofensivo — o Python tenta as demais entradas.
_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from analytics import ErroAnalytics, estatisticas_vitrine  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Painel da Vitrine")

_IDS_CACHE: tuple[float, list[str]] | None = None


def _pin_configurado() -> str:
    return (os.environ.get("PAINEL_PIN") or "").strip()


def _autorizado(request: Request, x_pin: str | None, pin_query: str | None) -> bool:
    pin = _pin_configurado()
    if not pin:
        return False
    candidatos = (x_pin or "", pin_query or "", request.cookies.get("pin", ""))
    return any(c and hmac.compare_digest(c, pin) for c in candidatos)


def _exigir_pin(
    request: Request,
    x_pin: str | None = Header(default=None),
    pin: str | None = Query(default=None),
) -> None:
    if not _pin_configurado():
        raise HTTPException(
            status_code=503,
            detail="Painel não configurado: defina PAINEL_PIN nas variáveis de ambiente do projeto Vercel.",
        )
    if not _autorizado(request, x_pin, pin):
        raise HTTPException(status_code=401, detail="PIN inválido ou ausente.")


def _ids_planilha() -> list[str] | None:
    """IDs atuais da planilha (CSV export público, cache de 10 min). Opcional.

    Permite marcar cliques em produtos já removidos — mesmo comportamento do
    endpoint do app Stitch. Sem GOOGLE_SHEETS_ID, devolve None (tudo na lista).
    """
    global _IDS_CACHE
    sid = (os.environ.get("GOOGLE_SHEETS_ID") or "").strip()
    if not sid:
        return None
    agora = time.time()
    if _IDS_CACHE and agora - _IDS_CACHE[0] < 600:
        return _IDS_CACHE[1]
    try:
        resp = requests.get(
            f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv",
            timeout=10,
        )
        resp.raise_for_status()
        ids = [
            (linha.get("ID") or "").strip()
            for linha in csv.DictReader(resp.text.splitlines())
        ]
        ids = [i for i in ids if i]
        if ids:
            _IDS_CACHE = (agora, ids)
            return ids
    except Exception:  # noqa: BLE001 — dado secundário, não derruba o painel
        logger.warning("Falha ao ler IDs da planilha", exc_info=True)
    return _IDS_CACHE[1] if _IDS_CACHE else None


@app.get("/api/checar-pin")
def checar_pin(
    request: Request,
    x_pin: str | None = Header(default=None),
    pin: str | None = Query(default=None),
) -> dict:
    """Valida o PIN sem gastar cota do GoatCounter (usado pela tela de login)."""
    if not _pin_configurado():
        raise HTTPException(
            status_code=503,
            detail="Painel não configurado: defina PAINEL_PIN nas variáveis de ambiente do projeto Vercel.",
        )
    return {"ok": _autorizado(request, x_pin, pin)}


@app.get("/api/metricas")
def api_metricas(
    request: Request,
    dias: int = 30,
    x_pin: str | None = Header(default=None),
    pin: str | None = Query(default=None),
) -> Response:
    """Resumo de métricas da vitrine — mesmo contrato do app Stitch."""
    _exigir_pin(request, x_pin, pin)
    dias = min(365, max(1, dias))
    try:
        metricas = estatisticas_vitrine(dias=dias, ids_conhecidos=_ids_planilha())
    except ErroAnalytics as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: inesperado
        logger.exception("Erro ao buscar métricas")
        raise HTTPException(status_code=500, detail=f"Erro ao buscar métricas: {exc}") from exc
    return Response(
        content=json.dumps({"sucesso": True, "metricas": metricas}, ensure_ascii=False),
        media_type="application/json",
        headers={"Cache-Control": "private, max-age=60"},
    )
