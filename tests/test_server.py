"""
test_server.py — Testes automatizados para a API FastAPI do Stitch UI.
"""

from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

def test_index_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "Fábrica de Achadinhos" in response.text
    assert "Viral Studio Pro" in response.text

def test_listar_produtos():
    response = client.get("/api/produtos")
    assert response.status_code == 200
    dados = response.json()
    assert isinstance(dados, list)
    assert len(dados) > 0
    primeiro = dados[0]
    assert "ID" in primeiro
    assert "Nome do Produto" in primeiro
    assert "Status" in primeiro
    assert "plataforma" in primeiro

def test_metricas():
    response = client.get("/api/metricas")
    assert response.status_code == 200
    dados = response.json()
    assert "total_produtos" in dados
    assert "ideias" in dados
    assert "roteiros_prontos" in dados
    assert "estados" in dados
    assert dados["total_produtos"] > 0

def test_atualizar_produto_inexistente():
    import urllib.parse
    pid_enc = urllib.parse.quote("#9999", safe="")
    response = client.patch(f"/api/produtos/{pid_enc}", json={"status": "Editado"})
    assert response.status_code == 404

def test_atualizar_status_produto():
    import urllib.parse
    # busca primeiro produto
    res_lista = client.get("/api/produtos")
    primeiro_id = res_lista.json()[0]["ID"]
    pid_enc = urllib.parse.quote(primeiro_id, safe="")
    
    response = client.patch(f"/api/produtos/{pid_enc}", json={"status": "Ideia"})
    assert response.status_code == 200
    assert response.json()["produto"]["Status"] == "Ideia"

def test_gerar_legenda_api():
    res_lista = client.get("/api/produtos")
    primeiro_id = res_lista.json()[0]["ID"]
    
    # Testa template rápido
    response = client.post("/api/ia/legenda", json={
        "produto_id": primeiro_id,
        "estilo": "reels",
        "apenas_template": True
    })
    assert response.status_code == 200
    dados = response.json()
    assert dados["sucesso"] is True
    assert "texto" in dados
    assert "hashtags" in dados
    assert "comentario_fixo" in dados
    assert "QUERO" in dados["texto"]
    assert "#achadinhos" in dados["hashtags"]

