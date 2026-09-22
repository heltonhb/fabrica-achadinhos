"""Testes da porta única de dados: slug, parse, CSV e validação de ID."""

from __future__ import annotations

from pathlib import Path

import pytest

from config import (
    COLUNAS,
    Produto,
    ler_csv_local,
    produto_de_linha,
    salvar_csv_local,
    validar_ids_unicos,
)


class TestSlug:
    def test_slug_basico(self):
        p = Produto(id="#07", nome="Mini Aspirador USB")
        assert p.slug == "07_MiniAspiradorUSB"

    def test_slug_remove_acentos_e_espacos(self):
        p = Produto(id="#12", nome="Gel de Limpeza p/ Frestas")
        assert " " not in p.slug
        assert "/" not in p.slug
        assert p.slug.startswith("12_")

    def test_slug_nome_vazio(self):
        p = Produto(id="#01", nome="")
        assert p.slug == "01_Produto"

    def test_slug_trunca_em_30_chars_de_nome(self):
        p = Produto(id="#01", nome="A" * 50)
        corpo = p.slug.split("_", 1)[1]
        assert len(corpo) <= 30

    def test_slug_estavel(self):
        a = Produto(id="#03", nome="Barra de Luz Monitor")
        b = Produto(id="#03", nome="Barra de Luz Monitor")
        assert a.slug == b.slug


class TestProdutoDeLinha:
    def test_parse_completo(self):
        p = produto_de_linha({
            "ID": " #05 ",
            "Status": "Editado",
            "Nome do Produto": "Alvejante",
            "Nicho": "limpeza",
            "Preco Medio (R$)": "19,90",
            "Link Afiliado Shopee": "https://shopee/x",
            "Media ID Instagram": "12345",
            "Roteiro / Gancho": "limpa em 1 min",
        })
        assert p is not None
        assert p.id == "#05"
        assert p.status == "Editado"
        assert p.nome == "Alvejante"
        assert p.media_id_instagram == "12345"
        assert p.gancho == "limpa em 1 min"

    def test_parse_sem_id_retorna_none(self):
        assert produto_de_linha({"ID": "", "Nome": "X"}) is None
        assert produto_de_linha({}) is None

    def test_parse_default_status(self):
        p = produto_de_linha({"ID": "#01"})
        assert p is not None
        assert p.status == "Ideia"

    def test_to_dict_cobre_todas_colunas(self):
        p = produto_de_linha({"ID": "#01", "Nome do Produto": "Y"})
        d = p.to_dict()
        assert set(d.keys()) == set(COLUNAS)


class TestValidarIds:
    def test_ids_unicos_ok(self):
        validar_ids_unicos([Produto(id="#01"), Produto(id="#02")])

    def test_id_duplicado(self):
        with pytest.raises(ValueError, match="duplicado"):
            validar_ids_unicos([Produto(id="#01"), Produto(id="#01")])

    def test_id_vazio(self):
        with pytest.raises(ValueError, match="sem ID"):
            validar_ids_unicos([Produto(id="")])

    def test_id_com_espaco_ainda_conta_como_duplicado(self):
        with pytest.raises(ValueError, match="duplicado"):
            validar_ids_unicos([Produto(id="#01"), Produto(id=" #01 ")])


class TestCsvRoundtrip:
    def test_roundtrip(self, tmp_path: Path):
        path = tmp_path / "achados.csv"
        original = [
            Produto(id="#01", nome="Um", status="Ideia", gancho="g1"),
            Produto(id="#02", nome="Dois", status="Postado", media_id_instagram="99"),
        ]
        salvar_csv_local(original, path)
        back = ler_csv_local(path)
        assert [p.id for p in back] == ["#01", "#02"]
        assert back[1].nome == "Dois"
        assert back[1].status == "Postado"
        assert back[1].media_id_instagram == "99"
        assert back[0].gancho == "g1"

    def test_arquivo_inexistente(self, tmp_path: Path):
        assert ler_csv_local(tmp_path / "nope.csv") == []

    def test_rejeita_duplicado_ao_salvar(self, tmp_path: Path):
        path = tmp_path / "d.csv"
        with pytest.raises(ValueError, match="duplicado"):
            salvar_csv_local([Produto(id="#A"), Produto(id="#A")], path)
        assert not path.exists()
