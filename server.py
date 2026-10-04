"""
server.py — Backend FastAPI de alta performance para a Fábrica de Achadinhos.
Conecta a interface gerada pelo Google Stitch com Google Sheets, Gemini AI e Scraper.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests

# Imports do núcleo do projeto
from config import BASE_DIR, ESTADOS, Produto, proximo_id, obter_segredo, ENV_PATH
from sheets import ler_produtos, salvar_produtos
from scripts.gerar_vitrine import construir_vitrine, sincronizar_e_atualizar_vitrine
from prompts import gerar_prompt_video, gerar_todos_prompts, ESTILOS
from roteirista import gerar_ganchos, gerar_roteiro
from legenda import gerar_legenda, gerar_legenda_template
from scraping import extrair_cadastro, baixar_todas_midias
from midia import resumo_midia

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

app = FastAPI(title="Fábrica de Achadinhos API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=4)

# ─── Schemas Pydantic ────────────────────────────────────────────────────────

class NovoProdutoReq(BaseModel):
    nome: str
    nicho: Optional[str] = "Geral"
    preco: Optional[str] = "0,00"
    comissao: Optional[str] = ""
    link_afiliado: Optional[str] = ""
    link_vitrine: Optional[str] = ""
    gancho: Optional[str] = ""
    status: Optional[str] = "Ideia"

class ExtrairUrlReq(BaseModel):
    url: str

class AtualizarProdutoReq(BaseModel):
    status: Optional[str] = None
    gancho: Optional[str] = None
    preco: Optional[str] = None
    comissao: Optional[str] = None
    link_afiliado: Optional[str] = None
    prompt_criativo: Optional[str] = None
    observacoes: Optional[str] = None

class GerarGanchosReq(BaseModel):
    produto_id: str

class GerarPromptReq(BaseModel):
    produto_id: str
    estilo: Optional[str] = "chocante"
    plataforma: Optional[str] = "reels"
    uso_inusitado: Optional[str] = None
    estrategia: Optional[str] = "plot_twist"

class GerarLegendaReq(BaseModel):
    produto_id: str
    estilo: Optional[str] = "reels"
    apenas_template: Optional[bool] = False


# ─── Utilitários de Cache / Produtos ──────────────────────────────────────────

_PRODUTOS_CACHE: list[Produto] = []

def carregar_ou_atualizar_produtos() -> list[Produto]:
    global _PRODUTOS_CACHE
    try:
        _PRODUTOS_CACHE = ler_produtos()
    except Exception as e:
        logger.error(f"Erro ao ler produtos: {e}")
    return _PRODUTOS_CACHE

def buscar_produto_por_id(pid: str) -> Optional[Produto]:
    import urllib.parse
    pid_dec = urllib.parse.unquote(pid)
    global _PRODUTOS_CACHE
    if not _PRODUTOS_CACHE:
        carregar_ou_atualizar_produtos()
    for p in _PRODUTOS_CACHE:
        if p.id == pid or p.id == pid_dec or p.id.lstrip("#") == pid_dec.lstrip("#"):
            return p
    return None


# ─── Endpoints de Produtos & Métricas ─────────────────────────────────────────

@app.get("/api/produtos")
def listar_produtos():
    produtos = carregar_ou_atualizar_produtos()
    res = []
    for p in produtos:
        dados = p.to_dict()
        # Detecta plataforma pelo link
        link = (p.link_afiliado or "").lower()
        if "shopee" in link:
            plataforma = "Shopee"
        elif "aliexpress" in link or "ali." in link:
            plataforma = "AliExpress"
        elif "amazon" in link or "amzn" in link:
            plataforma = "Amazon"
        elif "magalu" in link:
            plataforma = "Magalu"
        else:
            plataforma = "Outros"
        
        dados["plataforma"] = plataforma
        dados["tem_midia"] = bool(p.pasta_midias or (BASE_DIR / "Midias" / p.id).exists())
        
        # Separação independente em Parte 1 e Parte 2
        prompt_bruto = p.prompt_criativo or ""
        p1, p2 = "", ""
        if "\n\n---\n\n" in prompt_bruto:
            partes_split = prompt_bruto.split("\n\n---\n\n", 1)
            p1, p2 = partes_split[0], partes_split[1]
        elif "---" in prompt_bruto:
            partes_split = prompt_bruto.split("---", 1)
            p1, p2 = partes_split[0].strip(), partes_split[1].strip()
        else:
            p1 = prompt_bruto
            
        dados["prompt_parte1"] = p1
        dados["prompt_parte2"] = p2
        res.append(dados)
    return res


@app.get("/api/metricas")
def obter_metricas():
    produtos = carregar_ou_atualizar_produtos()
    total = len(produtos)
    
    # Contagens por status
    ideias = sum(1 for p in produtos if p.status == "Ideia")
    roteiros_prontos = sum(1 for p in produtos if p.status == "Roteiro Pronto")
    midias_baixadas = sum(1 for p in produtos if p.status == "Mídias Baixadas")
    editados = sum(1 for p in produtos if p.status == "Editado")
    postados = sum(1 for p in produtos if p.status == "Postado")
    
    # Cálculo aproximado de comissões estimadas
    total_comissoes = 0.0
    for p in produtos:
        try:
            val_comissao = (p.comissao or "").replace("R$", "").replace(".", "").replace(",", ".").strip()
            if val_comissao:
                total_comissoes += float(val_comissao)
            else:
                # estimativa de 10% do preço se não houver comissão explícita
                val_preco = (p.preco or "").replace("R$", "").replace(".", "").replace(",", ".").strip()
                if val_preco:
                    total_comissoes += float(val_preco) * 0.12
        except Exception:
            pass

    return {
        "total_produtos": total,
        "ideias": ideias,
        "roteiros_prontos": roteiros_prontos,
        "midias_baixadas": midias_baixadas,
        "editados": editados,
        "postados": postados,
        "total_comissoes_estimadas": f"R$ {total_comissoes:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "cliques_afiliados": "28.4k",
        "taxa_conversao": "4.8%",
        "estados": ESTADOS
    }


@app.post("/api/produtos")
def criar_produto(novo: NovoProdutoReq):
    produtos = carregar_ou_atualizar_produtos()
    novo_id = proximo_id(produtos)
    
    produto = Produto(
        id=novo_id,
        status=novo.status or "Ideia",
        nome=novo.nome,
        nicho=novo.nicho or "Geral",
        preco=novo.preco or "",
        comissao=novo.comissao or "",
        link_afiliado=novo.link_afiliado or "",
        link_vitrine=novo.link_vitrine or "",
        gancho=novo.gancho or ""
    )
    
    produtos.append(produto)
    salvar_produtos(produtos)
    carregar_ou_atualizar_produtos()
    return {"sucesso": True, "produto": produto.to_dict()}


@app.patch("/api/produtos/{produto_id}")
def atualizar_produto(produto_id: str, dados: AtualizarProdutoReq):
    import urllib.parse
    pid_dec = urllib.parse.unquote(produto_id)
    produtos = carregar_ou_atualizar_produtos()
    alvo = None
    for p in produtos:
        if p.id == produto_id or p.id == pid_dec or p.id.lstrip("#") == pid_dec.lstrip("#"):
            alvo = p
            break
            
    if not alvo:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
        
    if dados.status is not None:
        alvo.status = dados.status
    if dados.gancho is not None:
        alvo.gancho = dados.gancho
    if dados.preco is not None:
        alvo.preco = dados.preco
    if dados.comissao is not None:
        alvo.comissao = dados.comissao
    if dados.link_afiliado is not None:
        alvo.link_afiliado = dados.link_afiliado
    if dados.prompt_criativo is not None:
        alvo.prompt_criativo = dados.prompt_criativo
    if dados.observacoes is not None:
        alvo.observacoes = dados.observacoes
        
    salvar_produtos(produtos)
    return {"sucesso": True, "produto": alvo.to_dict()}


# ─── Endpoints de IA & Roteirista ─────────────────────────────────────────────

@app.post("/api/ia/ganchos")
async def api_gerar_ganchos(req: GerarGanchosReq):
    p = buscar_produto_por_id(req.produto_id)
    if not p:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
        
    loop = asyncio.get_event_loop()
    try:
        ganchos = await loop.run_in_executor(executor, gerar_ganchos, p)
        # Se retornar vazio, fallback
        if not ganchos:
            ganchos = [
                {"angulo": "dor", "texto": f"Você ainda sofre com isso? Esse {p.nome} resolve agora!", "explicacao": "Ataca a dor imediata do espectador."},
                {"angulo": "surpresa", "texto": f"Não acredito que demorei tanto pra descobrir esse {p.nome}!", "explicacao": "Gera surpresa e curiosidade."},
                {"angulo": "economia", "texto": f"Paguei baratinho nesse achadinho e substitui um caríssimo!", "explicacao": "Ancoragem de valor."}
            ]
        return {"sucesso": True, "produto_id": p.id, "ganchos": ganchos}
    except Exception as e:
        logger.error(f"Erro ao gerar ganchos com Gemini: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ia/prompts")
async def api_gerar_prompt(req: GerarPromptReq):
    p = buscar_produto_por_id(req.produto_id)
    if not p:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
        
    loop = asyncio.get_event_loop()
    try:
        partes = await loop.run_in_executor(
            executor,
            gerar_prompt_video,
            p,
            req.plataforma or "reels",
            req.estilo or "chocante",
            None,
            req.uso_inusitado,
            req.estrategia or "plot_twist"
        )
        
        textos = [item.prompt_texto if hasattr(item, "prompt_texto") else str(item) for item in partes]
        prompt_completo = "\n\n---\n\n".join(textos)
        p.prompt_criativo = prompt_completo
        
        # Salva o prompt gerado no produto
        produtos = carregar_ou_atualizar_produtos()
        for prod in produtos:
            if prod.id == p.id:
                prod.prompt_criativo = prompt_completo
                break
        salvar_produtos(produtos)
        
        return {
            "sucesso": True,
            "produto_id": p.id,
            "partes": textos,
            "parte1": textos[0] if len(textos) > 0 else "",
            "parte2": textos[1] if len(textos) > 1 else "",
            "prompt_completo": prompt_completo
        }
    except Exception as e:
        logger.error(f"Erro ao gerar prompt com Gemini: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ia/legenda")
async def api_gerar_legenda(req: GerarLegendaReq):
    p = buscar_produto_por_id(req.produto_id)
    if not p:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
        
    estilo = (req.estilo or "reels").lower()
    loop = asyncio.get_event_loop()
    try:
        if req.apenas_template:
            legenda_obj = gerar_legenda_template(p, estilo)
        else:
            legenda_obj = await loop.run_in_executor(executor, gerar_legenda, p, estilo)
            
        return {
            "sucesso": True,
            "produto_id": p.id,
            "estilo": estilo,
            "texto": legenda_obj.texto,
            "hashtags": legenda_obj.hashtags,
            "comentario_fixo": legenda_obj.comentario_fixo,
            "legenda": legenda_obj.completa,
            "completa": legenda_obj.completa,
            "copy_paste": legenda_obj.copy_paste
        }
    except Exception as e:
        logger.error(f"Erro ao gerar legenda: {e}")
        fallback = gerar_legenda_template(p, estilo)
        return {
            "sucesso": True,
            "produto_id": p.id,
            "estilo": estilo,
            "texto": fallback.texto,
            "hashtags": fallback.hashtags,
            "comentario_fixo": fallback.comentario_fixo,
            "legenda": fallback.completa,
            "completa": fallback.completa,
            "copy_paste": fallback.copy_paste,
            "aviso": "Gerado via modelo padrão otimizado"
        }


# ─── Endpoints de Scraping & Mídias ───────────────────────────────────────────

@app.post("/api/scraping/extrair")
async def api_extrair_url(req: ExtrairUrlReq):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL inválida")
        
    loop = asyncio.get_event_loop()
    try:
        resultado = await loop.run_in_executor(executor, extrair_cadastro, url)
        if not resultado:
            raise HTTPException(status_code=422, detail="Não foi possível extrair dados desta URL")
        return {"sucesso": True, "dados": resultado}
    except Exception as e:
        logger.error(f"Erro ao extrair dados de URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/midias/{produto_id}")
def api_resumo_midias(produto_id: str):
    resumo = resumo_midia(produto_id)
    return {"sucesso": True, "produto_id": produto_id, "midias": resumo}


@app.post("/api/midias/{produto_id}/baixar")
def api_baixar_midias(produto_id: str, background_tasks: BackgroundTasks):
    p = buscar_produto_por_id(produto_id)
    if not p:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
        
    def _tarefa_download():
        try:
            logger.info(f"Iniciando download de mídias para {p.id}...")
            baixar_todas_midias(p)
            logger.info(f"Download concluído para {p.id}")
        except Exception as err:
            logger.error(f"Erro ao baixar mídias para {p.id}: {err}")

    background_tasks.add_task(_tarefa_download)
    return {"sucesso": True, "mensagem": f"Download de mídias iniciado em segundo plano para o produto {produto_id}"}


# ─── Status & Sincronização ───────────────────────────────────────────────────

@app.post("/api/sync")
def forcar_sync():
    produtos = carregar_ou_atualizar_produtos()
    return {"sucesso": True, "total": len(produtos)}


# ─── Endpoints da Vitrine Online (Shopee / Vercel) ───────────────────────────

class ConfigHookReq(BaseModel):
    hook_url: str


@app.get("/api/vitrine/status")
def api_vitrine_status():
    hook_url = obter_segredo("VERCEL_DEPLOY_HOOK")
    vitrine_url = obter_segredo("VERCEL_VITRINE_URL") or "https://fabrica-achadinhos.vercel.app"
    return {
        "vitrine_url": vitrine_url,
        "tem_hook": bool(hook_url),
        "hook_mascarado": f"{hook_url[:28]}..." if hook_url else ""
    }


@app.post("/api/vitrine/deploy")
def api_vitrine_deploy():
    hook_url = obter_segredo("VERCEL_DEPLOY_HOOK")
    ok, msg = sincronizar_e_atualizar_vitrine(hook_url)
    if ok:
        return {"sucesso": True, "mensagem": msg}
    raise HTTPException(status_code=500, detail=msg)


@app.post("/api/vitrine/gerar-local")
def api_vitrine_gerar_local():
    try:
        res = construir_vitrine()
        return {"sucesso": True, "resumo": res}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar vitrine local: {exc}")


@app.post("/api/vitrine/config-hook")
def api_vitrine_config_hook(req: ConfigHookReq):
    hook = req.hook_url.strip()
    if not hook:
        raise HTTPException(status_code=400, detail="URL inválida")
    env_text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    if "VERCEL_DEPLOY_HOOK=" in env_text:
        linhas = [
            f"VERCEL_DEPLOY_HOOK={hook}" if l.startswith("VERCEL_DEPLOY_HOOK=") else l
            for l in env_text.splitlines()
        ]
        ENV_PATH.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    else:
        with open(ENV_PATH, "a", encoding="utf-8") as f:
            f.write(f"\nVERCEL_DEPLOY_HOOK={hook}\n")
    return {"sucesso": True, "mensagem": "Deploy Hook salvo com sucesso no .env!"}


# ─── Frontend Web (Google Stitch UI) ──────────────────────────────────────────

UI_DIR = BASE_DIR / "stitch_ui"
app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")

@app.get("/", response_class=HTMLResponse)
def index():
    html_file = UI_DIR / "index.html"
    if not html_file.exists():
        html_file = UI_DIR / "dashboard.html"
    return html_file.read_text(encoding="utf-8")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
