"""
analytics.py — Painel de métricas da vitrine via API do GoatCounter.

A vitrine (vitrine/index.html, gerada por scripts/gerar_vitrine.py) envia
eventos ao GoatCounter: clique no CTA por produto, busca (com/sem resultado),
filtro de nicho e visita via in-app browser. Este módulo lê esses dados de
volta pela API oficial (/api/v0) e devolve um resumo pronto pra exibir.

Configuração (via .env / variáveis de ambiente / secrets):
  GOATCOUNTER_API_TOKEN  token gerado em goatcounter.com (usuário → API)
  GOATCOUNTER_CODE       code do site (padrão: helton)

Uso:
    from analytics import estatisticas_vitrine
    resumo = estatisticas_vitrine(dias=30)
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from config import obter_segredo

logger = logging.getLogger(__name__)

# Cache em memória pra não bater na API a cada clique no app
_CACHE: dict[tuple[int, int, frozenset[str] | None], tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SEGUNDOS = 60


class ErroAnalytics(Exception):
    """Erro amigável do painel de métricas (token, rede, API)."""


def codigo_site() -> str:
    """Code do GoatCounter (mesmo usado na vitrine)."""
    return (obter_segredo("GOATCOUNTER_CODE") or "helton").strip() or "helton"


def _url_base() -> str:
    return f"https://{codigo_site()}.goatcounter.com/api/v0"


def _token() -> str:
    return obter_segredo("GOATCOUNTER_API_TOKEN").strip()


def _periodo(dias: int) -> tuple[str, str]:
    """Período (início, fim) em ISO, como a API espera."""
    hoje = dt.datetime.now()
    inicio = hoje - dt.timedelta(days=max(1, dias))
    return inicio.strftime("%Y-%m-%d"), hoje.strftime("%Y-%m-%d")


def _get(caminho: str, params: dict[str, Any], _tentativa: int = 0) -> dict[str, Any]:
    """GET autenticado na API do GoatCounter. Levanta ErroAnalytics amigável.

    Erros transitórios (404/429/5xx do edge) são retentados uma vez.
    """
    token = _token()
    if not token:
        raise ErroAnalytics(
            "Token do GoatCounter não configurado. Gere em goatcounter.com "
            "(usuário → API) e salve em GOATCOUNTER_API_TOKEN no .env."
        )
    try:
        resp = requests.get(
            f"{_url_base()}/{caminho}",
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise ErroAnalytics(f"Sem conexão com o GoatCounter: {exc}") from exc

    max_tentativas = 2 if resp.status_code == 429 else 1
    if resp.status_code in (404, 429, 500, 502, 503, 504) and _tentativa < max_tentativas:
        logger.warning("GoatCounter %s em /%s — tentando de novo", resp.status_code, caminho)
        time.sleep(1.5 * (_tentativa + 1))
        return _get(caminho, params, _tentativa + 1)

    if resp.status_code == 401:
        raise ErroAnalytics(
            "Token do GoatCounter inválido ou expirado. Gere um novo em "
            "goatcounter.com (usuário → API) e atualize GOATCOUNTER_API_TOKEN."
        )
    if resp.status_code >= 400:
        raise ErroAnalytics(
            f"GoatCounter retornou {resp.status_code} em /{caminho}: {resp.text[:200]}"
        )

    try:
        return resp.json()
    except ValueError as exc:
        raise ErroAnalytics(f"Resposta ilegível do GoatCounter em /{caminho}") from exc


# ─── Parsing (puro, testável sem rede) ────────────────────────────────────────

def decompor_evento_cta(caminho: str) -> tuple[str, str] | None:
    """'/cta/grade/20' → ('grade', '20'). None se não for evento de CTA."""
    partes = (caminho or "").strip().split("/")
    # '', 'cta', '{posição}', '{id}'
    if len(partes) >= 4 and partes[1] == "cta" and partes[2] and partes[3]:
        return partes[2], partes[3]
    return None


def normalizar_id_produto(pid: str) -> str:
    """Canonicaliza id de produto p/ comparação: '#01', '01' e '1' → '1'."""
    numeros = re.sub(r"\D", "", str(pid or ""))
    return str(int(numeros)) if numeros else ""


def resumir_hits(
    hits: list[dict[str, Any]],
    ids_conhecidos: list[str] | None = None,
) -> dict[str, Any]:
    """Agrega a lista de paths do GoatCounter no resumo do painel.

    Args:
        hits: paths retornados por /stats/hits.
        ids_conhecidos: ids da lista atual de produtos. Quando informado,
            cliques em ids que não existem mais são marcados com
            ``na_lista: False`` (produto removido da planilha).
    """
    ids_validos: set[str] | None = None
    if ids_conhecidos is not None:
        ids_validos = {normalizar_id_produto(i) for i in ids_conhecidos} - {""}
    resumo: dict[str, Any] = {
        "visualizacoes": 0,          # página da vitrine ("/")
        "visitantes": 0,
        "cliques_cta": 0,
        "visitas_inapp": 0,
        "buscas_ok": 0,
        "buscas_sem_resultado": 0,
        "produtos_clicados": [],     # [{id, posicao, cliques}]
        "buscas_falhas": [],         # [{termo, buscas}]
        "filtros": [],               # [{nicho, cliques}]
    }

    produtos: dict[tuple[str, str], int] = {}
    falhas: dict[str, int] = {}
    filtros: dict[str, int] = {}

    for hit in hits or []:
        caminho = (hit.get("path") or "").strip()
        contagem = int(hit.get("count") or 0)

        if caminho in ("/", "/index.html"):
            resumo["visualizacoes"] += int(hit.get("count_raw") or contagem)
            resumo["visitantes"] += contagem
            continue

        cta = decompor_evento_cta(caminho)
        if cta:
            # Só evento real (event=true) é clique no botão da Shopee.
            # Pageviews com path /cta/... (bot, crawler ou visita direta à URL)
            # não contam — senão aparece "produto" fantasma no painel.
            if hit.get("event"):
                posicao, pid = cta
                resumo["cliques_cta"] += contagem
                chave = (pid, posicao)
                produtos[chave] = produtos.get(chave, 0) + contagem
            else:
                logger.info("CTA ignorado (pageview, não clique): %s", caminho)
            continue

        if caminho.startswith("/busca/sem-resultado/"):
            resumo["buscas_sem_resultado"] += contagem
            termo = caminho.split("/busca/sem-resultado/", 1)[1]
            falhas[termo] = falhas.get(termo, 0) + contagem
            continue

        if caminho.startswith("/busca/ok/"):
            resumo["buscas_ok"] += contagem
            continue

        if caminho.startswith("/filtro/"):
            nicho = caminho.split("/filtro/", 1)[1]
            filtros[nicho] = filtros.get(nicho, 0) + contagem
            continue

        if caminho.startswith("/inapp/visita-inapp"):
            resumo["visitas_inapp"] += contagem

    resumo["produtos_clicados"] = [
        {
            "id": pid,
            "posicao": posicao,
            "cliques": cliques,
            # sem ids_conhecidos não há como validar → assume na lista
            "na_lista": ids_validos is None or normalizar_id_produto(pid) in ids_validos,
        }
        for (pid, posicao), cliques in sorted(produtos.items(), key=lambda kv: -kv[1])
    ]
    resumo["buscas_falhas"] = [
        {"termo": termo, "buscas": n}
        for termo, n in sorted(falhas.items(), key=lambda kv: -kv[1])
    ]
    resumo["filtros"] = [
        {"nicho": nicho, "cliques": n}
        for nicho, n in sorted(filtros.items(), key=lambda kv: -kv[1])
    ]
    return resumo


# Quebras do público: chave no resumo → endpoint da API
_QUEBRAS: dict[str, str] = {
    "navegadores": "stats/browsers",
    "sistemas": "stats/systems",
    "paises": "stats/locations",
    "dispositivos": "stats/sizes",
    "campanhas": "stats/campaigns",
}

_NOMES_DISPOSITIVO = {
    "phone": "Celular",
    "tablet": "Tablet",
    "desktop": "Computador",
    "desktophd": "Computador HD",
    "unknown": "Desconhecido",
}


def _nome_ref(ref: dict[str, Any]) -> str:
    """Nome do referrer ('name' na API atual, 'path' em versões antigas)."""
    return (ref.get("name") or ref.get("path") or "").strip()


def serie_diaria(dados_total: dict[str, Any]) -> list[dict[str, Any]]:
    """'/stats/total' → [{dia: 'AAAA-MM-DD', visitas: n}] em ordem cronológica."""
    serie = []
    for item in dados_total.get("stats") or []:
        dia = (item.get("day") or "").strip()
        if not dia:
            continue
        visitas = item.get("daily")
        if visitas is None:
            visitas = sum(item.get("hourly") or [])
        serie.append({"dia": dia, "visitas": int(visitas or 0)})
    return sorted(serie, key=lambda d: d["dia"])


def resumir_quebra(caminho: str, dados: dict[str, Any]) -> list[dict[str, Any]]:
    """Normaliza browsers/systems/locations/sizes/campaigns em [{nome, visitas, pct}]."""
    itens = []
    for s in dados.get("stats") or []:
        n = int(s.get("count") or 0)
        if n <= 0:
            continue
        ident = (s.get("id") or "").strip()
        nome = (s.get("name") or "").strip()
        if caminho == "stats/sizes":
            nome = _NOMES_DISPOSITIVO.get(ident, ident or "Desconhecido")
        elif not nome or nome == "(unknown)":
            nome = "Desconhecido"
        itens.append({"nome": nome, "visitas": n})

    # agrupa "Desconhecido" que pode vir duplicado ('' e '(unknown)')
    agrupado: dict[str, int] = {}
    for i in itens:
        agrupado[i["nome"]] = agrupado.get(i["nome"], 0) + i["visitas"]
    total = sum(agrupado.values())
    return [
        {"nome": nome, "visitas": n, "pct": round(100.0 * n / total, 1) if total else 0.0}
        for nome, n in sorted(agrupado.items(), key=lambda kv: -kv[1])
    ]


def _quebra(caminho: str, janela: dict[str, Any]) -> list[dict[str, Any]]:
    """Busca uma quebra do público; em erro devolve lista vazia (painel segue)."""
    try:
        return resumir_quebra(caminho, _get(caminho, {**janela, "limit": 10}))
    except Exception as exc:  # noqa: BLE001 — dado secundário, não derruba o painel
        logger.warning("GoatCounter: falha em /%s: %s", caminho, exc)
        return []


# ─── Tráfego detalhado ────────────────────────────────────────────────────────

# Domínios que aparecem como referrer/campanha → nome amigável no painel.
# "ig" é campanha UTM do Instagram (vitrine roda no in-app browser da bio).
_NOMES_REFERRER: dict[str, str] = {
    "instagram.com": "Instagram",
    "l.instagram.com": "Instagram",
    "lm.facebook.com": "Facebook",
    "m.facebook.com": "Facebook",
    "facebook.com": "Facebook",
    "www.facebook.com": "Facebook",
    "t.co": "X (Twitter)",
    "twitter.com": "X (Twitter)",
    "x.com": "X (Twitter)",
    "vm.tiktok.com": "TikTok",
    "www.tiktok.com": "TikTok",
    "tiktok.com": "TikTok",
    "api.whatsapp.com": "WhatsApp",
    "chat.whatsapp.com": "WhatsApp",
    "wa.me": "WhatsApp",
    "www.youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "youtube.com": "YouTube",
    "google.com": "Google (busca)",
    "www.google.com": "Google (busca)",
    "bing.com": "Bing",
    "www.bing.com": "Bing",
    "ig": "Instagram (campanha UTM 'ig')",
}

_DIAS_SEMANA = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")

# Fuso do público-alvo (Helton / Shopee BR). As horas da API são UTC.
_OFFSET_BRASILIA_HORAS = -3


def nome_amigavel_referrer(ref: str) -> str:
    """Domínio cru do GoatCounter → nome de exibição ('l.instagram.com' → 'Instagram')."""
    limpo = (ref or "").strip()
    limpo = limpo.removeprefix("https://").removeprefix("http://").rstrip("/")
    if limpo.startswith("www."):
        limpo = limpo[4:]
    # desconsidera caminho: 'instagram.com/x' → 'instagram.com'
    dominio = limpo.split("/", 1)[0]
    return _NOMES_REFERRER.get(dominio) or _NOMES_REFERRER.get(limpo) or limpo


def horas_acesso(hits: list[dict[str, Any]]) -> list[int]:
    """Visitas por hora do dia (UTC) a partir do stats/hits do path '/'.

    stats/hits com group=day devolve, por dia, a lista `hourly` com 24
    posições (confirmado na API v0). Só pageviews da vitrine contam.
    """
    horas = [0] * 24
    for hit in hits or []:
        if (hit.get("path") or "").strip() not in ("/", "/index.html"):
            continue
        for por_dia in hit.get("stats") or []:
            for hora, n in enumerate(por_dia.get("hourly") or []):
                if 0 <= hora < 24:
                    horas[hora] += int(n or 0)
    return horas


def pico_de_acesso(horas: list[int]) -> dict[str, Any] | None:
    """[{hora_utc, hora_local, visitas}] da hora com mais visitas, ou None.

    Converte p/ horário de Brasília (UTC-3); 0h UTC vira 21h do dia anterior.
    """
    if not horas or not any(horas):
        return None
    hora_utc = max(range(24), key=lambda h: horas[h])
    local = (hora_utc + _OFFSET_BRASILIA_HORAS) % 24
    return {
        "hora_utc": hora_utc,
        "hora_local": f"{local:02d}h",
        "visitas": horas[hora_utc],
    }


def visitas_por_dia_semana(serie_diaria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Soma visitas por dia da semana (Seg–Dom, na ordem)."""
    totais = [0] * 7
    for item in serie_diaria or []:
        try:
            data = dt.date.fromisoformat((item.get("dia") or "").strip())
        except ValueError:
            continue
        totais[data.weekday()] += int(item.get("visitas") or 0)
    return [{"dia": _DIAS_SEMANA[i], "visitas": totais[i]} for i in range(7)]


