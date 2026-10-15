"""
tests/test_analytics_trafego.py — Tráfego detalhado do painel (analytics.py).

Cobre as adições ao resumo: horários de pico (UTC → Brasília), dia da semana,
crescimento vs período anterior e nomes amigáveis de referrers — tudo sem rede.
"""

from __future__ import annotations

import datetime as dt

import analytics


# ─── Nome amigável de origem ─────────────────────────────────────────────────

class TestNomeAmigavelReferrer:
    def test_mapeia_redes_sociais_conhecidas(self):
        casos = {
            "l.instagram.com": "Instagram",
            "www.instagram.com": "Instagram",
            "instagram.com": "Instagram",
            "lm.facebook.com": "Facebook",
            "www.facebook.com": "Facebook",
            "m.facebook.com": "Facebook",
            "t.co": "X (Twitter)",
            "vm.tiktok.com": "TikTok",
            "www.tiktok.com": "TikTok",
            "api.whatsapp.com": "WhatsApp",
            "chat.whatsapp.com": "WhatsApp",
            "wa.me": "WhatsApp",
            "www.youtube.com": "YouTube",
            "youtu.be": "YouTube",
            "www.google.com": "Google (busca)",
            "google.com": "Google (busca)",
            "bing.com": "Bing",
            "ig": "Instagram (campanha UTM 'ig')",
        }
        for dominio, esperado in casos.items():
            assert analytics.nome_amigavel_referrer(dominio) == esperado, dominio

    def test_desconhecido_mantem_valor_limpo(self):
        assert analytics.nome_amigavel_referrer("site-estranho.com.br") == "site-estranho.com.br"
        assert analytics.nome_amigavel_referrer("0.0.0.0:8000") == "0.0.0.0:8000"
        assert analytics.nome_amigavel_referrer("") == ""

    def test_descarta_www_https_e_caminho(self):
        assert analytics.nome_amigavel_referrer("https://www.instagram.com/") == "Instagram"
        assert analytics.nome_amigavel_referrer("https://l.instagram.com/x") == "Instagram"


# ─── Horários de pico ────────────────────────────────────────────────────────

class TestHorariosAcesso:
    def test_agrega_horas_utc_do_path_raiz(self):
        hits = [
            # 2 visitas às 10h UTC
            {"path": "/", "count": 2, "count_raw": 2, "event": False,
             "stats": [{"day": "2026-10-05", "hourly": [0] * 10 + [2] + [0] * 13}]},
            # 5 às 10h UTC (outro dia) + 1 às 14h UTC
            {"path": "/", "count": 6, "count_raw": 6, "event": False,
             "stats": [
                 {"day": "2026-10-06", "hourly": [0] * 10 + [5] + [0] * 13},
                 {"day": "2026-10-07", "hourly": [0] * 14 + [1] + [0] * 9},
             ]},
            # evento de CTA não entra na conta de visitas por hora
            {"path": "/cta/grade/20", "count": 3, "event": True,
             "stats": [{"day": "2026-10-05", "hourly": [0] * 3 + [3] + [0] * 20}]},
        ]
        horas = analytics.horas_acesso(hits)
        assert horas == [0] * 10 + [7] + [0] * 3 + [1] + [0] * 9  # UTC
        assert len(horas) == 24
        assert sum(horas) == 8

    def test_sem_stats_usa_zona_horaria_padrao(self):
        assert analytics.horas_acesso([]) == [0] * 24
        assert analytics.horas_acesso([{"path": "/", "count": 5}]) == [0] * 24

    def test_pico_de_hora_com_fuso_brasilia(self):
        horas = [0] * 24
        horas[10] = 9  # 10h UTC → 7h em Brasília
        pico = analytics.pico_de_acesso(horas)
        assert pico == {"hora_utc": 10, "hora_local": "07h", "visitas": 9}

    def test_pico_de_hora_meia_noite_utc(self):
        horas = [0] * 24
        horas[0] = 4  # 0h UTC → 21h do dia anterior em Brasília
        pico = analytics.pico_de_acesso(horas)
        assert pico["hora_local"] == "21h"
        assert pico["visitas"] == 4

    def test_pico_sem_dados_e_none(self):
        assert analytics.pico_de_acesso([0] * 24) is None
        assert analytics.pico_de_acesso([]) is None


# ─── Dia da semana ──────────────────────────────────────────────────────────

class TestVisitasDiaSemana:
    def test_agrega_por_dia_da_semana(self):
        serie = [
            {"dia": "2026-10-05", "visitas": 9},   # segunda (0)
            {"dia": "2026-10-06", "visitas": 3},   # terça (1)
            {"dia": "2026-10-11", "visitas": 5},   # domingo (6)
            {"dia": "2026-10-11", "visitas": 2},   # domingo (duplo)
        ]
        res = analytics.visitas_por_dia_semana(serie)
        assert res == [
            {"dia": "Seg", "visitas": 9},
            {"dia": "Ter", "visitas": 3},
            {"dia": "Qua", "visitas": 0},
            {"dia": "Qui", "visitas": 0},
            {"dia": "Sex", "visitas": 0},
            {"dia": "Sáb", "visitas": 0},
            {"dia": "Dom", "visitas": 7},
        ]

    def test_serie_vazia_devolve_zero(self):
        assert analytics.visitas_por_dia_semana([]) == [
            {"dia": d, "visitas": 0} for d in ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
        ]

    def test_ignora_dia_invalido(self):
        assert analytics.visitas_por_dia_semana([{"dia": "xx", "visitas": 3}])[0]["visitas"] == 0


# ─── Crescimento vs período anterior ─────────────────────────────────────────

