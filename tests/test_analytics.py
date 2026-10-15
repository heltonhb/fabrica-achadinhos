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

    def test_aceita_path_sem_barra_inicial(self):
        """Regressão: o GoatCounter guarda eventos como 'cta/hero/25' (sem '/')."""
        assert analytics.decompor_evento_cta("cta/hero/25") == ("hero", "25")
        assert analytics.decompor_evento_cta("cta/grade/02") == ("grade", "02")
        assert analytics.decompor_evento_cta("busca/ok/20") is None


class TestResumirHitsPathsSemBarra:
    def test_eventos_reais_do_goatcounter_sao_contados(self):
        """Regressão: painel mostrava 0 cliques porque os eventos chegam sem '/'.

        Paths copiados da resposta real de /stats/hits.
        """
        hits = [
            {"path": "/", "count": 19, "event": False},
            {"path": "cta/hero/25", "count": 1, "event": True},
            {"path": "cta/hero/24", "count": 1, "event": True},
            {"path": "cta/grade/20", "count": 1, "event": True},
            {"path": "filtro/all", "count": 1, "event": True},
            {"path": "busca/ok/20", "count": 1, "event": True},
            {"path": "busca/sem-resultado/aspirador", "count": 2, "event": True},
            {"path": "inapp/visita-inapp", "count": 1, "event": True},
            # pageview de bot em /cta/... continua não sendo clique
            {"path": "/cta/grade/99", "count": 1, "event": False},
        ]

        r = analytics.resumir_hits(hits)

        assert r["visitantes"] == 19
        assert r["cliques_cta"] == 3
        assert {p["id"] for p in r["produtos_clicados"]} == {"25", "24", "20"}
        assert r["buscas_ok"] == 1
        assert r["buscas_sem_resultado"] == 2
        assert r["buscas_falhas"] == [{"termo": "aspirador", "buscas": 2}]
        assert r["filtros"] == [{"nicho": "all", "cliques": 1}]
        assert r["visitas_inapp"] == 1


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


# total + hits + toprefs + hits-janela-anterior + quebras do público
N_CHAMADAS = 4 + len(analytics._QUEBRAS)


class TestEstatisticasVitrine:
    def _mock_get(self, dados_total, dados_hits, dados_refs):
        def _get(caminho, params):
            return {
                "stats/total": dados_total,
                "stats/hits": dados_hits,
                "stats/toprefs": dados_refs,
            }.get(caminho, {"stats": []})

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
        assert resumo["referrers"][0] == {"url": "instagram.com", "nome": "Instagram", "visitas": 22}
        # referrer vazio é descartado
        assert all(r["url"] for r in resumo["referrers"])

    def test_cache_distingue_lista_de_ids(self, monkeypatch):
        """Mudou a lista de produtos (ids_conhecidos) → não reaproveita cache antigo."""
        chamadas = {"n": 0}

        def _get(caminho, params):
            chamadas["n"] += 1
            return {"stats/total": {"total": 1}, "stats/hits": {"hits": []}}.get(caminho, {"stats": []})

        monkeypatch.setattr(analytics, "_get", _get)
        analytics.limpar_cache()

        analytics.estatisticas_vitrine(dias=20)
        analytics.estatisticas_vitrine(dias=20, ids_conhecidos=["#01"])

        assert chamadas["n"] == 2 * N_CHAMADAS  # chamadas completas por lista de cache distinta

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
            return {"stats/total": {"total": 1}, "stats/hits": {"hits": []}}.get(caminho, {"stats": []})

        monkeypatch.setattr(analytics, "_get", _get)
        analytics.limpar_cache()

        analytics.estatisticas_vitrine(dias=15)
        chamadas_1a = chamadas["n"]
        analytics.estatisticas_vitrine(dias=15)

        assert chamadas_1a == N_CHAMADAS
        assert chamadas["n"] == N_CHAMADAS  # segunda chamada veio do cache


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