def calcular_crescimento(atual: int, anterior: int) -> float | None:
    """Variação percentual vs período anterior; None quando não há base."""
    if not anterior:
        return None
    return round(100.0 * (atual - anterior) / anterior, 1)


# ─── API pública ──────────────────────────────────────────────────────────────

def estatisticas_vitrine(
    dias: int = 30,
    limite: int = 200,
    usar_cache: bool = True,
    ids_conhecidos: list[str] | None = None,
) -> dict[str, Any]:
    """Resumo de métricas da vitrine para exibição no app.

    ``ids_conhecidos`` (ids da lista atual de produtos) permite marcar cliques
    em produtos que já saíram da planilha com ``na_lista: False``.

    Levanta ErroAnalytics quando o token está ausente/inválido ou sem rede.
    """
    dias = max(1, int(dias))
    ids_norm = (
        frozenset(normalizar_id_produto(i) for i in ids_conhecidos) - {""}
        if ids_conhecidos is not None
        else None
    )
    chave_cache = (dias, limite, ids_norm)
    import time

    if usar_cache:
        entrada = _CACHE.get(chave_cache)
        if entrada and time.time() - entrada[0] < _CACHE_TTL_SEGUNDOS:
            return {**entrada[1], "cache": True}

    inicio, fim = _periodo(dias)
    # A API espera horários arredondados à hora; janela cobre o fuso local (-3).
    inicio = f"{inicio}T00:00:00Z"
    fim_dt = dt.datetime.now() + dt.timedelta(hours=2)
    fim = fim_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    janela = {"start": inicio, "end": fim}
    dados_total = _get("stats/total", janela)
    dados_hits = _get(
        "stats/hits",
        {**janela, "limit": limite, "group": "day"},
    )
    dados_refs = _get("stats/toprefs", {**janela, "limit": 10})

    resumo = resumir_hits(dados_hits.get("hits") or [], ids_conhecidos=ids_conhecidos)
    resumo["visitas_total_periodo"] = int(dados_total.get("total") or 0)
    resumo["eventos_total_periodo"] = int(dados_total.get("total_events") or 0)
    # A API devolve o referrer em "name" (versões antigas usavam "path").
    # "url" preserva o domínio cru; "nome" é o amigável p/ exibição.
    resumo["referrers"] = [
        {
            "url": _nome_ref(ref),
            "nome": nome_amigavel_referrer(_nome_ref(ref)),
            "visitas": int(ref.get("count") or 0),
        }
        for ref in (dados_refs.get("stats") or [])
        if _nome_ref(ref)
    ]
    resumo["acesso_direto"] = sum(
        int(ref.get("count") or 0)
        for ref in (dados_refs.get("stats") or [])
        if not _nome_ref(ref)
    )

    # Tráfego detalhado: pico de horário (UTC → Brasília) e visitas por hora.
    resumo["horas_acesso"] = horas_acesso(dados_hits.get("hits") or [])
    resumo["pico_acesso"] = pico_de_acesso(resumo["horas_acesso"])

    # Crescimento de visitantes vs período anterior (mesma duração, antes da
    # janela atual). Dado secundário: falha não derruba o painel.
    try:
        janela_anterior = {
            "start": _periodo(2 * dias)[0] + "T00:00:00Z",
            "end": inicio,
        }
        dados_hits_anteriores = _get(
            "stats/hits",
            {**janela_anterior, "limit": limite, "group": "day"},
        )
        visitantes_anteriores = resumir_hits(
            dados_hits_anteriores.get("hits") or []
        )["visitantes"]
        resumo["crescimento_visitantes"] = calcular_crescimento(
            resumo["visitantes"], visitantes_anteriores
        )
    except Exception:  # noqa: BLE001 — comparativo é opcional
        logger.warning("Falha ao buscar período anterior", exc_info=True)
        resumo["crescimento_visitantes"] = None


    # Série diária de visitas (gráfico) + destaques
    resumo["serie_diaria"] = serie_diaria(dados_total)
    resumo["dias_semana"] = visitas_por_dia_semana(resumo["serie_diaria"])
    dias_com_dado = resumo["serie_diaria"]
    if dias_com_dado:
        melhor = max(dias_com_dado, key=lambda d: d["visitas"])
        resumo["melhor_dia"] = melhor if melhor["visitas"] > 0 else None
        resumo["media_diaria"] = round(
            sum(d["visitas"] for d in dias_com_dado) / len(dias_com_dado), 1
        )
    else:
        resumo["melhor_dia"] = None
        resumo["media_diaria"] = 0.0

    # Perfil do público: falhas aqui não derrubam o painel inteiro.
    # Em paralelo (só 2 por vez — o GoatCounter limita requisições por segundo).
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = {chave: pool.submit(_quebra, cam, janela) for chave, cam in _QUEBRAS.items()}
        for chave, fut in futuros.items():
            resumo[chave] = fut.result()

    visitas = resumo["visitantes"]
    resumo["ctr_pct"] = (
        round(100.0 * resumo["cliques_cta"] / visitas, 1) if visitas else 0.0
    )
    resumo["periodo"] = {"inicio": inicio[:10], "fim": fim[:10], "dias": dias}
    resumo["site"] = codigo_site()
    resumo["cache"] = False

    _CACHE[chave_cache] = (time.time(), resumo)
    return resumo


def limpar_cache() -> None:
    """Esquece o cache (útil após mudar período/token)."""
    _CACHE.clear()