class TestCrescimento:
    def test_calcula_variacao_percentual(self):
        assert analytics.calcular_crescimento(atual=110, anterior=100) == 10.0

    def test_queda_percentual(self):
        assert analytics.calcular_crescimento(atual=80, anterior=100) == -20.0

    def test_anterior_zero_sem_calcular(self):
        # sem base anterior não dá pra calcular percentual — não inventa número
        assert analytics.calcular_crescimento(atual=10, anterior=0) is None
        assert analytics.calcular_crescimento(atual=0, anterior=0) is None


# ─── Integração no resumo (via estatisticas_vitrine) ─────────────────────────

class TestResumoTrafegoDetalhado:
    """stats/hits com group=day devolve 'stats' por dia com 'hourly' de 24
    posições (formato confirmado ao vivo na API v0)."""

    def _get_padrao(self):
        return {
            "stats/total": {
                "total": 22,
                "total_events": 8,
                "stats": [
                    {"day": "2026-10-05", "daily": 9, "weekly": 9, "monthly": 22},
                    {"day": "2026-10-06", "daily": 0},
                ],
            },
            "stats/hits": {
                "hits": [
                    {
                        "path": "/", "count": 13, "count_raw": 13, "event": False,
                        "stats": [
                            {"day": "2026-10-05", "hourly": [0] * 10 + [7] + [0] * 13, "daily": 7},
                            {"day": "2026-10-06", "hourly": [0] * 14 + [2] + [0] * 9, "daily": 2},
                        ],
                    },
                    {"path": "/cta/grade/20", "count": 5, "event": True,
                     "stats": [{"day": "2026-10-05", "hourly": [0] * 2 + [5] + [0] * 21}]},
                ]
            },
            "stats/toprefs": {"stats": [
                {"id": "l.instagram.com", "name": "l.instagram.com", "count": 6},
                {"name": "", "count": 5, "ref_scheme": "o"},
            ]},
        }

    def _inicio_janela_atual(self, dias: int = 7) -> str:
        """Mesma fórmula do estatisticas_vitrine p/ separar janelas no mock."""
        hoje = dt.datetime.now()
        return (hoje - dt.timedelta(days=dias)).strftime("%Y-%m-%dT00:00:00Z")

    def test_resumo_inclui_pico_dia_semana_e_origem_amigavel(self, monkeypatch):
        dados = self._get_padrao()

        def _get(caminho, params):
            if caminho == "stats/hits" and params["start"] < self._inicio_janela_atual():
                return {"hits": []}  # janela anterior sem dados
            return dados.get(caminho, {"stats": []})

        monkeypatch.setattr(analytics, "_get", _get)
        resumo = analytics.estatisticas_vitrine(dias=7, usar_cache=False)

        # pico: 7 visitas às 10h UTC = 07h Brasília
        assert resumo["pico_acesso"] == {"hora_utc": 10, "hora_local": "07h", "visitas": 7}
        assert len(resumo["horas_acesso"]) == 24
        assert sum(resumo["horas_acesso"]) == 9
        # dia da semana só com pageviews da vitrine (não soma eventos):
        # 2026-10-05 é segunda (7 visitas às 10h UTC), 2026-10-06 é terça (2 às 14h UTC)
        assert resumo["dias_semana"][0] == {"dia": "Seg", "visitas": 7}
        assert resumo["dias_semana"][1] == {"dia": "Ter", "visitas": 2}
        # referrers: url crua preservada + nome amigável novo
        assert resumo["referrers"][0] == {
            "url": "l.instagram.com", "nome": "Instagram", "visitas": 6,
        }
        # acesso direto continua somando referrers sem nome
        assert resumo["acesso_direto"] == 5

    def test_crescimento_consulta_janela_anterior(self, monkeypatch):
        dados = self._get_padrao()
        janelas: list[str] = []

        def _get(caminho, params):
            janelas.append(params.get("start", ""))
            if caminho == "stats/hits" and params["start"] < self._inicio_janela_atual():
                return {"hits": []}  # sem dados no período anterior
            return dados.get(caminho, {"stats": []})

        monkeypatch.setattr(analytics, "_get", _get)
        resumo = analytics.estatisticas_vitrine(dias=7, usar_cache=False)

        # houve consulta com start anterior ao início da janela atual
        assert any(s < self._inicio_janela_atual() for s in janelas)
        # sem visitantes no período anterior não inventa percentual
        assert resumo["crescimento_visitantes"] is None

    def test_crescimento_calculado_com_visitantes_anteriores(self, monkeypatch):
        dados = self._get_padrao()

        def _get(caminho, params):
            if caminho == "stats/hits" and params["start"] < self._inicio_janela_atual():
                return {"hits": [{"path": "/", "count": 10, "event": False}]}
            return dados.get(caminho, {"stats": []})

        monkeypatch.setattr(analytics, "_get", _get)
        resumo = analytics.estatisticas_vitrine(dias=7, usar_cache=False)
        # visitantes atuais 13 vs 10 no período anterior → +30%
        assert resumo["crescimento_visitantes"] == 30.0

    def test_falha_na_janela_anterior_nao_derruba_painel(self, monkeypatch):
        dados = self._get_padrao()

        def _get(caminho, params):
            if caminho == "stats/hits" and params["start"] < self._inicio_janela_atual():
                raise analytics.ErroAnalytics("GoatCounter retornou 500")
            return dados.get(caminho, {"stats": []})

        monkeypatch.setattr(analytics, "_get", _get)
        resumo = analytics.estatisticas_vitrine(dias=7, usar_cache=False)
        assert resumo["visitantes"] == 13
        assert resumo["crescimento_visitantes"] is None
