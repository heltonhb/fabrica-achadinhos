"""
tests/test_painel.py — Mini-app de métricas (painel/api/index.py).

Carrega o módulo do entrypoint Vercel por caminho de arquivo (não é pacote
importável) e valida o gate de PIN e o contrato /api/metricas, que deve
espelhar o endpoint do app Stitch ({sucesso, metricas}).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_RAIZ = Path(__file__).resolve().parents[1]
_MODULO = _RAIZ / "painel" / "index.py"

METRICAS_FALSA = {
    "visitantes": 120,
    "cliques_cta": 9,
    "ctr_pct": 7.5,
    "periodo": {"inicio": "2026-09-12", "fim": "2026-10-12", "dias": 30},
    "produtos_clicados": [{"id": "12", "posicao": "grade", "cliques": 9, "na_lista": True}],
    "buscas_falhas": [],
    "filtros": [],
    "serie_diaria": [],
    "referrers": [],
    "acesso_direto": 0,
    "site": "helton",
    "cache": False,
}


def _carregar_modulo(monkeypatch: pytest.MonkeyPatch, pin: str | None = "1234"):
    """Importa painel/api/index.py com PAINEL_PIN controlado (None = sem PIN)."""
    if pin is None:
        monkeypatch.delenv("PAINEL_PIN", raising=False)
    else:
        monkeypatch.setenv("PAINEL_PIN", pin)
    monkeypatch.delenv("GOOGLE_SHEETS_ID", raising=False)

    nome = f"painel_index_{id(monkeypatch)}"
    spec = importlib.util.spec_from_file_location(nome, _MODULO)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(
        mod, "estatisticas_vitrine", lambda **kwargs: dict(METRICAS_FALSA)
    )
    return mod


def test_sem_pin_configurado_retorna_503(monkeypatch):
    mod = _carregar_modulo(monkeypatch, pin=None)
    client = TestClient(mod.app)
    res = client.get("/api/metricas")
    assert res.status_code == 503
    assert "PAINEL_PIN" in res.json()["detail"]


def test_raiz_serve_o_mini_app(monkeypatch):
    mod = _carregar_modulo(monkeypatch, pin="1234")
    client = TestClient(mod.app)
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Painel" in res.text


def test_pin_errado_retorna_401(monkeypatch):
    mod = _carregar_modulo(monkeypatch, pin="1234")
    client = TestClient(mod.app)
    assert client.get("/api/metricas", headers={"x-pin": "9999"}).status_code == 401
    assert client.get("/api/metricas", params={"pin": "0000"}).status_code == 401
    assert client.get("/api/metricas").status_code == 401


def test_pin_correto_via_header(monkeypatch):
    mod = _carregar_modulo(monkeypatch, pin="1234")
    client = TestClient(mod.app)
    res = client.get("/api/metricas", headers={"x-pin": "1234"})
    assert res.status_code == 200
    corpo = res.json()
    assert corpo["sucesso"] is True
    assert corpo["metricas"]["visitantes"] == 120
    assert res.headers["cache-control"] == "private, max-age=60"


def test_pin_correto_via_query(monkeypatch):
    mod = _carregar_modulo(monkeypatch, pin="1234")
    client = TestClient(mod.app)
    res = client.get("/api/metricas", params={"pin": "1234", "dias": 7})
    assert res.status_code == 200
    assert res.json()["sucesso"] is True


def test_pin_correto_via_cookie(monkeypatch):
    mod = _carregar_modulo(monkeypatch, pin="1234")
    client = TestClient(mod.app)
    client.cookies.set("pin", "1234")
    assert client.get("/api/metricas").status_code == 200


def test_checar_pin_ok_e_falso(monkeypatch):
    mod = _carregar_modulo(monkeypatch, pin="1234")
    client = TestClient(mod.app)
    assert client.get("/api/checar-pin", headers={"x-pin": "1234"}).json() == {"ok": True}
    assert client.get("/api/checar-pin", headers={"x-pin": "errado"}).json() == {"ok": False}


def test_checar_pin_sem_configurar_503(monkeypatch):
    mod = _carregar_modulo(monkeypatch, pin=None)
    client = TestClient(mod.app)
    assert client.get("/api/checar-pin").status_code == 503


def test_dias_e_limitado(monkeypatch):
    mod = _carregar_modulo(monkeypatch, pin="1234")
    chamadas: list[int] = []

    def _espia(**kwargs):
        chamadas.append(int(kwargs["dias"]))
        return dict(METRICAS_FALSA)

    monkeypatch.setattr(mod, "estatisticas_vitrine", _espia)
    client = TestClient(mod.app)
    client.get("/api/metricas", headers={"x-pin": "1234"}, params={"dias": 99999})
    client.get("/api/metricas", headers={"x-pin": "1234"}, params={"dias": -5})
    assert chamadas == [365, 1]


def test_erro_analytics_vira_400(monkeypatch):
    mod = _carregar_modulo(monkeypatch, pin="1234")
    from analytics import ErroAnalytics

    def _explode(**kwargs):
        raise ErroAnalytics("token inválido")

    monkeypatch.setattr(mod, "estatisticas_vitrine", _explode)
    client = TestClient(mod.app)
    res = client.get("/api/metricas", headers={"x-pin": "1234"})
    assert res.status_code == 400
    assert "token" in res.json()["detail"]
