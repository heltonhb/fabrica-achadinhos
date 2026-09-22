"""
app.py — Streamlit UI: Fábrica de Achadinhos.
Gerencia produtos no Google Sheets e gera prompts para criativos.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import Future
from dataclasses import replace as dc_replace
from pathlib import Path
from typing import Any, Callable

import streamlit as st

# garante que o diretório do projeto está no path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets import Produto, ler_produtos, salvar_produtos, _get_sheets_service
from config import ESTADOS
from prompts import (
    gerar_prompt_video,
    gerar_prompt_podcast,
    gerar_prompt_carrossel,
    gerar_todos_prompts,
    ESTILOS,
)
from roteirista import gerar_ganchos
from midia import resumo_midia, gerar_links_busca, criar_pasta_midia, MIDIAS_DIR
from scraping import extrair_de_url, baixar_todas_midias, baixar_urls_manuais
from legenda import gerar_legenda, gerar_todas_legendas

# ─── Configuração da página ──────────────────────────────────────────────────
st.set_page_config(
    page_title="Fábrica de Achadinhos",
    page_icon="🎯",
    layout="wide",
)

st.title("🎯 Fábrica de Achadinhos")
st.caption("Gerencie produtos e gere prompts para criativos (Reels / TikTok / Podcast / Carrossel)")

# ─── Estado da sessão ────────────────────────────────────────────────────────
SECOES = [
    "📋 Produtos",
    "➕ Novo Produto",
    "🎬 Mídia",
    "🚀 Pipeline",
    "📝 Legenda",
    "🤖 Gerar Prompt",
]
if "produtos" not in st.session_state:
    st.session_state.produtos = []
if "secao" not in st.session_state:
    st.session_state.secao = SECOES[0]
if "opcoes_gancho" not in st.session_state:
    st.session_state.opcoes_gancho = []
if "gancho_selecionado" not in st.session_state:
    st.session_state.gancho_selecionado = ""
if "produto_id_prompt" not in st.session_state:
    # rastreia qual produto está ativo na seção Gerar Prompt
    st.session_state.produto_id_prompt = None
if "params_geracao" not in st.session_state:
    # parâmetros da última geração de prompt (para "Regerar este")
    st.session_state.params_geracao = None
for _job_key in (
    "job_prompt",
    "job_prompt_params",
    "job_gancho",
    "job_gancho_pid",
    "job_legenda",
    "job_legenda_pid",
):
    if _job_key not in st.session_state:
        st.session_state[_job_key] = None


def _limpar_estado_prompt() -> None:
    """Zera todos os estados ligados à seção Gerar Prompt."""
    st.session_state.opcoes_gancho = []
    st.session_state.gancho_selecionado = ""
    st.session_state.prompt_gerado = None
    st.session_state.params_geracao = None
    st.session_state.job_prompt = None
    st.session_state.job_prompt_params = None
    st.session_state.job_gancho = None
    st.session_state.job_gancho_pid = None


def _abrir_prompt_do_produto(produto_id: str) -> None:
    """Seleciona o produto na seção Gerar Prompt e navega até lá."""
    invertidos = list(reversed(st.session_state.produtos))
    try:
        idx = next(i for i, p in enumerate(invertidos) if p.id == produto_id)
    except StopIteration:
        idx = 0
    # o selectbox da seção usa a lista invertida e a chave sel_prompt
    st.session_state.sel_prompt = idx
    st.session_state.produto_id_prompt = None  # força reset de estado no próximo run
    _limpar_estado_prompt()
    st.session_state.secao = "🤖 Gerar Prompt"
    st.rerun()


def _gerar_prompts_salvos(params: dict) -> list:
    """(Re)gera prompts a partir dos parâmetros salvos em session_state."""
    p = params["produto"]
    tipo = params["tipo"]
    estilo = params["estilo"]
    if tipo in ("reels", "tiktok"):
        return gerar_prompt_video(
            p, tipo, estilo,
            uso_inusitado=params.get("uso_inusitado"),
            estrategia_parte2=params.get("estrategia", "plot_twist"),
        )
    if tipo == "podcast":
        return [gerar_prompt_podcast(p)]
    return [gerar_prompt_carrossel(p)]


# ─── Jobs em background (sobrevivem a troca de seção) ─────────────────────────
def _iniciar_job(chave: str, fn: Callable[[], Any], produto_id: str = "") -> None:
    """Roda ``fn`` em thread daemon. O Streamlit cancela o run atual ao trocar
    de seção; a thread continua e o resultado é coletado no próximo run."""
    fut: Future = Future()
    st.session_state[f"job_{chave}"] = fut
    if chave == "gancho":
        st.session_state.job_gancho_pid = produto_id
    elif chave == "legenda":
        st.session_state.job_legenda_pid = produto_id

    def _run() -> None:
        try:
            fut.set_result(fn())
        except Exception as exc:  # noqa: BLE001
            try:
                if not fut.cancelled():
                    fut.set_exception(exc)
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=_run, daemon=True, name=f"job-{chave}").start()


def _job_ativo(chave: str) -> bool:
    fut = st.session_state.get(f"job_{chave}")
    return fut is not None and not fut.done()


def _coletar_job(chave: str, produto_id: str = "") -> Any:
    """None = sem job · 'running' = em andamento · Exception · resultado."""
    fut = st.session_state.get(f"job_{chave}")
    if fut is None:
        return None

    pid_key = f"job_{chave}_pid"
    if chave == "prompt":
        params = st.session_state.get("job_prompt_params") or {}
        prod = params.get("produto")
        pid = prod.id if prod is not None else ""
    else:
        pid = st.session_state.get(pid_key) or ""

    if produto_id and pid and pid != produto_id:
        # job de outro produto — descarta
        st.session_state[f"job_{chave}"] = None
        if chave == "prompt":
            st.session_state.job_prompt_params = None
        else:
            st.session_state[pid_key] = None
        return None

    if not fut.done():
        return "running"

    st.session_state[f"job_{chave}"] = None
    if fut.cancelled():
        return None
    exc = fut.exception()
    if exc is not None:
        return exc
    resultado = fut.result()
    if chave == "prompt":
        st.session_state.prompt_gerado = resultado
        st.session_state.params_geracao = st.session_state.get("job_prompt_params")
    return resultado


def recarregar():
    st.session_state.produtos = ler_produtos()


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configurações")
    if st.button("🔄 Recarregar planilha", use_container_width=True):
        recarregar()
        st.success(f"Carregados {len(st.session_state.produtos)} produtos")
    st.divider()
    sheets_ok = _get_sheets_service() is not None
    if sheets_ok:
        st.success("🟢 Google Sheets: sincronizando")
    else:
        st.warning(
            "🟡 Google Sheets: somente leitura (rode `python auth.py`; "
            "na nuvem, defina o secret GOOGLE_TOKEN_JSON)"
        )
    st.markdown(f"**Produtos:** {len(st.session_state.produtos)}")
    st.divider()
    st.markdown("#### Como usar")
    st.markdown("""
    1. Recarregue para ler a planilha
    2. Clique num produto para ver/gerar prompts
    3. Copie o prompt e cole no Google Vids ou NotebookLM
    4. Em **🚀 Pipeline**, gere gancho, roteiro e pacote de post
    """)

# ─── Carrega dados na primeira vez ────────────────────────────────────────────
if not st.session_state.produtos:
    recarregar()

# ─── Navegação principal ─────────────────────────────────────────────────────
secao = st.radio(
    "Seção",
    SECOES,
    horizontal=True,
    key="secao",
    label_visibility="collapsed",
)

# ─── SEÇÃO: Lista de Produtos ───────────────────────────────────────────────
if secao == "📋 Produtos":
    if not st.session_state.produtos:
        st.info("Nenhum produto encontrado. Clique em 'Recarregar planilha' ou adicione um novo.")
    else:
        # métricas resumo
        col1, col2, col3, col4 = st.columns(4)
        total = len(st.session_state.produtos)
        ideias = sum(1 for p in st.session_state.produtos if p.status == "Ideia")
        editados = sum(1 for p in st.session_state.produtos if p.status == "Editado")
        postados = sum(1 for p in st.session_state.produtos if p.status == "Postado")
        col1.metric("Total", total)
        col2.metric("💡 Ideias", ideias)
        col3.metric("🎬 Editados", editados)
        col4.metric("✅ Postados", postados)

        st.divider()

        # tabela de produtos
        for i, p in enumerate(st.session_state.produtos):
            with st.expander(f"**{p.id}** — {p.nome}  |  {p.status}  |  R$ {p.preco}", expanded=False):
                c1, c2 = st.columns([2, 1])
                with c1:
                    st.markdown(f"**Nicho:** {p.nicho}")
                    st.markdown(f"**Gancho:** {p.gancho}")
                    st.markdown(f"**Comissão:** R$ {p.comissao}")
                    st.markdown(f"**Link Afiliado:** {p.link_afiliado}")
                    st.markdown(f"**Link Vitrine:** {p.link_vitrine}")
                with c2:
                    st.markdown(f"**Data Postagem:** {p.data_postagem}")
                    st.markdown(f"**Pasta Mídias:** {p.pasta_midias}")
                    st.markdown(f"**Agendado:** {p.post_agendado}")
                    if p.prompt_criativo:
                        st.success("✅ Prompt gerado")
                    else:
                        st.warning("⏳ Prompt pendente")

                # edição de status (fonte única: planilha via salvar_produtos)
                st.markdown("**Status:**")
                status_idx = ESTADOS.index(p.status) if p.status in ESTADOS else 0
                novo_status = st.selectbox(
                    "Status do fluxo",
                    ESTADOS,
                    index=status_idx,
                    key=f"status_{p.id}_{i}",
                    label_visibility="collapsed",
                )
                if novo_status != p.status:
                    anterior = p.status
                    p.status = novo_status
                    try:
                        salvar_produtos(st.session_state.produtos)
                        st.success(f"Status → **{novo_status}**")
                    except Exception as exc:
                        p.status = anterior
                        st.error(f"Falha ao salvar status: {exc}")

                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button(f"🎬 Gerar prompt", key=f"btn_prompt_{i}", use_container_width=True):
                        _abrir_prompt_do_produto(p.id)
                with col_btn2:
                    if st.button(f"🗑️ Deletar", key=f"btn_del_{i}", use_container_width=True, type="secondary"):
                        st.session_state.confirmar_delete = i
                        st.rerun()

        # confirmação de delete
        if "confirmar_delete" in st.session_state and st.session_state.confirmar_delete is not None:
            idx = st.session_state.confirmar_delete
            p = st.session_state.produtos[idx]
            st.warning(f"⚠️ Tem certeza que quer deletar **{p.id} — {p.nome}**?")
            col_sim, col_nao = st.columns(2)
            with col_sim:
                if st.button("✅ Sim, deletar", type="primary", use_container_width=True):
                    removido = st.session_state.produtos.pop(idx)
                    try:
                        salvar_produtos(st.session_state.produtos)
                    except Exception as exc:
                        st.session_state.produtos.insert(idx, removido)
                        st.error(f"Falha ao salvar: {exc}")
                        st.stop()
                    st.session_state.confirmar_delete = None
                    st.success(f"🗑️ Produto {p.id} deletado!")
                    st.rerun()
            with col_nao:
                if st.button("❌ Cancelar", use_container_width=True):
                    st.session_state.confirmar_delete = None
                    st.rerun()

# ─── SEÇÃO: Novo Produto ─────────────────────────────────────────────────────
if secao == "➕ Novo Produto":
    st.subheader("Adicionar novo produto à planilha")

    with st.form("novo_produto"):
        c1, c2 = st.columns(2)
        with c1:
            novo_id = st.text_input("ID (ex: #06)")
            novo_nome = st.text_input("Nome do Produto")
            novo_nicho = st.text_input("Nicho")
            novo_preco = st.text_input("Preço Médio (R$)")
        with c2:
            novo_gancho = st.text_area("Gancho / Roteiro", height=100)
            novo_link_af = st.text_input("Link Afiliado Shopee")
            novo_link_vit = st.text_input("Link Vitrine (Bio)")
            novo_comissao = st.text_input("Comissão Est. (R$)")

        submitted = st.form_submit_button("➕ Adicionar produto")
        if submitted:
            if not novo_id or not novo_nome:
                st.error("Preencha pelo menos ID e Nome do Produto.")
            elif any((x.id or "").strip() == novo_id.strip() for x in st.session_state.produtos):
                st.error(f"ID já existe na lista: {novo_id}")
            else:
                novo = Produto(
                    id=novo_id.strip(),
                    nome=novo_nome,
                    nicho=novo_nicho,
                    preco=novo_preco,
                    comissao=novo_comissao,
                    link_afiliado=novo_link_af,
                    link_vitrine=novo_link_vit,
                    gancho=novo_gancho,
                )
                st.session_state.produtos.append(novo)
                try:
                    salvar_produtos(st.session_state.produtos)
                except Exception as exc:
                    st.session_state.produtos.pop()
                    st.error(f"Falha ao salvar: {exc}")
                else:
                    st.success(f"✅ Produto {novo_id} adicionado!")
                    st.rerun()

# ─── SEÇÃO: Mídia (B-Roll de Fornecedores) ──────────────────────────────────
if secao == "🎬 Mídia":
    st.subheader("🎬 Mineração e Extração de Mídia")

    if not st.session_state.produtos:
        st.info("Carregue a planilha primeiro (sidebar → Recarregar)")
    else:
        # visão geral
        st.markdown("#### Visão Geral")
        cols = st.columns(len(st.session_state.produtos))
        for i, p in enumerate(st.session_state.produtos):
            r = resumo_midia(p.slug)
            with cols[i]:
                if r["pronto"]:
                    st.success(f"**{p.id}** ✅")
                    st.caption(f"{r['total_clipes']} clipes, {r['duracao_total']}s")
                elif r["existe_pasta"]:
                    st.warning(f"**{p.id}** ⚠️")
                    st.caption(f"{r['total_clipes']} clipes (faltam verticais)")
                else:
                    st.error(f"**{p.id}** ❌")
                    st.caption("Sem mídia")

        st.divider()

        # seleção do produto
        opcoes = [f"{p.id} — {p.nome}" for p in st.session_state.produtos]
        idx = st.selectbox("Selecione o produto:", range(len(opcoes)), format_func=lambda i: opcoes[i], key="sel_midia")
        p = st.session_state.produtos[idx]
        slug = p.slug

        c1, c2 = st.columns([1, 1])

        with c1:
            st.markdown(f"### {p.id} — {p.nome}")

            # cria pasta se não existe
            if st.button("📁 Criar pasta de mídia", use_container_width=True):
                criar_pasta_midia(slug)
                st.success(f"Pasta criada: Midias/{slug}/")
                st.rerun()

            # status atual
            r = resumo_midia(slug)
            if r["existe_pasta"]:
                st.markdown(f"**Pasta:** `{r['pasta']}`")
                st.markdown(f"**Clipes:** {r['total_clipes']}")
                st.markdown(f"**Verticais:** {r['verticais']}")
                st.markdown(f"**Duração total:** {r['duracao_total']}s")

                if r["pronto"]:
                    st.success("✅ Mídia pronta — o roteiro vai usar esses clipes!")
                else:
                    st.warning("⚠️ Mínimo: 3 clipes, pelo menos 2 verticais (9:16)")

                # detalhes de cada clipe
                if r["clipes"]:
                    st.markdown("**Clipes encontrados:**")
                    for c in r["clipes"]:
                        emoji = "✅" if c.ok else "⚠️"
                        st.markdown(
                            f"{emoji} `{c.arquivo}` — {c.duracao}s, "
                            f"{c.largura}x{c.altura}, {c.fps}fps, {c.orientacao}"
                        )
            else:
                st.info("Pasta de mídia não criada ainda. Clique acima para criar.")

        with c2:
            st.markdown("### 🤖 Extração Automática")
            st.markdown("Cole o link do produto para baixar imagens e vídeos automaticamente:")

            url_produto = st.text_input(
                "Link do produto (Shopee ou AliExpress):",
                placeholder="https://shopee.com.br/produto-name-i.shopid.itemid",
                key="url_scraping",
            )

            if st.button("⬇️ Baixar mídia automaticamente", use_container_width=True, type="primary"):
                if not url_produto.strip():
                    st.error("Cole um link de produto primeiro!")
                else:
                    with st.spinner("Extraindo mídia do anúncio..."):
                        dados = extrair_de_url(url_produto.strip())

                    if dados.get("fallback"):
                        # mostra instruções de fallback
                        st.warning(dados.get("instrucoes", "Não foi possível extrair mídia."))
                    elif not dados["imagens"] and not dados["videos"]:
                        st.error("❌ Não encontrou mídia neste link. Verifique se a URL está correta.")
                    else:
                        # cria pasta se não existe
                        criar_pasta_midia(slug)

                        st.info(f"Encontrado: {len(dados['imagens'])} imagens, {len(dados['videos'])} vídeos")

                        with st.spinner("Baixando arquivos..."):
                            resultado = baixar_todas_midias(dados, slug)

                        n_vid = len(resultado["videos"])
                        n_img = len(resultado["imagens"])
                        if n_vid or n_img:
                            st.success(f"✅ Baixado: {n_vid} vídeos + {n_img} imagens em Midias/{slug}/")
                            st.rerun()
                        else:
                            st.warning("Nenhum arquivo foi baixado (pode ser bloqueio anti-bot)")

            st.divider()

            # download manual por URLs
            st.markdown("### 📋 Download Manual")
            st.markdown("Cole URLs diretas de imagens ou vídeos (uma por linha):")

            urls_manuais = st.text_area(
                "URLs (uma por linha):",
                placeholder="https://cf.shopee.com.br/file/abc123.jpg\nhttps://example.com/video.mp4",
                height=120,
                key="urls_manuais",
            )

            if st.button("⬇️ Baixar URLs coladas", use_container_width=True):
                if not urls_manuais.strip():
                    st.error("Cole pelo menos uma URL!")
                else:
                    criar_pasta_midia(slug)
                    with st.spinner("Baixando..."):
                        res = baixar_urls_manuais(urls_manuais, slug)
                    n_vid = len(res["videos"])
                    n_img = len(res["imagens"])
                    if n_vid or n_img:
                        st.success(f"✅ Baixado: {n_vid} vídeos + {n_img} imagens")
                        st.rerun()
                    else:
                        st.error("Nenhum arquivo foi baixado. Verifique as URLs.")

            st.divider()
            st.markdown("### 🔍 Links de Busca")
            st.markdown("Pesquise o produto nestes sites para encontrar B-Roll:")

            links = gerar_links_busca(p.nome)
            for nome, url in links.items():
                st.markdown(f"🔗 [{nome}]({url})")

            st.divider()
            st.markdown("**Dicas de Extração:**")
            st.markdown("""
            - **Shopee:** Use extensão AliSave ou Downloader
            - **AliExpress:** Vídeos na aba "Vídeo" do produto
            - **TikTok:** Busque em inglês/mandarim
            - **Pinterest:** Busque "product demo vertical"
            - **YouTube Shorts:** Procure reviews curtos
            """)

            st.divider()
            st.markdown("**Formato Ideal:**")
            st.markdown("""
            - Vertical 9:16 (1080x1920)
            - MP4 (H.264)
            - Mínimo 2s por clipe
            - 5 clipes para ~20s de vídeo
            """)

# ─── SEÇÃO: Pipeline ─────────────────────────────────────────────────────────
if secao == "🚀 Pipeline":
    st.subheader("🚀 Pipeline — gancho → roteiro → pacote de post")

    if not st.session_state.produtos:
        st.info("Carregue a planilha primeiro (sidebar → Recarregar)")
    else:
        opcoes = [f"{p.id} — {p.nome}" for p in st.session_state.produtos]
        idx = st.selectbox(
            "Produto:", range(len(opcoes)), format_func=lambda i: opcoes[i],
            key="sel_render",
        )
        p = st.session_state.produtos[idx]

        r = resumo_midia(p.slug)
        clipes = p.clipes()

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"**Status atual:** {p.status}")
            st.markdown(f"**Pasta:** `{p.slug}`")
        with c2:
            st.markdown(f"**Clipes:** {len(clipes)}")
            if r["pronto"]:
                st.success("Mídia pronta ✅")
            elif r["existe_pasta"]:
                st.warning("Mídia incompleta ⚠️")
            else:
                st.error("Sem mídia ❌")
        with c3:
            st.markdown(f"**Estilo de roteiro:**")
            estilo_render = st.selectbox(
                "Estilo",
                list(ESTILOS.keys()),
                format_func=lambda k: ESTILOS[k]["label"],
                key="estilo_render",
                label_visibility="collapsed",
            )

        st.divider()

        col_opt1, col_opt2 = st.columns(2)
        with col_opt1:
            forcar = st.checkbox(
                "Forçar regeneração (ignora arquivos já gerados)",
                key="render_forcar",
            )
        with col_opt2:
            usar_ganchos = st.checkbox(
                "Gerar 3 ganchos com Gemini (senão usa o da planilha)",
                value=True,
                key="render_ganchos",
            )

        if st.button("🚀 Processar", type="primary", use_container_width=True):
            # import lazy: pipeline só é carregado quando o botão é clicado
            from pipeline import processar_produto

            with st.spinner(f"Processando {p.id} — gerando gancho, roteiro e pacote..."):
                try:
                    res = processar_produto(
                        p,
                        forcar=forcar,
                        estilo=estilo_render,
                        usar_ganchos=usar_ganchos,
                    )
                except Exception as exc:
                    st.session_state.ultimo_render = {
                        "id": p.id, "ok": False, "erro": str(exc), "log": [],
                    }
                    st.error(f"Falha no pipeline: {exc}")
                else:
                    res["id"] = p.id
                    st.session_state.ultimo_render = res
                    # persiste status e dados na planilha
                    try:
                        salvar_produtos(st.session_state.produtos)
                    except Exception as exc:
                        st.warning(f"Pipeline ok, mas falhou ao salvar na planilha: {exc}")
                    st.rerun()

        # resultado do último pipeline
        ultimo = st.session_state.get("ultimo_render")
        if ultimo:
            st.divider()
            st.markdown(f"#### Resultado — `{ultimo.get('id', '?')}`")
            if ultimo.get("ok"):
                st.success("✅ Pipeline concluído — vídeo agora é feito no Google Vids")
            else:
                st.error(f"✗ Erro: {ultimo.get('erro', 'desconhecido')}")

            for linha in ultimo.get("log", []):
                st.caption(f"• {linha}")

            pacote_path = ultimo.get("pacote")
            if pacote_path and Path(pacote_path).exists():
                st.download_button(
                    "📥 Baixar pacote de post (.txt)",
                    data=Path(pacote_path).read_text(encoding="utf-8"),
                    file_name=Path(pacote_path).name,
                    mime="text/plain",
                    use_container_width=True,
                )

        with st.expander("ℹ️ O que o pipeline faz"):
            st.markdown("""
            1. **Gancho** — 3 opções via Gemini (ou o da planilha)
            2. **Roteiro** — JSON 20s adaptado ao estilo e aos clipes reais
            3. **Pacote** — `pacote_post.txt` (legenda, hashtags, regras ManyChat)

            O vídeo em si é feito no Google Vids com os prompts da seção 🤖 Gerar Prompt.
            """)

# ─── SEÇÃO: Legenda Instagram ────────────────────────────────────────────────
if secao == "📝 Legenda":
    st.subheader("📝 Gerador de Legendas para Instagram")

    if not st.session_state.produtos:
        st.info("Carregue a planilha primeiro (sidebar → Recarregar)")
    else:
        # seleção do produto (invertido: último aparece primeiro)
        produtos_invertidos = list(reversed(st.session_state.produtos))
        opcoes = [f"{p.id} — {p.nome}" for p in produtos_invertidos]
        idx = st.selectbox("Selecione o produto:", range(len(opcoes)), format_func=lambda i: opcoes[i], key="sel_legenda")
        p = produtos_invertidos[idx]

        # estilo da legenda
        estilo = st.radio(
            "Estilo da legenda:",
            ["🎬 Reels/TikTok", "📸 Carrossel", "📰 Feed", "📱 Stories"],
            horizontal=True,
            key="estilo_legenda",
        )

        mapa_estilo = {
            "🎬 Reels/TikTok": "reels",
            "📸 Carrossel": "carrossel",
            "📰 Feed": "feed",
            "📱 Stories": "stories",
        }

        # coleta job de legenda (ex.: voltou de outra seção)
        r_leg = _coletar_job("legenda", p.id)
        if isinstance(r_leg, Exception):
            st.error(f"Falha ao gerar legenda: {r_leg}")
        elif r_leg is not None:
            st.session_state.legenda_gerada = r_leg

        legenda_rodando = _job_ativo("legenda")
        if st.button(
            "⚡ Gerar Legenda",
            use_container_width=True,
            type="primary",
            disabled=legenda_rodando,
        ):
            estilo_sel = mapa_estilo[estilo]
            _iniciar_job("legenda", lambda: gerar_legenda(p, estilo_sel), p.id)
            st.rerun()

        if legenda_rodando:
            st.info(
                "⏳ Gerando legenda em segundo plano — pode mudar de seção "
                "e voltar depois."
            )
            time.sleep(0.5)
            st.rerun()

        # exibe a legenda gerada
        if "legenda_gerada" in st.session_state and st.session_state.legenda_gerada:
            leg = st.session_state.legenda_gerada

            st.success(f"✅ Legenda **{leg.estilo}** gerada para **{p.nome}**")

            # legenda completa
            st.markdown("#### 📋 Legenda completa (copiar e colar)")
            st.code(leg.completa, language=None)

            # separado
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Legenda:**")
                st.code(leg.texto, language=None)
            with c2:
                st.markdown("**Hashtags:**")
                st.code(leg.hashtags, language=None)

            # comentário fixo
            if leg.comentario_fixo:
                st.markdown("#### 💬 Comentário para fixar")
                st.code(leg.comentario_fixo, language=None)

            # botões de ação
            col_a, col_b = st.columns(2)
            with col_a:
                st.download_button(
                    "📥 Baixar legenda (.txt)",
                    data=leg.completa,
                    file_name=f"legenda_{p.id}_{leg.estilo}.txt",
                    mime="text/plain",
                    use_container_width=True,
                )
            with col_b:
                st.download_button(
                    "📥 Baixar comentário (.txt)",
                    data=leg.comentario_fixo or "",
                    file_name=f"comentario_{p.id}.txt",
                    mime="text/plain",
                    use_container_width=True,
                    disabled=not leg.comentario_fixo,
                )
            st.caption("💡 Use o ícone de cópia no canto superior direito de cada bloco `st.code` para copiar.")

            # preview de todos os estilos
            with st.expander("👀 Ver todos os estilos", expanded=False):
                todas = gerar_todas_legendas(p)
                for nome, l in todas.items():
                    st.markdown(f"**{nome.upper()}:**")
                    st.code(l.completa, language=None)
                    if l.comentario_fixo:
                        st.caption(f"💬 Comentário: {l.comentario_fixo}")
                    st.divider()

# ─── SEÇÃO: Gerar Prompt ─────────────────────────────────────────────────────
if secao == "🤖 Gerar Prompt":
    st.subheader("Gerar prompt para criativo")

    if not st.session_state.produtos:
        st.info("Carregue a planilha primeiro (sidebar → Recarregar)")
    else:
        # seleção do produto (invertido: último aparece primeiro)
        produtos_invertidos = list(reversed(st.session_state.produtos))
        opcoes = [f"{p.id} — {p.nome}" for p in produtos_invertidos]
        idx_selecionado = st.selectbox(
            "Selecione o produto:",
            range(len(opcoes)),
            format_func=lambda i: opcoes[i],
            key="sel_prompt",
        )

        p = produtos_invertidos[idx_selecionado]

        # ── Detecta troca de produto e limpa estado ──────────────────────────
        if st.session_state.produto_id_prompt != p.id:
            st.session_state.produto_id_prompt = p.id
            _limpar_estado_prompt()
            st.rerun()

        # ── Coleta jobs que terminaram (ex.: usuário voltou de outra seção) ──
        r_gancho = _coletar_job("gancho", p.id)
        if isinstance(r_gancho, Exception):
            st.error(f"Não foi possível gerar ganchos: {r_gancho}")
        elif r_gancho is not None:
            if r_gancho:
                st.session_state.opcoes_gancho = r_gancho
            else:
                st.error("Não foi possível gerar ganchos. Verifique a GEMINI_API_KEY.")

        r_prompt = _coletar_job("prompt", p.id)
        if isinstance(r_prompt, Exception):
            st.error(f"Falha ao gerar prompt: {r_prompt}")

        # info do produto
        with st.expander("📝 Detalhes do produto", expanded=False):
            st.markdown(f"**{p.id}** — **{p.nome}**")
            st.markdown(f"Nicho: {p.nicho} | Preço: R$ {p.preco} | Comissão: R$ {p.comissao}")
            st.markdown(f"**Gancho atual:** {p.gancho or '_(não preenchido)_'}")
            st.markdown(f"**Link Afiliado:** {p.link_afiliado}")
            clipes = p.clipes()
            if clipes:
                st.success(f"🎬 {len(clipes)} clipe(s) disponível(is) — roteiro será adaptado ao material real")
                for c in clipes:
                    st.caption(f"  • {c.name}")
            else:
                st.warning("⚠️ Nenhum clipe em Midias/ — cortes serão genéricos")

        st.divider()

        # ── PASSO 1: Gancho ──────────────────────────────────────────────────
        st.markdown("### 1️⃣ Gancho de abertura")

        # valor inicial: gancho selecionado > gancho do produto > vazio
        gancho_inicial = st.session_state.gancho_selecionado or p.gancho or ""

        col_gancho, col_btn_gancho = st.columns([3, 1])
        with col_gancho:
            gancho_editado = st.text_input(
                "Gancho (edite ou use o do produto):",
                value=gancho_inicial,
                key=f"gancho_input_{p.id}",   # chave vinculada ao produto evita reuso
                placeholder="Ex: Esse produto me salvou da bagunça da geladeira",
            )
        with col_btn_gancho:
            st.markdown("<br>", unsafe_allow_html=True)
            gerar_btn = st.button(
                "🎲 Sugerir 3 ganchos",
                use_container_width=True,
                disabled=_job_ativo("gancho"),
            )

        if gerar_btn:
            st.session_state.opcoes_gancho = []
            _iniciar_job("gancho", lambda: gerar_ganchos(p), p.id)
            st.rerun()

        # exibe as opções de gancho
        if st.session_state.opcoes_gancho:
            st.markdown("**Escolha um gancho (clique para usar):**")
            cols_g = st.columns(3)
            for i, g in enumerate(st.session_state.opcoes_gancho):
                with cols_g[i]:
                    emoji = {"dor": "😣", "surpresa": "😮", "economia": "💰"}.get(
                        g.get("angulo", ""), "✨"
                    )
                    st.markdown(f"**{emoji} {g.get('angulo', '').upper()}**")
                    st.info(f'"{g.get("texto", "")}"')
                    st.caption(g.get("explicacao", ""))
                    if st.button("Usar este", key=f"usar_gancho_{p.id}_{i}", use_container_width=True):
                        st.session_state.gancho_selecionado = g["texto"]
                        st.session_state.opcoes_gancho = []
                        st.rerun()

        # feedback visual do gancho ativo
        gancho_final = gancho_editado.strip()
        if gancho_final and gancho_final != p.gancho:
            st.success(f"✅ Gancho personalizado ativo: **{gancho_final}**")
        elif not gancho_final:
            st.warning("⚠️ Gancho vazio — o Gemini usará um genérico")

        # monta produto com gancho corrigido (sem alterar o objeto original)
        p_para_gerar = dc_replace(p, gancho=gancho_final) if gancho_final else p

        st.divider()

        # ── PASSO 2: Tipo e Estilo ────────────────────────────────────────────
        st.markdown("### 2️⃣ Tipo e estilo do criativo")

        col_tipo, col_estilo = st.columns(2)
        with col_tipo:
            tipo_criativo = st.radio(
                "Tipo de criativo:",
                ["🎬 Reels", "🎵 TikTok", "🎙️ Podcast (NotebookLM)", "📸 Carrossel"],
                key="tipo_criativo_radio",
            )
        with col_estilo:
            estilo_opcoes = {v["label"]: k for k, v in ESTILOS.items()}
            estilo_label_sel = st.radio(
                "Estilo / persona:",
                list(estilo_opcoes.keys()),
                key="estilo_radio",
                help=(
                    "😱 Chocante — revelação dramática\n"
                    "🎓 Educativo — dica de amigo calmo\n"
                    "✨ Lifestyle — aspiracional e visual\n"
                    "💰 Comparativo — foco em economia"
                ),
            )
            estilo_sel = estilo_opcoes[estilo_label_sel]
            st.caption(ESTILOS[estilo_sel]["descricao"])

        mapa_tipo = {
            "🎬 Reels": "reels",
            "🎵 TikTok": "tiktok",
            "🎙️ Podcast (NotebookLM)": "podcast",
            "📸 Carrossel": "carrossel",
        }

        st.divider()

        # ── PASSO 2.5: Estratégia da Parte 2 ─────────────────────────────
        st.markdown("### Estratégia da Parte 2")

        estrategia = st.radio(
            "O que fazer na Parte 2 (10-20s)?",
            ["🎭 Plot Twist (uso inusitado)", "💎 Reforço de Qualidade"],
            horizontal=True,
            key="estrategia_radio",
            help=(
                "🎭 Plot Twist — mostra um uso criativo/inesperado do produto\n"
                "💎 Qualidade — reforça materiais, durabilidade, custo-benefício"
            ),
        )

        if estrategia.startswith("🎭"):
            estrategia_val = "plot_twist"
            uso_inusitado = st.text_input(
                "🎯 Uso inusitado (opcional):",
                placeholder="Ex: serve pra aspirar o teclado do notebook",
                help="Se preencher, o Gemini usa EXATAMENTE esse uso. "
                     "Se deixar em branco, ele sugere um uso livremente.",
                key="uso_inusitado_input",
            )
            uso_inusitado_val = uso_inusitado.strip() if uso_inusitado.strip() else None
        else:
            estrategia_val = "qualidade"
            uso_inusitado_val = None

        # ── PASSO 3: Gerar ────────────────────────────────────────────────────
        st.markdown("### 3️⃣ Gerar")

        prompt_rodando = _job_ativo("prompt")
        if st.button(
            "⚡ Gerar Prompt",
            use_container_width=True,
            type="primary",
            disabled=prompt_rodando,
        ):
            tipo = mapa_tipo[tipo_criativo]
            params = {
                "produto": p_para_gerar,
                "tipo": tipo,
                "estilo": estilo_sel,
                "uso_inusitado": uso_inusitado_val,
                "estrategia": estrategia_val,
            }
            st.session_state.prompt_gerado = None
            st.session_state.params_geracao = params
            st.session_state.job_prompt_params = params
            _iniciar_job("prompt", lambda: _gerar_prompts_salvos(params), p.id)
            st.rerun()

        # exibe os prompts gerados
        prompts_gerados = st.session_state.get("prompt_gerado")
        if prompts_gerados:
            prompts = prompts_gerados if isinstance(prompts_gerados, list) else [prompts_gerados]

            for prompt in prompts:
                st.divider()
                if "parte1" in prompt.tipo:
                    st.info("📌 **PARTE 1** — Apresentação do Produto (0–10s)")
                elif "parte2" in prompt.tipo:
                    st.warning("🎬 **PARTE 2** — Plot Twist + CTA (10–20s)")
                else:
                    st.success(f"✅ **{prompt.tipo.upper()}**")

                # erro real da API (o texto do prompt abaixo é só placeholder)
                erro_api = prompt.metadados.get("erro")
                if erro_api:
                    if "429" in erro_api or "RESOURCE_EXHAUSTED" in erro_api:
                        dica = "Cota free-tier esgotada (limite de ~20 req/modelo). Aguarde alguns minutos e clique em 🔄 Regerar."
                    elif "503" in erro_api or "UNAVAILABLE" in erro_api:
                        dica = "Modelo instável (503 alta demanda). Clique em 🔄 Regerar em instantes."
                    elif "GEMINI_API_KEY" in erro_api:
                        dica = (
                            "Chave não configurada — local: preencha `GEMINI_API_KEY` no "
                            "`.env`; nuvem: *Settings → Secrets* no Streamlit Cloud. "
                            "Salve a chave e então clique em 🔄 Regerar."
                        )
                    else:
                        dica = "Clique em 🔄 Regerar para tentar de novo."
                    st.error(
                        "⚠️ **Gemini falhou ao gerar este prompt** — o texto abaixo é apenas um placeholder.\n\n"
                        f"`{erro_api[:400]}`\n\n{dica}"
                    )

                estilo_meta = prompt.metadados.get("estilo", "")
                if estilo_meta and estilo_meta in ESTILOS:
                    st.caption(f"Estilo: {ESTILOS[estilo_meta]['label']}")

                st.markdown(f"**{prompt.produto_nome}**")

                # caixa de texto editável
                chave_edit = f"edit_{prompt.tipo}"
                texto_editado = st.text_area(
                    "Prompt (edite se necessário):",
                    value=prompt.prompt_texto,
                    height=300,
                    key=chave_edit,
                ) or prompt.prompt_texto

                # atualiza o prompt com a edição (se houver)
                if texto_editado != prompt.prompt_texto:
                    prompt.prompt_texto = texto_editado

                # cópia rápida (seleciona tudo com 1 clique)
                with st.expander("📋 Copiar prompt (clique pra selecionar)", expanded=False):
                    st.code(texto_editado, language=None)

                col_a, col_b = st.columns(2)
                with col_a:
                    st.download_button(
                        "📥 Baixar .txt",
                        data=texto_editado,
                        file_name=f"prompt_{prompt.produto_id}_{prompt.tipo}.txt",
                        mime="text/plain",
                        use_container_width=True,
                        key=f"dl_{p.id}_{prompt.tipo}",
                    )
                with col_b:
                    if st.button(
                        "🔄 Regerar este",
                        use_container_width=True,
                        key=f"regen_{p.id}_{prompt.tipo}",
                        disabled=_job_ativo("prompt"),
                    ):
                        params = st.session_state.get("params_geracao")
                        if not params:
                            st.error("Sem parâmetros da última geração — clique em ⚡ Gerar Prompt de novo.")
                        else:
                            st.session_state.prompt_gerado = None
                            st.session_state.job_prompt_params = params
                            _iniciar_job("prompt", lambda: _gerar_prompts_salvos(params), p.id)
                            st.rerun()

            if len(prompts) > 1:
                with st.expander("🔧 Metadados"):
                    st.json(prompts[0].to_json())

        # status do job em background — pode trocar de seção e voltar depois
        if _job_ativo("gancho") or _job_ativo("prompt"):
            st.info(
                "⏳ Processamento em segundo plano — pode mudar de seção; "
                "quando voltar aqui, o resultado aparece."
            )
            time.sleep(0.5)
            st.rerun()
