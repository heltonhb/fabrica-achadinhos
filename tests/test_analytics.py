"""Testes do painel de métricas da vitrine (analytics.py) — sem rede."""

from __future__ import annotations

import pytest

import analytics


class TestDecomporEventoCta:
    def test_cta_grade_e_hero(self):
        assert analytics.decompor_evento_cta("/cta/grade/20") == ("grade", "20")
        assert analytics.decompor_evento_cta("/cta/hero/1") == ("hero", "1")

    def test_ignora_outros_caminhos(self):
        assert analytics.decompor_evento_cta("/") is None
        assert analytics.decompor_evento_cta("/busca/ok/tapete") is None
        assert analytics.decompor_evento_cta("/cta/grade") is None
        assert analytics.decompor_evento_cta("") is None


class TestResumirHits:
    def test_agrega_visitas_cta_buscas_e_filtros(self):
        hits = [
            {"path": "/", "count": 40, "count_raw": 120, "event": False},
            {"path": "/cta/grade/20", "count": 9, "event": True},
            {"path": "/cta/hero/20", "count": 4, "event": True},
            {"path": "/cta/grade/15", "count": 12, "event": True},
            {"path": "/busca/ok/tapete", "count": 3, "event": True},
            {"path": "/busca/sem-resultado/aspirador", "count": 5, "event": True},
            {"path": "/busca/sem-resultado/kit cozinha", "count": 2, "event": True},
            {"path": "/filtro/moda%20feminina", "count": 7, "event": True},
            {"path": "/inapp/visita-inapp", "count": 25, "event": True},
            {"path": "/inapp/banner-fechado", "count": 10, "event": True},
        ]

        r = analytics.resumir_hits(hits)

        assert r["visitantes"] == 40
        assert r["visualizacoes"] == 120
        assert r["cliques_cta"] == 25
        assert r["buscas_ok"] == 3
        assert r["buscas_sem_resultado"] == 7
        assert r["visitas_inapp"] == 25
        # produtos ordenados por clique (decrescente)
        assert [p["id"] for p in r["produtos_clicados"]] == ["15", "20", "20"]
        assert r["produtos_clicados"][0] == {
            "id": "15", "posicao": "grade", "cliques": 12, "na_lista": True
        }
        assert r["buscas_falhas"][0] == {"termo": "aspirador", "buscas": 5}
        assert r["filtros"][0]["cliques"] == 7

    def test_lista_vazia_nao_zera(self):
        r = analytics.resumir_hits([])
        assert r["visitantes"] == 0
        assert r["cliques_cta"] == 0
        assert r["produtos_clicados"] == []

    def test_pageview_com_path_cta_nao_conta_como_clique(self):
        """Visita direta/bot em /cta/... (event=false) não é clique no CTA.

        Regressão: o painel mostrava o produto #99 (que não existe na lista)
        porque um pageview de crawler em /cta/grade/99 era contado como clique.
        """
        hits = [
            {"path": "/", "count": 5, "count_raw": 5, "event": False},
            {"path": "/cta/grade/99", "count": 1, "event": False},
            {"path": "/cta/grade/20", "count": 3, "event": True},
        ]

        r = analytics.resumir_hits(hits)

        assert r["cliques_cta"] == 3
        assert r["produtos_clicados"] == [
            {"id": "20", "posicao": "grade", "cliques": 3, "na_lista": True}
        ]
        assert all(p["id"] != "99" for p in r["produtos_clicados"])

    def test_marca_clique_de_produto_removido_da_lista(self):
        """Clique real em id que não existe mais na planilha é marcado como removido."""
        hits = [
            {"path": "/cta/grade/99", "count": 4, "event": True},
            {"path": "/cta/grade/15", "count": 2, "event": True},
        ]

        # ids da planilha em formatos mistos ('#15', '02') continuam reconhecidos
        r = analytics.resumir_hits(hits, ids_conhecidos=["#15", "02"])

        assert r["produtos_clicados"][0] == {
            "id": "99", "posicao": "grade", "cliques": 4, "na_lista": False
        }
        assert r["produtos_clicados"][1]["na_lista"] is True

        # sem ids_conhecidos não há como validar → assume que está na lista
        sem_ref = analytics.resumir_hits(hits)
        assert all(p["na_lista"] for p in sem_ref["produtos_clicados"])


