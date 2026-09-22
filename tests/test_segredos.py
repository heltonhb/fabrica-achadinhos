"""Resolução de segredos (env → .env → st.secrets) e token do Google na nuvem."""

from __future__ import annotations

import json
import sys
import types

import config
import sheets


# ─── config.obter_segredo ────────────────────────────────────────────────────


def test_env_varre_vence_arquivo_env(monkeypatch):
    monkeypatch.setenv("CHAVE_TESTE", "do_env")
    monkeypatch.setitem(config.ENV, "CHAVE_TESTE", "do_arquivo")
    assert config.obter_segredo("CHAVE_TESTE") == "do_env"


def test_cai_no_arquivo_env_quando_sem_env(monkeypatch):
    monkeypatch.delenv("CHAVE_TESTE", raising=False)
    monkeypatch.setitem(config.ENV, "CHAVE_TESTE", "do_arquivo")
    assert config.obter_segredo("CHAVE_TESTE") == "do_arquivo"


def test_ausente_retorna_vazio(monkeypatch):
    monkeypatch.delenv("CHAVE_TESTE_AUSENTE", raising=False)
    monkeypatch.setitem(config.ENV, "CHAVE_TESTE_AUSENTE", "")
    assert config.obter_segredo("CHAVE_TESTE_AUSENTE") == ""


def test_cai_no_st_secrets_quando_streamlit_carregado(monkeypatch):
    # simula o contexto do Streamlit (st.secrets é um mapping)
    fake = types.SimpleNamespace(secrets={"CHAVE_ST": "do_secret"})
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    assert config.obter_segredo("CHAVE_ST") == "do_secret"


def test_sem_streamlit_nao_importa_streamlit():
    # scripts CLI não devem puxar o streamlit só por ler um segredo
    antes = "streamlit" in sys.modules
    resultado = config.obter_segredo("QUALQUER_CHAVE")
    assert resultado == "" or isinstance(resultado, str)
    if not antes:
        assert "streamlit" not in sys.modules


# ─── sheets: token via secret (nuvem) ────────────────────────────────────────


def test_info_token_de_conteudo_inline(monkeypatch, tmp_path):
    payload = {"refresh_token": "rt", "client_id": "cid", "client_secret": "cs"}
    monkeypatch.setattr(sheets, "_TOKEN_PATH", tmp_path / "nope.json")
    monkeypatch.setattr(sheets, "GOOGLE_TOKEN_JSON", json.dumps(payload))
    assert sheets._info_token() == payload


def test_info_token_conteudo_invalido_retorna_none(monkeypatch, tmp_path):
    monkeypatch.setattr(sheets, "_TOKEN_PATH", tmp_path / "nope.json")
    monkeypatch.setattr(sheets, "GOOGLE_TOKEN_JSON", "{quebrado")
    assert sheets._info_token() is None


def test_info_token_sem_arquivo_sem_secret_retorna_none(monkeypatch, tmp_path):
    monkeypatch.setattr(sheets, "_TOKEN_PATH", tmp_path / "nope.json")
    monkeypatch.setattr(sheets, "GOOGLE_TOKEN_JSON", "")
    assert sheets._info_token() is None


def test_info_token_prefere_arquivo_local(monkeypatch, tmp_path):
    token = tmp_path / ".google_token.json"
    token.write_text(json.dumps({"refresh_token": "do_arquivo"}), encoding="utf-8")
    monkeypatch.setattr(sheets, "_TOKEN_PATH", token)
    monkeypatch.setattr(
        sheets, "GOOGLE_TOKEN_JSON", json.dumps({"refresh_token": "do_secret"})
    )
    assert sheets._info_token() == {"refresh_token": "do_arquivo"}
