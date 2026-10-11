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
        lambda prod, forcar, estilo, usar_ganchos, *a, **kw: {
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


def test_atualizar_campos_completos(monkeypatch):
    import server
    import urllib.parse

    # nada é persistido de verdade durante o teste (evita gravar no CSV/Sheets)
    monkeypatch.setattr(server, "salvar_produtos", lambda prods: None)

    res_lista = client.get("/api/produtos")
    alvo = res_lista.json()[0]
    pid_enc = urllib.parse.quote(alvo["ID"], safe="")
    antes = {
        "nome": alvo["Nome do Produto"],
        "nicho": alvo["Nicho"],
        "preco": alvo["Preco Medio (R$)"],
        "comissao": alvo["Comissao Est (R$)"],
        "link_vitrine": alvo["Link Vitrine (Bio)"],
    }

    try:
        response = client.patch(f"/api/produtos/{pid_enc}", json={
            "nome": "Produto Teste Edição",
            "nicho": "casa",
            "preco": "R$ 39.9",
            "comissao": "3,50",
            "link_vitrine": "https://s.shopee.com.br/vitrine-teste",
        })
        assert response.status_code == 200
        p = response.json()["produto"]
        assert p["Nome do Produto"] == "Produto Teste Edição"
        assert p["Nicho"] == "casa"
        assert p["Preco Medio (R$)"] == "39,90"
        assert p["Comissao Est (R$)"] == "3,50"
        assert p["Link Vitrine (Bio)"] == "https://s.shopee.com.br/vitrine-teste"
    finally:
        # devolve o cache em memória ao estado original
        cache = next(x for x in server._PRODUTOS_CACHE if x.id == alvo["ID"])
        for campo, valor in antes.items():
            setattr(cache, campo, valor)


def test_atualizar_preco_nao_numerico_e_preservado(monkeypatch):
    import server
    import urllib.parse

    monkeypatch.setattr(server, "salvar_produtos", lambda prods: None)
    res_lista = client.get("/api/produtos")
    alvo = res_lista.json()[0]
    pid_enc = urllib.parse.quote(alvo["ID"], safe="")
    antes = alvo["Preco Medio (R$)"]

    try:
        response = client.patch(f"/api/produtos/{pid_enc}", json={"preco": "sob consulta"})
        assert response.status_code == 200
        assert response.json()["produto"]["Preco Medio (R$)"] == "sob consulta"
    finally:
        cache = next(x for x in server._PRODUTOS_CACHE if x.id == alvo["ID"])
        cache.preco = antes


def test_api_vitrine_metricas_ok(monkeypatch):
    import analytics

    fake = {"visitantes": 10, "cliques_cta": 2, "ctr_pct": 20.0}
    monkeypatch.setattr(analytics, "estatisticas_vitrine", lambda **kw: fake)

    resp = client.get("/api/vitrine/metricas?dias=7")
    assert resp.status_code == 200
    assert resp.json()["metricas"]["ctr_pct"] == 20.0


def test_api_vitrine_metricas_erro_amigavel(monkeypatch):
    import analytics

    def _explode(**_kw):
        raise analytics.ErroAnalytics("Token do GoatCounter inválido ou expirado.")

    monkeypatch.setattr(analytics, "estatisticas_vitrine", _explode)

    resp = client.get("/api/vitrine/metricas")
    assert resp.status_code == 400
    assert "Token do GoatCounter" in resp.json()["detail"]


def test_vitrine_status_reporta_analytics():
    resp = client.get("/api/vitrine/status")
    dados = resp.json()
    assert "tem_token_analytics" in dados
    assert "analytics_site" in dados


def test_normalizar_preco_formatos():
    from config import normalizar_preco

    assert normalizar_preco("39,90") == "39,90"
    assert normalizar_preco("R$ 39.90") == "39,90"
    assert normalizar_preco("1.234,56") == "1.234,56"
    assert normalizar_preco("1234.5") == "1.234,50"
    assert normalizar_preco("") == ""
    assert normalizar_preco("sob consulta") == "sob consulta"