class TestEstatisticasVitrine:
    def _mock_get(self, dados_total, dados_hits, dados_refs):
        def _get(caminho, params):
            return {
                "stats/total": dados_total,
                "stats/hits": dados_hits,
                "stats/toprefs": dados_refs,
            }[caminho]

        return _get

    def test_monta_resumo_com_ctr_e_referrers(self, monkeypatch):
        monkeypatch.setattr(
            analytics,
            "_get",
            self._mock_get(
                {"total": 40, "total_events": 60, "stats": []},
                {
                    "hits": [
                        {"path": "/", "count": 40, "count_raw": 120},
                        {"path": "/cta/grade/20", "count": 10, "event": True},
                    ]
                },
                {"stats": [{"path": "instagram.com", "count": 22}, {"path": "", "count": 5}]},
            ),
        )

        resumo = analytics.estatisticas_vitrine(dias=7, usar_cache=False)

        assert resumo["visitantes"] == 40
        assert resumo["cliques_cta"] == 10
        assert resumo["ctr_pct"] == 25.0
        assert resumo["visitas_total_periodo"] == 40
        assert resumo["periodo"]["dias"] == 7
        assert resumo["site"] == analytics.codigo_site()
        assert resumo["referrers"][0] == {"url": "instagram.com", "visitas": 22}
        # referrer vazio é descartado
        assert all(r["url"] for r in resumo["referrers"])

    def test_cache_distingue_lista_de_ids(self, monkeypatch):
        """Mudou a lista de produtos (ids_conhecidos) → não reaproveita cache antigo."""
        chamadas = {"n": 0}

        def _get(caminho, params):
            chamadas["n"] += 1
            return {"stats/total": {"total": 1}, "stats/hits": {"hits": []}, "stats/toprefs": {"stats": []}}[caminho]

        monkeypatch.setattr(analytics, "_get", _get)
        analytics.limpar_cache()

        analytics.estatisticas_vitrine(dias=20)
        analytics.estatisticas_vitrine(dias=20, ids_conhecidos=["#01"])

        assert chamadas["n"] == 6  # 3 chamadas por lista de cache distinta

    def test_ctr_zero_quando_sem_visitas(self, monkeypatch):
        monkeypatch.setattr(
            analytics,
            "_get",
            self._mock_get({"total": 0}, {"hits": []}, {"stats": []}),
        )
        resumo = analytics.estatisticas_vitrine(dias=7, usar_cache=False)
        assert resumo["ctr_pct"] == 0.0

    def test_cache_evita_segunda_chamada(self, monkeypatch):
        chamadas = {"n": 0}

        def _get(caminho, params):
            chamadas["n"] += 1
            return {"stats/total": {"total": 1}, "stats/hits": {"hits": []}, "stats/toprefs": {"stats": []}}[caminho]

        monkeypatch.setattr(analytics, "_get", _get)
        analytics.limpar_cache()

        analytics.estatisticas_vitrine(dias=15)
        chamadas_1a = chamadas["n"]
        analytics.estatisticas_vitrine(dias=15)

        assert chamadas_1a == 3
        assert chamadas["n"] == 3  # segunda chamada veio do cache


class TestErrosAmigaveis:
    def test_sem_token(self, monkeypatch):
        monkeypatch.setattr(analytics, "_token", lambda: "")
        with pytest.raises(analytics.ErroAnalytics) as exc:
            analytics.estatisticas_vitrine(dias=7, usar_cache=False)
        assert "GOATCOUNTER_API_TOKEN" in str(exc.value)

    def test_token_invalido(self, monkeypatch):
        monkeypatch.setattr(analytics, "_token", lambda: "token-errado")

        class _Resp:
            status_code = 401
            text = '{"error":"unknown token"}'

            def json(self):
                return {"error": "unknown token"}

        monkeypatch.setattr(analytics.requests, "get", lambda *a, **k: _Resp())
        with pytest.raises(analytics.ErroAnalytics) as exc:
            analytics._get("stats/total", {})
        assert "Token do GoatCounter inválido" in str(exc.value)

    def test_erro_de_rede(self, monkeypatch):
        import requests as _requests

        monkeypatch.setattr(analytics, "_token", lambda: "qualquer")
        monkeypatch.setattr(
            analytics.requests, "get",
            lambda *a, **k: (_ for _ in ()).throw(_requests.ConnectionError("sem internet")),
        )
        with pytest.raises(analytics.ErroAnalytics) as exc:
            analytics._get("stats/total", {})
        assert "Sem conexão" in str(exc.value)
