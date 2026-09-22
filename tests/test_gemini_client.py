"""Testes do cliente Gemini (retry/backoff, sem chamar a API real)."""

from __future__ import annotations

import pytest

import gemini_client as gc


def test_modelos_padrao_nao_vazios():
    assert gc.MODELOS_PADRAO
    assert all(isinstance(m, str) and m for m in gc.MODELOS_PADRAO)


def test_espera_recuperavel_503_cresce_e_corta():
    w0 = gc._espera_recoveravel(0, "503 UNAVAILABLE")
    w1 = gc._espera_recoveravel(1, "503 UNAVAILABLE")
    w_last = gc._espera_recoveravel(10, "503 UNAVAILABLE")
    assert w0 is not None and w1 is not None
    assert w1 > w0
    assert w_last == gc._ESPERA_MAX_S


def test_espera_erro_nao_recuperavel():
    assert gc._espera_recoveravel(0, "404 NOT_FOUND") is None
    assert gc._espera_recoveravel(2, "API key not valid") is None


def test_chamar_sem_api_key(monkeypatch):
    monkeypatch.setattr(gc, "GEMINI_API_KEY", "")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        gc._chamar_gemini("sys", "user")


def test_chamar_503_persistente_levanta_com_ultimo_erro(monkeypatch):
    monkeypatch.setattr(gc, "GEMINI_API_KEY", "k")
    monkeypatch.setattr(gc.time, "sleep", lambda _s: None)

    class _Exc(Exception):
        pass

    class _Models:
        def generate_content(self, **_kwargs):
            raise RuntimeError("503 UNAVAILABLE high demand")

    class _Client:
        def __init__(self, api_key=None):
            self.models = _Models()

    monkeypatch.setattr(gc.genai, "Client", _Client)
    with pytest.raises(RuntimeError) as ei:
        gc._chamar_gemini("sys", "user", modelos=["m1"])
    assert "503" in str(ei.value)
    assert "m1" in str(ei.value)


def test_chamar_retorna_primeiro_texto_valido(monkeypatch):
    monkeypatch.setattr(gc, "GEMINI_API_KEY", "k")

    class _Models:
        def __init__(self):
            self.calls = 0

        def generate_content(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("503 UNAVAILABLE")
            class R:
                text = "  prompt ok  "
            return R()

    models = _Models()

    class _Client:
        def __init__(self, api_key=None):
            self.models = models

    monkeypatch.setattr(gc.genai, "Client", _Client)
    monkeypatch.setattr(gc.time, "sleep", lambda _s: None)
    assert gc._chamar_gemini("sys", "user", modelos=["m1"]) == "prompt ok"
    assert models.calls >= 2


def test_429_falha_rapido_para_proximo_modelo(monkeypatch):
    """429 em um modelo NÃO deve gerar retry cego: troca de modelo na hora."""
    monkeypatch.setattr(gc, "GEMINI_API_KEY", "k")
    sleeps: list[float] = []
    monkeypatch.setattr(gc.time, "sleep", sleeps.append)

    class _Models:
        def __init__(self):
            self.calls: dict[str, int] = {}

        def generate_content(self, **kwargs):
            m = kwargs["model"]
            self.calls[m] = self.calls.get(m, 0) + 1
            if m == "m1":
                raise RuntimeError("429 RESOURCE_EXHAUSTED ... Please retry in 33.1s.")

            class R:
                text = "ok do m2"

            return R()

    models = _Models()

    class _Client:
        def __init__(self, api_key=None):
            self.models = models

    monkeypatch.setattr(gc.genai, "Client", _Client)
    assert gc._chamar_gemini("sys", "user", modelos=["m1", "m2"]) == "ok do m2"
    assert models.calls["m1"] == 1                      # uma tentativa e trocou
    assert not any(s >= 10 for s in sleeps)             # não esperou a janela de cota


def test_429_em_todos_modelos_espera_uma_vez_e_repete(monkeypatch):
    """Se TODOS os modelos estão na cota, espera o retry in Ns uma vez e repete."""
    monkeypatch.setattr(gc, "GEMINI_API_KEY", "k")
    sleeps: list[float] = []
    monkeypatch.setattr(gc.time, "sleep", sleeps.append)

    class _Models:
        def __init__(self):
            self.calls: dict[str, int] = {}

        def generate_content(self, **kwargs):
            m = kwargs["model"]
            self.calls[m] = self.calls.get(m, 0) + 1
            raise RuntimeError(f"429 RESOURCE_EXHAUSTED ... Please retry in 5s. [{m}]")

    models = _Models()

    class _Client:
        def __init__(self, api_key=None):
            self.models = models

    monkeypatch.setattr(gc.genai, "Client", _Client)
    with pytest.raises(RuntimeError) as ei:
        gc._chamar_gemini("sys", "user", modelos=["m1", "m2"])

    assert "429" in str(ei.value)
    assert models.calls == {"m1": 2, "m2": 2}           # 2 rodadas, 1 tentativa/rodada
    assert sleeps == [5.0]                              # espera coletiva única


def test_validar_saida_texto_puro_e_vazio():
    assert gc._validar_saida("olá", None) == "olá"
    assert gc._validar_saida("", "application/json") is None
    assert gc._validar_saida("não é json", "application/json") is None


def test_validar_saida_repara_virgula_final():
    texto = '{"locucao": "oi", "hashtags": ["a",],}'
    out = gc._validar_saida(texto, "application/json")
    assert out is not None
    import json as _json
    assert _json.loads(out)["locucao"] == "oi"


def test_validar_saida_repara_fences_markdown():
    texto = '```json\n{"texto": "legenda"}\n```'
    out = gc._validar_saida(texto, "application/json")
    assert out is not None
    import json as _json
    assert _json.loads(out)["texto"] == "legenda"


def test_chamar_gemini_json_invalido_repete_ate_valido(monkeypatch):
    """JSON irrecuperável deve contar como resposta ruim e ser tentado de novo."""
    monkeypatch.setattr(gc, "GEMINI_API_KEY", "k")
    monkeypatch.setattr(gc.time, "sleep", lambda _s: None)

    class _Models:
        def __init__(self):
            self.calls = 0

        def generate_content(self, **_kwargs):
            self.calls += 1
            class R:
                text = "claramente nao é json" if self.calls == 1 else '{"ok": true}'
            return R()

    models = _Models()

    class _Client:
        def __init__(self, api_key=None):
            self.models = models

    monkeypatch.setattr(gc.genai, "Client", _Client)
    out = gc._chamar_gemini(
        "sys", "user", response_mime_type="application/json", modelos=["m1"]
    )
    assert out == '{"ok": true}'
    assert models.calls >= 2


def test_dica_retry_429_extraia_segundos():
    assert gc._dica_retry_429("429 ... Please retry in 33.104s.") == pytest.approx(33.104)
    assert gc._dica_retry_429("429 RESOURCE_EXHAUSTED sem dica") is None


def test_resposta_vazia_repete_ate_sucesso(monkeypatch):
    monkeypatch.setattr(gc, "GEMINI_API_KEY", "k")
    monkeypatch.setattr(gc.time, "sleep", lambda _s: None)

    class _Models:
        def __init__(self):
            self.calls = 0

        def generate_content(self, **_kwargs):
            self.calls += 1
            class R:
                text = "" if self.calls < 2 else "depois de vazio"
            return R()

    models = _Models()

    class _Client:
        def __init__(self, api_key=None):
            self.models = models

    monkeypatch.setattr(gc.genai, "Client", _Client)
    assert gc._chamar_gemini("sys", "user", modelos=["m1"]) == "depois de vazio"
    assert models.calls >= 2
