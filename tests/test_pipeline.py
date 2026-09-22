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
