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
    assert resultado[0].metadados["loop_infinito"] is True
    assert resultado[1].metadados["loop_infinito"] is True


def test_gerar_prompt_video_loop_customizado(monkeypatch):
    import prompts
    from config import Produto

    p = Produto(id="#12", nome="Forma de Gelo", preco="29,99", gancho="Não acredito que demorei tanto")
    prompts_enviados = []

    def mock_gemini(sys, user, **kw):
        prompts_enviados.append(user)
        return 'VERTICAL 1080 BRAZILIAN PORTUGUESE CTA link no canal: Voiceover: "Não acredito que demorei tanto pra descobrir essa forma"'

    monkeypatch.setattr(prompts, "_chamar_gemini", mock_gemini)

    # 1. Com loop_infinito=True em Reels
    res_com_loop = prompts.gerar_prompt_video(p, plataforma="reels", loop_infinito=True)
    assert res_com_loop[0].metadados["loop_infinito"] is True
    # O prompt da parte 2 deve instruir loop VISUAL e CTA com o número
    assert any("VISUAL LOOP" in pr for pr in prompts_enviados)
    # A regra "não termine em conectivo aberto" vive no system prompt
    assert "Do NOT end on an open grammar" in prompts._SYSTEM_VIDEO_BASE

    # 2. Com loop_infinito=False
    res_sem_loop = prompts.gerar_prompt_video(p, plataforma="shorts", loop_infinito=False)
    assert res_sem_loop[0].metadados["loop_infinito"] is False


def test_prompt_video_exige_orcamento_por_beat(monkeypatch):
    """O prompt precisa pedir palavras por trecho, com pattern interrupt e loop visual."""
    import prompts
    from config import Produto

    p = Produto(id="#21", nome="Organizador de Cabos", preco="19,90", gancho="Cabo solto é crime")
    enviados = []
    monkeypatch.setattr(
        prompts, "_chamar_gemini",
        lambda sys, user, **kw: (enviados.append(user), "VERTICAL 1080 CTA")[1],
    )

    prompts.gerar_prompt_video(p, plataforma="shorts")
    p1, p2 = enviados[0], enviados[1]
    assert "PATTERN INTERRUPT" in p1
    assert "exactly 32 words" in p1
    assert "exactly 34 words" in p2
    # frame 1 em movimento e ritmoAccelerado são regras do system prompt
    assert prompts._SYSTEM_VIDEO_BASE.count("PATTERN INTERRUPT") >= 1


def test_prompt_video_nao_exige_conector_verbal():
    """Regressão: o loop não pode voltar a ser carregado por frase quebrada."""
    import prompts

    assert "OPEN GRAMMATICAL CONNECTOR" not in prompts._SYSTEM_VIDEO_BASE
    assert "Do NOT end on an open grammar" in prompts._SYSTEM_VIDEO_BASE


def test_roteirista_loop_infinito(monkeypatch):
    import roteirista
    from config import Produto

    p = Produto(id="#02", nome="Aspirador Portátil", preco="49,90", gancho="Seu carro nunca mais vai ficar sujo")
    prompts_enviados = []

    monkeypatch.setattr(
        roteirista,
        "_chamar_gemini",
        lambda system_prompt, user_prompt, **kw: (
            prompts_enviados.append(user_prompt),
            '{"locucao": "teste", "cortes": ["c1"], "texto_na_tela": ["t1"]}'
        )[1],
    )

    r = roteirista.gerar_roteiro(p, loop_infinito=True)
    assert r is not None
    assert r["_meta"]["loop_infinito"] is True
    assert "LOOP VISUAL (Seamless Loop)" in prompts_enviados[0]
    # O loop é carregado pelo quadro, não por frase quebrada
    assert "NUNCA em conectivo gramatical aberto" in prompts_enviados[0]
    # O CTA precisa citar o número do produto em voz alta
    assert "Vai pro perfil e procura o 02" in prompts_enviados[0]
    # E precisa proibir o português quebrado que o Gemini inventou
    assert "garanta seu link" in prompts_enviados[0].lower()


def test_cta_do_prompt_video_cita_o_numero_do_produto(monkeypatch):
    """O CTA precisa dizer o número do produto, senão o compra não acha na vitrine."""
    import prompts
    from config import Produto

    p = Produto(id="#37", nome="Furadeira sem Fio", preco="89,90")
    enviados = []
    monkeypatch.setattr(
        prompts, "_chamar_gemini",
        lambda sys, user, **kw: (enviados.append(user), "VERTICAL 1080")[1],
    )

    # Shorts com loop (padrão) e sem loop
    prompts.gerar_prompt_video(p, plataforma="shorts")
    prompts.gerar_prompt_video(p, plataforma="shorts", loop_infinito=False)
    p2_loop, p2_sem_loop = enviados[1], enviados[3]

    assert "procura o 37" in p2_loop
    assert "Say the number 37 slowly" in p2_loop
    assert "procura o 37" in p2_sem_loop
    assert "garanta seu link" in p2_loop.lower()


def test_system_prompt_proibe_portugues_quebrado_no_cta():
    """Regressão: 'garanta seu link' voltou uma vez, não pode voltar."""
    import prompts

    base = prompts._SYSTEM_VIDEO_BASE.lower()
    # citado como exemplo do que NÃO fazer
    assert "garanta seu link" in base
    assert "adquira o seu link" in base
    assert "you do not" in base and "guarantee, acquire or own a link" in base


def test_roteirista_mede_locucao_contra_orcamento(monkeypatch, caplog):
    """A contagem de palavras precisa entrar no _meta e avisar fora da faixa."""
    import logging

    import roteirista
    from config import Produto

    p = Produto(id="#77", nome="Cesto Organizador", preco="25,00")

    def fake(system_prompt, user_prompt, **kw):
        longa = " ".join(["palavra"] * 90)
        return '{"locucao": "' + longa + '"}'

    monkeypatch.setattr(roteirista, "_chamar_gemini", fake)
    with caplog.at_level(logging.WARNING, logger="roteirista"):
        r = roteirista.gerar_roteiro(p)

    assert r is not None
    assert r["_meta"]["palavras_locucao"] == 90
    assert any("acima do orçamento" in m for m in caplog.messages)



