"""Fallback de prompts: Parte 1/2 independentes (uma falha não zera a outra)."""

from __future__ import annotations

from unittest.mock import patch

from config import Produto
import prompts as prompts_mod


def _produto() -> Produto:
    return Produto(
        id="06",
        nome="Jogo de Lençol 400 fios",
        nicho="cama e banho",
        preco="89,90",
        gancho="maciez para sua cama",
    )


def _gerar_com_fallback_retorno():
    # Parte 1 ok, Parte 2 falha → só a 2 vira placeholder
    chamadas = {"n": 0}

    def fake_chamada(system, user, temperature=0.8, **kwargs):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            return "PROMPT PARTE 1 OK"
        raise RuntimeError("Gemini não respondeu em nenhum modelo disponível")

    with patch.object(prompts_mod, "_chamar_gemini", side_effect=fake_chamada):
        res = prompts_mod.gerar_prompt_video(_produto(), "reels", "chocante")

    assert len(res) == 2
    assert res[0].prompt_texto == "PROMPT PARTE 1 OK"
    assert res[1].prompt_texto.startswith("[ERRO GEMINI] Parte 2")
    assert not res[0].prompt_texto.startswith("[ERRO")


def test_ambas_partes_falham_mostram_placeholder():
    with patch.object(prompts_mod, "_chamar_gemini", side_effect=RuntimeError("x")):
        res = prompts_mod.gerar_prompt_video(_produto(), "reels", "chocante")
    assert res[0].prompt_texto.startswith("[ERRO GEMINI] Parte 1")
    assert "Lençol" in res[0].prompt_texto or "Lençol" in res[0].prompt_texto.replace(
        "Jogo de ", ""
    )
    assert res[1].prompt_texto.startswith("[ERRO GEMINI] Parte 2")


def test_metadados_guardam_erro_real_da_api():
    """O erro da API precisa ficar em metadados["erro"] para a UI exibir."""
    with patch.object(
        prompts_mod, "_chamar_gemini",
        side_effect=RuntimeError("429 RESOURCE_EXHAUSTED cota"),
    ):
        res = prompts_mod.gerar_prompt_video(_produto(), "reels", "chocante")
    for r in res:
        assert r.prompt_texto.startswith("[ERRO GEMINI")
        assert "429" in r.metadados.get("erro", "")


def test_metadados_sem_erro_quando_gera_ok():
    with patch.object(prompts_mod, "_chamar_gemini", return_value="  PROMPT OK  "):
        res = prompts_mod.gerar_prompt_video(_produto(), "reels", "chocante")
    for r in res:
        assert r.prompt_texto == "PROMPT OK"
        assert "erro" not in r.metadados


def test_gerar_com_fallback_ok_sem_erro():
    texto, err = prompts_mod._gerar_com_fallback(lambda: "  x  ", "FB", "rot")
    assert texto == "x"
    assert err is None


def test_gerar_com_fallback_erro():
    def boom():
        raise ValueError("api fora")

    texto, err = prompts_mod._gerar_com_fallback(boom, "FB", "rot")
    assert texto == "FB"
    assert err == "api fora"