class TestPerfilPublico:
    def test_referrer_usa_campo_name(self, monkeypatch):
        """A API atual devolve o referrer em 'name' — antes a lista vinha sempre vazia."""
        def _get(caminho, params):
            return {
                "stats/total": {"total": 9},
                "stats/hits": {"hits": []},
                "stats/toprefs": {"stats": [
                    {"name": "", "count": 5, "ref_scheme": "o"},
                    {"id": "instagram.com", "name": "instagram.com", "count": 4},
                ]},
            }.get(caminho, {"stats": []})

        monkeypatch.setattr(analytics, "_get", _get)
        resumo = analytics.estatisticas_vitrine(dias=7, usar_cache=False)
        assert resumo["referrers"] == [{"url": "instagram.com", "nome": "Instagram", "visitas": 4}]
        assert resumo["acesso_direto"] == 5

    def test_serie_diaria_e_melhor_dia(self, monkeypatch):
        total = {"total": 5, "stats": [
            {"day": "2026-10-02", "daily": 4},
            {"day": "2026-10-01", "hourly": [1, 0, 0]},
        ]}
        assert analytics.serie_diaria(total) == [
            {"dia": "2026-10-01", "visitas": 1},
            {"dia": "2026-10-02", "visitas": 4},
        ]
        hits = [{"path": "/", "count": 5, "stats": [
            {"day": "2026-10-01", "hourly": [0] * 12 + [1] + [0] * 11},
            {"day": "2026-10-02", "hourly": [0] * 12 + [4] + [0] * 11},
        ]}]
        monkeypatch.setattr(
            analytics, "_get",
            lambda c, p: {"stats/total": total, "stats/hits": {"hits": hits}}.get(c, {"stats": []}),
        )
        resumo = analytics.estatisticas_vitrine(dias=7, usar_cache=False)
        assert resumo["melhor_dia"] == {"dia": "2026-10-02", "visitas": 4}
        assert resumo["media_diaria"] == 2.5

    def test_serie_diaria_nao_conta_eventos_como_visitas(self):
        """Regressão: /stats/total soma eventos; gráfico/melhor dia/média inflavam.

        Dados reais: 19 pageviews + 9 eventos + 1 hit de bot = 29 no total.
        """
        total = {"total": 29, "total_events": 9, "stats": [
            {"day": "2026-10-12", "daily": 15},
        ]}
        hits = [
            {"path": "/", "count": 9, "stats": [
                {"day": "2026-10-12", "hourly": [0] * 10 + [9] + [0] * 13},
            ]},
            {"path": "cta/hero/25", "count": 1, "event": True, "stats": [
                {"day": "2026-10-12", "hourly": [0] * 14 + [1] + [0] * 9},
            ]},
        ]
        assert analytics.serie_diaria(total, hits=hits) == [
            {"dia": "2026-10-12", "visitas": 9},
        ]

    def test_serie_diaria_usa_o_dia_de_brasilia(self):
        """22h BRT (domingo) = 01h UTC (segunda): deve contar no domingo."""
        total = {"stats": [
            {"day": "2026-10-11", "daily": 0},
            {"day": "2026-10-12", "daily": 0},
        ]}
        hits = [{"path": "/", "stats": [
            {"day": "2026-10-12", "hourly": [0, 3] + [0] * 8 + [2] + [0] * 13},
        ]}]
        assert analytics.serie_diaria(total, hits=hits) == [
            {"dia": "2026-10-11", "visitas": 3},   # 01h UTC → 22h BRT do dia 11
            {"dia": "2026-10-12", "visitas": 2},   # 10h UTC → 07h BRT
        ]

    def test_serie_diaria_sem_horas_usa_daily(self):
        total = {"stats": [{"day": "2026-10-12", "daily": 0}]}
        hits = [{"path": "/", "stats": [{"day": "2026-10-12", "daily": 4}]}]
        assert analytics.serie_diaria(total, hits=hits) == [
            {"dia": "2026-10-12", "visitas": 4},
        ]

    @pytest.mark.parametrize("ref,esperado", [
        ("localhost:8000", True),
        ("0.0.0.0:8000", True),
        ("192.168.15.20:8000", True),
        ("10.0.0.5", True),
        ("172.20.1.1:3000", True),
        ("http://127.0.0.1:5000/x", True),
        ("meu-pc.local", True),
        ("172.32.0.1", False),
        ("l.instagram.com", False),
        ("www.facebook.com", False),
        ("ig", False),
        ("", False),
    ])
    def test_referrer_interno(self, ref, esperado):
        assert analytics.referrer_interno(ref) is esperado

    def test_referrers_de_teste_saem_da_origem_e_viram_contador(self, monkeypatch):
        refs = [
            {"name": "l.instagram.com", "count": 6},
            {"name": "0.0.0.0:8000", "count": 6},
            {"name": "localhost:8000", "count": 2},
            {"name": "192.168.15.20:8000", "count": 1},
            {"name": "", "count": 3},
        ]
        monkeypatch.setattr(
            analytics, "_get",
            lambda c, p: {"stats/total": {"total": 1}, "stats/hits": {"hits": []},
                          "stats/toprefs": {"stats": refs}}.get(c, {"stats": []}),
        )
        resumo = analytics.estatisticas_vitrine(dias=7, usar_cache=False)
        assert [r["nome"] for r in resumo["referrers"]] == ["Instagram"]
        assert resumo["visitas_testes"] == 9
        assert resumo["acesso_direto"] == 3

    def test_resumir_quebra_dispositivos_e_desconhecidos(self):
        sizes = {"stats": [
            {"id": "phone", "name": "", "count": 3},
            {"id": "tablet", "name": "", "count": 0},
            {"id": "desktop", "name": "", "count": 1},
        ]}
        assert analytics.resumir_quebra("stats/sizes", sizes) == [
            {"nome": "Celular", "visitas": 3, "pct": 75.0},
            {"nome": "Computador", "visitas": 1, "pct": 25.0},
        ]
        locs = {"stats": [
            {"id": "BR", "name": "Brazil", "count": 7},
            {"id": "(unknown)", "name": "(unknown)", "count": 2},
            {"name": "", "count": 1},
        ]}
        res = analytics.resumir_quebra("stats/locations", locs)
        assert res[0] == {"nome": "Brazil", "visitas": 7, "pct": 70.0}
        assert res[1] == {"nome": "Desconhecido", "visitas": 3, "pct": 30.0}

    def test_falha_em_quebra_nao_derruba_painel(self, monkeypatch):
        def _get(caminho, params):
            if caminho == "stats/browsers":
                raise analytics.ErroAnalytics("GoatCounter retornou 500")
            return {"stats/total": {"total": 1}, "stats/hits": {"hits": []}}.get(caminho, {"stats": []})

        monkeypatch.setattr(analytics, "_get", _get)
        resumo = analytics.estatisticas_vitrine(dias=7, usar_cache=False)
        assert resumo["navegadores"] == []
        assert resumo["sistemas"] == []
