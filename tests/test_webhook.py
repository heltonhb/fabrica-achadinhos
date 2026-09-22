"""Testes do webhook Instagram: verify, payload de comentário e lookup de link."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import webhook_insta as wh
from config import Produto


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(wh, "VERIFY_TOKEN", "token_teste")
    monkeypatch.setattr(wh, "PAGE_ID", "page_1")
    monkeypatch.setattr(wh, "ACCESS_TOKEN", "tok")
    return TestClient(wh.app)


class TestVerify:
    def test_token_correto(self, client: TestClient):
        r = client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "token_teste",
                "hub.challenge": "12345",
            },
        )
        assert r.status_code == 200
        assert r.json() == 12345

    def test_token_errado(self, client: TestClient):
        r = client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "errado",
                "hub.challenge": "1",
            },
        )
        assert r.status_code == 403

    def test_mode_errado(self, client: TestClient):
        r = client.get(
            "/webhook",
            params={
                "hub.mode": "unsubscribe",
                "hub.verify_token": "token_teste",
                "hub.challenge": "1",
            },
        )
        assert r.status_code == 403


def _payload_comentario(texto: str, *, user_id: str = "u1", media_id: str = "m1",
                        comment_id: str = "c1") -> dict:
    return {
        "object": "instagram",
        "entry": [{
            "id": "ig",
            "time": 1,
            "changes": [{
                "field": "comments",
                "value": {
                    "from": {"id": user_id, "username": "aluno"},
                    "text": texto,
                    "id": comment_id,
                    "media": {"id": media_id},
                },
            }],
        }],
    }


class TestHandleWebhook:
    def test_gatilho_quero_chama_acoes(self, client: TestClient, monkeypatch):
        chamado = {"dm": 0, "curtida": 0, "resposta": 0, "link": []}

        monkeypatch.setattr(
            wh, "buscar_link_por_media_id",
            lambda mid: chamado["link"].append(mid) or "https://afiliado/x",
        )
        monkeypatch.setattr(
            wh, "enviar_direct_message",
            lambda uid, msg: chamado.__setitem__("dm", chamado["dm"] + 1),
        )
        monkeypatch.setattr(
            wh, "curtir_comentario",
            lambda cid: chamado.__setitem__("curtida", chamado["curtida"] + 1),
        )
        monkeypatch.setattr(
            wh, "responder_comentario",
            lambda cid, msg: chamado.__setitem__("resposta", chamado["resposta"] + 1),
        )

        r = client.post("/webhook", json=_payload_comentario("QUERO o link!"))
        assert r.status_code == 200
        assert r.json() == {"status": "success"}
        assert chamado["dm"] == 1
        assert chamado["curtida"] == 1
        assert chamado["resposta"] == 1
        assert chamado["link"] == ["m1"]

    def test_sem_palavra_chave_nao_dispara(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(wh, "enviar_direct_message", lambda *a, **k: pytest.fail("dm"))
        monkeypatch.setattr(wh, "curtir_comentario", lambda *a, **k: pytest.fail("curtida"))
        monkeypatch.setattr(wh, "responder_comentario", lambda *a, **k: pytest.fail("resposta"))

        r = client.post("/webhook", json=_payload_comentario("produto bonitinho"))
        assert r.status_code == 200
        assert r.json() == {"status": "success"}

    def test_bot_nao_responde_a_si_mesmo(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(wh, "enviar_direct_message", lambda *a, **k: pytest.fail("dm"))
        r = client.post(
            "/webhook",
            json=_payload_comentario("quero", user_id="page_1"),
        )
        assert r.status_code == 200

    def test_objeto_diferente_de_instagram_ignorado(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(wh, "enviar_direct_message", lambda *a, **k: pytest.fail("dm"))
        r = client.post("/webhook", json={"object": "page", "entry": []})
        assert r.status_code == 200


class TestBuscarLink:
    def test_encontra_media_id(self, monkeypatch):
        prods = [
            Produto(id="#01", media_id_instagram="m9", link_afiliado="https://shopee/1"),
            Produto(id="#02", media_id_instagram="m1", link_afiliado="https://shopee/2"),
        ]
        monkeypatch.setattr(wh, "ler_produtos", lambda: prods)
        assert wh.buscar_link_por_media_id("m1") == "https://shopee/2"

    def test_fallback_quando_nao_acha(self, monkeypatch):
        monkeypatch.setattr(wh, "ler_produtos", lambda: [])
        monkeypatch.setenv("LINK_VITRINE_PADRAO", "https://bio/padrao")
        assert wh.buscar_link_por_media_id("nao_existe") == "https://bio/padrao"

    def test_fallback_quando_link_vazio(self, monkeypatch):
        prods = [Produto(id="#01", media_id_instagram="m1", link_afiliado="")]
        monkeypatch.setattr(wh, "ler_produtos", lambda: prods)
        monkeypatch.setenv("LINK_VITRINE_PADRAO", "https://bio/x")
        assert wh.buscar_link_por_media_id("m1") == "https://bio/x"

    def test_erro_de_leitura_nao_propaga(self, monkeypatch):
        def _explode():
            raise RuntimeError("sheets fora")
        monkeypatch.setattr(wh, "ler_produtos", _explode)
        monkeypatch.setenv("LINK_VITRINE_PADRAO", "https://bio/safe")
        assert wh.buscar_link_por_media_id("m1") == "https://bio/safe"
