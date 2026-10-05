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


def test_api_vitrine_status():
    response = client.get("/api/vitrine/status")
    assert response.status_code == 200
    dados = response.json()
    assert "vitrine_url" in dados
    assert "tem_hook" in dados


def test_api_vitrine_deploy_sem_hook():
    response = client.post("/api/vitrine/deploy")
    # Deve retornar 400 ou 200 dependendo se há VERCEL_DEPLOY_HOOK no ambiente
    assert response.status_code in (200, 400)


def test_gerar_legenda_shorts_api():
    res_lista = client.get("/api/produtos")
    primeiro_id = res_lista.json()[0]["ID"]

    response = client.post("/api/ia/legenda", json={
        "produto_id": primeiro_id,
        "estilo": "shorts",
        "apenas_template": True
    })
    assert response.status_code == 200
    dados = response.json()
    assert dados["sucesso"] is True
    assert "#Shorts" in dados["hashtags"]
    assert "canal" in dados["comentario_fixo"].lower() or "vitrine" in dados["comentario_fixo"].lower()


def test_api_pipeline_executar(monkeypatch, tmp_path):
    import server

    res_lista = client.get("/api/produtos")
    primeiro_id = res_lista.json()[0]["ID"]

    # Mock do processar_produto para ser rápido e testar integração
    monkeypatch.setattr(
        server,
        "processar_produto",
        lambda prod, forcar, estilo, usar_ganchos: {
            "ok": True,
            "log": ["gancho gerado", "pacote pronto"],
            "pacote": str(tmp_path / "pacote_post.txt"),
        }
    )
    (tmp_path / "pacote_post.txt").write_text("═══ ACHADINHO YOUTUBE SHORTS ═══", encoding="utf-8")

    response = client.post("/api/ia/pipeline", json={
        "produto_id": primeiro_id,
        "estilo": "chocante",
        "forcar": True
    })
    assert response.status_code == 200
    dados = response.json()
    assert dados["sucesso"] is True
    assert "ACHADINHO YOUTUBE SHORTS" in dados["pacote_texto"]



