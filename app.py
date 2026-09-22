"""
app.py — Streamlit UI: Fábrica de Achadinhos.
Gerencia produtos no Google Sheets e gera prompts para criativos.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace as dc_replace
from pathlib import Path

import streamlit as st

# garante que o diretório do projeto está no path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets import Produto, ler_produtos, salvar_produtos, _get_sheets_service
from prompts import (
    gerar_prompt_video,
    gerar_prompt_podcast,
    gerar_prompt_carrossel,
    gerar_todos_prompts,
    ESTILOS,
)
from roteirista import gerar_ganchos
from midia import resumo_midia, gerar_links_busca, criar_pasta_midia, MIDIAS_DIR, _slugificar
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
if "produtos" not in st.session_state:
    st.session_state.produtos = []
if "indice_editando" not in st.session_state:
    st.session_state.indice_editando = None
if "opcoes_gancho" not in st.session_state:
    st.session_state.opcoes_gancho = []
if "gancho_selecionado" not in st.session_state:
    st.session_state.gancho_selecionado = ""
if "produto_id_prompt" not in st.session_state:
    # rastreia qual produto está ativo na tab Gerar Prompt
    st.session_state.produto_id_prompt = None


def _limpar_estado_prompt() -> None:
    """Zera todos os estados ligados à tab Gerar Prompt."""
    st.session_state.opcoes_gancho = []
    st.session_state.gancho_selecionado = ""
    st.session_state.prompt_gerado = None


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
        st.warning("🟡 Google Sheets: somente leitura (configure OAUTH_CLIENT_JSON)")
    st.markdown(f"**Produtos:** {len(st.session_state.produtos)}")
    st.divider()
    st.markdown("#### Como usar")
    st.markdown("""
    1. Recarregue para ler a planilha
    2. Clique num produto para ver/gerar prompts
    3. Copie o prompt e cole no Google Vids ou NotebookLM
    """)

# ─── Carrega dados na primeira vez ────────────────────────────────────────────
if not st.session_state.produtos:
    recarregar()

# ─── Abas principais ─────────────────────────────────────────────────────────
tab_lista, tab_novo, tab_midia, tab_legenda, tab_prompt = st.tabs([
    "📋 Produtos", "➕ Novo Produto", "🎬 Mídia", "📝 Legenda", "🤖 Gerar Prompt"
])

# ─── TAB: Lista de Produtos ──────────────────────────────────────────────────
with tab_lista:
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

                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button(f"🎬 Gerar prompt", key=f"btn_prompt_{i}", use_container_width=True):
                        st.session_state.indice_editando = i
                        st.rerun()
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
                    st.session_state.produtos.pop(idx)
                    salvar_produtos(st.session_state.produtos)
                    st.session_state.confirmar_delete = None
                    st.success(f"🗑️ Produto {p.id} deletado!")
                    st.rerun()
            with col_nao:
                if st.button("❌ Cancelar", use_container_width=True):
                    st.session_state.confirmar_delete = None
                    st.rerun()

# ─── TAB: Novo Produto ───────────────────────────────────────────────────────
with tab_novo:
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
            else:
                novo = Produto(
                    id=novo_id,
                    nome=novo_nome,
                    nicho=novo_nicho,
                    preco=novo_preco,
                    comissao=novo_comissao,
                    link_afiliado=novo_link_af,
                    link_vitrine=novo_link_vit,
                    gancho=novo_gancho,
                )
                st.session_state.produtos.append(novo)
                salvar_produtos(st.session_state.produtos)
                st.success(f"✅ Produto {novo_id} adicionado! (salvo localmente)")
                st.rerun()

# ─── TAB: Mídia (B-Roll de Fornecedores) ────────────────────────────────────
with tab_midia:
    st.subheader("🎬 Mineração e Extração de Mídia")

    if not st.session_state.produtos:
        st.info("Carregue a planilha primeiro (sidebar → Recarregar)")
    else:
        # visão geral
        st.markdown("#### Visão Geral")
        cols = st.columns(len(st.session_state.produtos))
        for i, p in enumerate(st.session_state.produtos):
            slug = p.id.replace("#", "") + "_" + _slugificar(p.nome)
            r = resumo_midia(slug)
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
        slug = p.id.replace("#", "") + "_" + _slugificar(p.nome)

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
                    st.success("✅ Mídia pronta para render!")
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

# ─── TAB: Legenda Instagram ──────────────────────────────────────────────────
with tab_legenda:
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

        if st.button("⚡ Gerar Legenda", use_container_width=True, type="primary"):
            leg = gerar_legenda(p, mapa_estilo[estilo])
            st.session_state.legenda_gerada = leg

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
            col_a, col_b, col_c = st.columns(3)
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
                    data=leg.comentario_fixo,
                    file_name=f"comentario_{p.id}.txt",
                    mime="text/plain",
                    use_container_width=True,
                )
            with col_c:
                if st.button("📋 Copiar tudo", use_container_width=True):
                    st.write("Copiado! Cole direto no Instagram.")

            # preview de todos os estilos
            with st.expander("👀 Ver todos os estilos", expanded=False):
                todas = gerar_todas_legendas(p)
                for nome, l in todas.items():
                    st.markdown(f"**{nome.upper()}:**")
                    st.code(l.completa, language=None)
                    if l.comentario_fixo:
                        st.caption(f"💬 Comentário: {l.comentario_fixo}")
                    st.divider()

# ─── TAB: Gerar Prompt ───────────────────────────────────────────────────────
with tab_prompt:
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
            gerar_btn = st.button("🎲 Sugerir 3 ganchos", use_container_width=True)

        if gerar_btn:
            with st.spinner("Gemini gerando opções de gancho..."):
                opcoes_gancho = gerar_ganchos(p)
            if opcoes_gancho:
                st.session_state.opcoes_gancho = opcoes_gancho
            else:
                st.error("Não foi possível gerar ganchos. Verifique a GEMINI_API_KEY.")

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

        if st.button("⚡ Gerar Prompt", use_container_width=True, type="primary"):
            tipo = mapa_tipo[tipo_criativo]
            st.session_state.prompt_gerado = None

            with st.spinner("Gemini gerando prompt..."):
                if tipo in ("reels", "tiktok"):
                    resultado = gerar_prompt_video(
                        p_para_gerar, tipo, estilo_sel,
                        uso_inusitado=uso_inusitado_val,
                        estrategia_parte2=estrategia_val,
                    )
                elif tipo == "podcast":
                    resultado = [gerar_prompt_podcast(p_para_gerar)]
                else:
                    resultado = [gerar_prompt_carrossel(p_para_gerar)]

            st.session_state.prompt_gerado = resultado
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
                    ):
                        st.session_state.prompt_gerado = None
                        st.rerun()

            if len(prompts) > 1:
                with st.expander("🔧 Metadados"):
                    st.json(prompts[0].to_json())
