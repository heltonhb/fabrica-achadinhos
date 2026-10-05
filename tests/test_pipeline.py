"""Pipeline sem render: só gancho → roteiro → pacote (vídeo no Google Vids)."""

from __future__ import annotations

import inspect

import pipeline


def test_pipeline_importa_sem_render_voz_trilha():
    """O orquestrador não deve mais puxar as etapas locais de vídeo."""
    assert not hasattr(pipeline, "renderizar")
    assert not hasattr(pipeline, "gerar_voz")
    assert not hasattr(pipeline, "gerar_trilha")
    assert not hasattr(pipeline, "gerar_badge")


def test_montar_pacote_nao_requer_video():
    sig = inspect.signature(pipeline.montar_pacote)
    assert "video_path" not in sig.parameters
    assert "p" in sig.parameters


def test_processar_produto_retorna_ok_com_pacote():
    fonte = inspect.getsource(pipeline.processar_produto)
    assert '"pacote": str(pacote)' in fonte
    assert '"video"' not in fonte
    # status só avança a partir de "Ideia" (não regride o manual)
    assert 'p.status = "Roteiro Pronto"' in fonte


def test_escolher_gancho_com_dicts_e_strings():
    # Lista com dicts normais
    ganchos_dicts = [
        {"angulo": "dor", "texto": "Gancho dor"},
        {"angulo": "surpresa", "texto": "Gancho surpresa"},
    ]
    # surpresa é preferida conforme _ANGULO_PREFERIDO
    assert pipeline._escolher_gancho(ganchos_dicts) == "Gancho surpresa"

    # Lista apenas com strings
    ganchos_strings = ["Texto puro 1", "Texto puro 2"]
    assert pipeline._escolher_gancho(ganchos_strings) == "Texto puro 1"

    # Lista vazia
    assert pipeline._escolher_gancho([]) == ""


def test_gerar_ganchos_com_strings(monkeypatch):
    import roteirista
    from config import Produto

    p = Produto(id="#01", nome="Teste")
    # Simula Gemini retornando array de strings
    monkeypatch.setattr(
        roteirista,
        "_chamar_gemini",
        lambda **kw: '{"ganchos": ["Gancho direto 1", "Gancho direto 2"]}',
    )
    res = roteirista.gerar_ganchos(p)
    assert len(res) == 2
    assert isinstance(res[0], dict)
    assert res[0]["texto"] == "Gancho direto 1"
    assert "angulo" in res[0]


def test_montar_pacote_contem_secao_youtube_shorts(tmp_path, monkeypatch):
    from config import Produto

    monkeypatch.setattr(Produto, "pasta", property(lambda self: tmp_path))
    p = Produto(
        id="#42",
        nome="Mini Processador Manual",
        preco="25,90",
        link_vitrine="https://vitrine.test",
        link_afiliado="https://shope.ee/test",
    )
    p.roteiro = {
        "locucao": "Olha a facilidade desse mini processador. Link no perfil canal código 42",
        "titulos_shorts": ["Mini Processador que economiza tempo! #Shorts"],
        "texto_na_tela": ["🔥 MENOS DE R$ 26", "Link no canal | Código #42"],
        "comentario_fixo_shorts": "🛒 Link oficial no perfil! É o produto #42.",
        "legenda": "Legenda Reels",
        "hashtags": ["achadinhos", "shopee"],
    }

    pacote = pipeline.montar_pacote(p)
    assert pacote.exists()
    conteudo = pacote.read_text(encoding="utf-8")
    assert "YOUTUBE SHORTS" in conteudo
    assert "Mini Processador que economiza tempo! #Shorts" in conteudo
    assert "Código da Vitrine: #42" in conteudo
    assert "INSTAGRAM REELS" in conteudo


def test_gerar_prompt_video_shorts(monkeypatch):
    import prompts
    from config import Produto

    p = Produto(id="#15", nome="Garrafa Térmica Digital", preco="34,90")
    monkeypatch.setattr(
        prompts,
        "_chamar_gemini",
        lambda sys, user, **kw: f"VERTICAL 1080 BRAZILIAN PORTUGUESE CTA link no canal: {user[:40]}",
    )
    resultado = prompts.gerar_prompt_video(p, plataforma="shorts")
    assert len(resultado) == 2
    assert "shorts" in resultado[0].tipo.lower()
    # Checa que gerou com o metadado correto
    assert resultado[0].metadados["plataforma"] == "shorts"


