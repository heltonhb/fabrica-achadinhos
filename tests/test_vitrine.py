"""Testes da vitrine estática (gerar_vitrine.py)."""

from __future__ import annotations

import html
from pathlib import Path
import pytest

from config import Produto
from scripts import gerar_vitrine


class TestFiltroVitrine:
    def test_pula_sem_nome_ou_sem_link(self):
        prods = [
            Produto(id="#01", nome="Produto 1", link_afiliado="https://shopee/1"),
            Produto(id="#02", nome="", link_afiliado="https://shopee/2"),  # sem nome
            Produto(id="#03", nome="Produto 3", link_afiliado=""),         # sem link
            Produto(id="", nome="Produto 4", link_afiliado="https://shopee/4"), # sem id
            Produto(id="#05", nome="   ", link_afiliado="https://shopee/5"), # nome espaços
            Produto(id="#06", nome="Produto 6", link_afiliado="   "),      # link espaços
        ]
        filtrados = gerar_vitrine.filtrar_produtos_vitrine(prods)
        assert len(filtrados) == 1
        assert filtrados[0].id == "#01"
        assert filtrados[0].nome == "Produto 1"

    def test_lista_vazia(self):
        assert gerar_vitrine.filtrar_produtos_vitrine([]) == []


class TestGerarHtmlVitrine:
    def test_contem_elementos_obrigatorios(self):
        p = Produto(
            id="#10",
            nome="Copo Térmico Inox <Edição Especial>",
            nicho="Cozinha & Casa",
            preco="49,90",
            link_afiliado="https://s.shopee.com.br/teste123",
            gancho="Mantém gelado por 12 horas seguidas!",
        )
        mapa_imgs = {"#10": None}
        conteudo = gerar_vitrine.gerar_html_vitrine([p], mapa_imgs)

        # Assinatura de afiliado obrigatória
        assert 'rel="noopener sponsored"' in conteudo
        assert 'target="_blank"' in conteudo
        assert 'href="https://s.shopee.com.br/teste123"' in conteudo

        # Escape seguro de caracteres especiais
        assert "&lt;Edição Especial&gt;" in conteudo
        assert "<Edição Especial>" not in conteudo
        assert "Cozinha &amp; Casa" in conteudo

        # Formatação de preço e ID
        assert "R$ 49,90" in conteudo
        assert "#10" in conteudo

        # Placeholder CSS presente quando sem imagem
        assert "card-img-placeholder" in conteudo
        assert "card-img" not in conteudo or '<img src=' not in conteudo

    def test_card_com_imagem(self):
        p = Produto(
            id="#11",
            nome="Mini Processador",
            nicho="Cozinha",
            preco="29,90",
            link_afiliado="https://shopee/mini",
        )
        mapa_imgs = {"#11": "assets/11_MiniProcessador.jpg"}
        conteudo = gerar_vitrine.gerar_html_vitrine([p], mapa_imgs)

        assert '<img src="assets/11_MiniProcessador.jpg"' in conteudo
        assert 'alt="Mini Processador"' in conteudo


class TestImagensVitrine:
    def test_encontrar_imagem_ja_existente_em_assets(self, tmp_path):
        v_dir = tmp_path / "vitrine"
        assets_dir = v_dir / "assets"
        assets_dir.mkdir(parents=True)

        p = Produto(id="#01", nome="Lencol 400 fios", link_afiliado="https://shopee/1")
        img_fake = assets_dir / f"{p.slug}.jpg"
        img_fake.write_bytes(b"\xFF\xD8\xFFfakejpeg")

        resultado = gerar_vitrine.encontrar_ou_copiar_imagem(p, vitrine_dir=v_dir)
        assert resultado == f"assets/{p.slug}.jpg"

    def test_copiar_imagem_de_midias_para_assets(self, tmp_path):
        v_dir = tmp_path / "vitrine"
        m_dir = tmp_path / "Midias"
        p = Produto(id="#02", nome="Aspirador Portatil", link_afiliado="https://shopee/2")

        pasta_produto = m_dir / p.slug
        pasta_produto.mkdir(parents=True)

        # Cria imagens simuladas em Midias/
        img_var = pasta_produto / "shopee_variant_1.jpeg"
        img_var.write_bytes(b"var_img")
        img_main = pasta_produto / "shopee_main_0.jpeg"
        img_main.write_bytes(b"main_img_prioritaria")

        # Executa a busca/cópia
        resultado = gerar_vitrine.encontrar_ou_copiar_imagem(p, vitrine_dir=v_dir, midias_dir=m_dir)

        # Deve preferir a imagem main
        destino = v_dir / "assets" / f"{p.slug}.jpg"
        assert destino.exists()
        assert destino.read_bytes() == b"main_img_prioritaria"
        assert resultado == f"assets/{p.slug}.jpg"

    def test_sem_imagem_retorna_none(self, tmp_path):
        v_dir = tmp_path / "vitrine"
        m_dir = tmp_path / "Midias"
        p = Produto(id="#99", nome="Sem Imagem", link_afiliado="https://shopee/sem")

        resultado = gerar_vitrine.encontrar_ou_copiar_imagem(p, vitrine_dir=v_dir, midias_dir=m_dir)
        assert resultado is None


class TestConstruirVitrineEndToEnd:
    def test_construir_vitrine_gera_arquivo_e_metricas(self, tmp_path, monkeypatch):
        prods_mock = [
            Produto(id="#01", nome="Item 1", preco="19,90", link_afiliado="https://shopee/1"),
            Produto(id="#02", nome="Item 2", preco="29,90", link_afiliado="https://shopee/2"),
            Produto(id="#03", nome="Item Sem Link", preco="39,90", link_afiliado=""),
        ]
        monkeypatch.setattr(gerar_vitrine, "ler_produtos", lambda: prods_mock)

        res = gerar_vitrine.construir_vitrine(vitrine_dir=tmp_path)

        assert res["total"] == 3
        assert res["elegiveis"] == 2
        assert res["com_cta"] == 2
        assert Path(res["arquivo"]).exists()

        html_gerado = Path(res["arquivo"]).read_text(encoding="utf-8")
        assert "Item 1" in html_gerado
        assert "Item 2" in html_gerado
        assert "Item Sem Link" not in html_gerado
