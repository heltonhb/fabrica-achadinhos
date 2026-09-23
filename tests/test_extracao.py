"""
test_extracao.py — cadastro automático a partir do link (scraping.extrair_cadastro).

Camadas cobertas com monkeypatch (nenhuma chamada real de rede/navegador):
  1. Gemini + busca do Google → scraping._chamar_gemini
  2. navegador local           → scraping._cadastro_navegador
"""

import json

import pytest

import scraping
from config import Produto, proximo_id

LINK = "https://shopee.com.br/x-i.313660590.22893738408"
LINK_SHARE = "https://shopee.com.br/opaanlp/313660590/22893738408"


# ── parsing de URL (sem rede para formatos longos) ───────────────────────────
def test_parse_url_canonica():
    assert scraping._parse_shopee_url(LINK) == ("313660590", "22893738408")


def test_parse_url_compartilhamento():
    assert scraping._parse_shopee_url(LINK_SHARE) == ("313660590", "22893738408")


# ── preço no formato da planilha ─────────────────────────────────────────────
@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("R$ 79,99", "79,99"),
        ("79.99", "79,99"),
        ("R$ 1.299,00", "1.299,00"),
        ("", ""),
        (None, ""),
        ("sem preço aqui", ""),
    ],
)
def test_normalizar_preco(entrada, esperado):
    assert scraping._normalizar_preco(entrada) == esperado


# ── camada 1: Gemini + Google Search ─────────────────────────────────────────
def test_camada_ia_preenche_tudo(monkeypatch):
    payload = json.dumps(
        {
            "nome": "Jogo de Lençol 400 Fios",
            "preco": "R$ 79,99",
            "nicho": "Cama e Mesa",
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(scraping, "_chamar_gemini", lambda *a, **k: payload)
    monkeypatch.setattr(
        scraping, "_cadastro_navegador",
        lambda u: pytest.fail("não deve chamar o navegador se a IA respondeu"),
    )

    r = scraping.extrair_cadastro(LINK)
    assert r["erro"] == ""
    assert r["camada"] == "ia"
    assert r["nome"] == "Jogo de Lençol 400 Fios"
    assert r["preco"] == "79,99"
    assert r["nicho"] == "Cama e Mesa"


def test_camada_ia_repara_json_com_fences_e_prosa(monkeypatch):
    texto = (
        "Claro! Aqui está:\n```json\n"
        '{"nome": "Mini Aspirador Portátil", "preco": "39.90", "nicho": "Casa"}\n'
        "```"
    )
    monkeypatch.setattr(scraping, "_chamar_gemini", lambda *a, **k: texto)
    monkeypatch.setattr(scraping, "_cadastro_navegador", lambda u: None)

    r = scraping.extrair_cadastro(LINK)
    assert r["camada"] == "ia"
    assert r["nome"] == "Mini Aspirador Portátil"
    assert r["preco"] == "39,90"
    assert r["nicho"] == "Casa"


def test_camada_ia_resposta_vazia_nao_conta(monkeypatch):
    vazio = json.dumps({"nome": "", "nicho": "", "preco": ""})
    monkeypatch.setattr(scraping, "_chamar_gemini", lambda *a, **k: vazio)
    monkeypatch.setattr(
        scraping, "_cadastro_navegador",
        lambda u: {"nome": "Fraldas Gel", "nicho": "Bebê", "preco": "24,90"},
    )

    r = scraping.extrair_cadastro(LINK)
    assert r["camada"] == "navegador"
    assert r["nome"] == "Fraldas Gel"


# ── camada 2: navegador local ────────────────────────────────────────────────
def test_fallback_para_navegador_quando_ia_falha(monkeypatch):
    def _ia_falha(*a, **k):
        raise RuntimeError(
            "Gemini não respondeu em nenhum modelo disponível. Último erro: m: 429"
        )

    monkeypatch.setattr(scraping, "_chamar_gemini", _ia_falha)
    monkeypatch.setattr(
        scraping, "_cadastro_navegador",
        lambda u: {"nome": "Ventilador Turbo", "nicho": "Eletro", "preco": "89,90"},
    )

    r = scraping.extrair_cadastro(LINK)
    assert r["erro"] == ""
    assert r["camada"] == "navegador"
    assert r["nome"] == "Ventilador Turbo"
    assert r["preco"] == "89,90"


def test_navegador_pula_quando_nao_ha_tela(monkeypatch):
    """Sem DISPLAY (nuvem/CI) desiste na hora — nunca tenta abrir janela."""
    monkeypatch.delenv("DISPLAY", raising=False)
    assert scraping._cadastro_navegador(LINK) is None


# ── fim das camadas ──────────────────────────────────────────────────────────
def test_sem_camadas_devolve_erro_amigavel(monkeypatch):
    def _ia_falha(*a, **k):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(scraping, "_chamar_gemini", _ia_falha)
    monkeypatch.setattr(scraping, "_cadastro_navegador", lambda u: None)

    r = scraping.extrair_cadastro(LINK)
    assert r["erro"]
    assert "à mão" in r["erro"]
    assert r["nome"] == "" and r["camada"] == ""


def test_link_vazio_avisa():
    r = scraping.extrair_cadastro("   ")
    assert "Cole o link" in r["erro"]


# ── ID automático ────────────────────────────────────────────────────────────
def test_proximo_id():
    assert proximo_id([]) == "#01"
    assert proximo_id([Produto(id="#03"), Produto(id="#07")]) == "#08"
    assert proximo_id([Produto(id="12")]) == "#13"
