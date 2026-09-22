"""
pipeline.py — Orquestrador: gancho → roteiro → pacote de post.

O vídeo é feito fora do app (Google Vids) a partir dos prompts da seção
Gerar Prompt. As etapas locais de voz/visual/trilha/render foram removidas —
o pipeline não requer mais ffmpeg.

Uso:
    python pipeline.py                   # processa todos os produtos
    python pipeline.py #01 #03           # só esses IDs
    python pipeline.py #01 --forcar      # regenera tudo mesmo se já existir
    python pipeline.py #01 --estilo educativo   # escolhe persona do vídeo
    python pipeline.py #01 --sem-ganchos        # pula geração de ganchos (usa gancho do CSV)

Estilos disponíveis: chocante (padrão), educativo, lifestyle, comparativo
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace as dc_replace
from pathlib import Path

from prompts import ESTILOS
from roteirista import gerar_ganchos, gerar_roteiro
from sheets import Produto, ler_produtos, salvar_produtos

logger = logging.getLogger(__name__)

# Ordem de preferência de ângulos para seleção automática de gancho no pipeline.
# "surpresa" tende a ter melhor retenção em achadinhos; ajuste conforme seu nicho.
_ANGULO_PREFERIDO = ["surpresa", "dor", "economia"]


def _escolher_gancho(ganchos: list[dict]) -> str:
    """Seleciona automaticamente o melhor gancho da lista gerada pelo Gemini.

    Prioriza pelo ângulo definido em _ANGULO_PREFERIDO.
    Se nenhum ângulo conhecido for encontrado, usa o primeiro da lista.
    """
    for angulo in _ANGULO_PREFERIDO:
        for g in ganchos:
            if g.get("angulo") == angulo:
                return g["texto"]
    return ganchos[0]["texto"] if ganchos else ""


def processar_produto(
    p: Produto,
    forcar: bool = False,
    estilo: str = "chocante",
    usar_ganchos: bool = True,
) -> dict:
    """Roda o pipeline completo para UM produto.

    Args:
        p: Produto a processar.
        forcar: Se True, regenera todas as etapas mesmo que já existam.
        estilo: Persona do vídeo (chave de ``prompts.ESTILOS``).
        usar_ganchos: Se True, gera 3 ganchos via Gemini e escolhe o melhor
                      antes de gerar o roteiro. Se False, usa ``p.gancho`` do CSV.

    Returns:
        Dict com: ok, log, pacote.
    """
    if estilo not in ESTILOS:
        logger.warning("Estilo '%s' desconhecido — usando 'chocante'", estilo)
        estilo = "chocante"

    log: list[str] = []
    pasta = p.pasta
    pasta.mkdir(parents=True, exist_ok=True)

    # ── 1. Gancho ─────────────────────────────────────────────────────────────
    arq_gancho = pasta / "gancho.json"

    if arq_gancho.exists() and not forcar:
        gancho_data = json.loads(arq_gancho.read_text(encoding="utf-8"))
        gancho_texto = gancho_data.get("texto", p.gancho or "")
        log.append(f"gancho: reutilizado ({gancho_data.get('angulo', 'manual')})")
    elif usar_ganchos:
        logger.info("Gerando ganchos para %s...", p.id)
        ganchos = gerar_ganchos(p)
        if ganchos:
            gancho_texto = _escolher_gancho(ganchos)
            angulo = next(
                (g["angulo"] for g in ganchos if g["texto"] == gancho_texto), "?"
            )
            gancho_data = {
                "texto": gancho_texto,
                "angulo": angulo,
                "todas_opcoes": ganchos,
                "estilo": estilo,
            }
            arq_gancho.write_text(
                json.dumps(gancho_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log.append(f"gancho: gerado — ângulo '{angulo}': {gancho_texto[:50]}")
        else:
            # fallback: gancho do CSV ou genérico
            gancho_texto = p.gancho or f"Esse produto vai mudar sua rotina"
            log.append("gancho: fallback (Gemini falhou)")
    else:
        gancho_texto = p.gancho or f"Esse produto vai mudar sua rotina"
        log.append(f"gancho: do CSV — {gancho_texto[:50]}")

    # injeta o gancho no produto (sem alterar o objeto original da planilha)
    p_roteiro = dc_replace(p, gancho=gancho_texto)

    # ── 2. Roteiro ────────────────────────────────────────────────────────────
    arq_roteiro = pasta / "roteiro.json"

    if arq_roteiro.exists() and not forcar:
        roteiro = json.loads(arq_roteiro.read_text(encoding="utf-8"))
        estilo_salvo = roteiro.get("_meta", {}).get("estilo", "?")
        log.append(f"roteiro: reutilizado (estilo: {estilo_salvo})")
        if estilo_salvo != estilo:
            logger.warning(
                "Roteiro de %s salvo com estilo '%s'; pedido '%s' — use --forcar para regenerar",
                p.id, estilo_salvo, estilo,
            )
    else:
        logger.info("Gerando roteiro para %s (estilo: %s)...", p.id, estilo)
        roteiro = gerar_roteiro(p_roteiro, estilo=estilo)
        if not roteiro:
            raise RuntimeError(f"Gemini não gerou roteiro para {p.id}")
        # estilo já vem em _meta via gerar_roteiro; garante merge seguro
        roteiro["_meta"] = {**roteiro.get("_meta", {}), "estilo": estilo}
        arq_roteiro.write_text(
            json.dumps(roteiro, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        log.append(f"roteiro: gerado (estilo: {estilo}, clipes: {roteiro['_meta'].get('n_clipes', 0)})")

    p_roteiro.roteiro = roteiro

    # ── 3. Pacote de post ────────────────────────────────────────────────────
    # voz/visual/trilha/render removidos — o vídeo é feito no Google Vids.
    pacote = montar_pacote(p_roteiro, estilo=estilo, gancho_texto=gancho_texto)
    log.append("pacote: pronto")

    # ── 4. Atualiza status na planilha ───────────────────────────────────────
    # só avança: não regride status já definido manualmente pelo usuário
    if p.status == "Ideia":
        p.status = "Roteiro Pronto"
    p.post_agendado = "Nao"

    return {"ok": True, "log": log, "pacote": str(pacote)}


def montar_pacote(
    p: Produto,
    estilo: str = "chocante",
    gancho_texto: str = "",
) -> Path:
    """Gera pacote_post.txt com tudo que vai pro Meta Suite / TikTok Studio."""
    r = p.roteiro
    num = p.id.replace("#", "")
    estilo_label = ESTILOS.get(estilo, {}).get("label", estilo)

    linhas = [
        f"═══ ACHADINHO {p.id} — {p.nome} ═══",
        f"Estilo: {estilo_label}",
        f"Gancho usado: {gancho_texto or p.gancho}",
        "",
        "▶ VÍDEO: gerar no Google Vids (prompt na seção 🤖 Gerar Prompt)",
        "",
        "── LEGENDA (copiar/colar) ──",
        r.get("legenda", ""),
        "",
        "── HASHTAGS ──",
        " ".join("#" + h.lstrip("#") for h in r.get("hashtags", [])),
        "",
        "── COMENTÁRIO PARA FIXAR (TikTok/Shorts) ──",
        r.get("comentario_fixo", f"Link do produto {num} disponível no link da minha bio!"),
        "",
        "── REGRAS MANYCHAT (Instagram) ──",
        'Se comentar "QUERO" ou "EU QUERO" → DM automática:',
        f"Link do produto: {p.link_afiliado}",
        "",
        "── SUGESTÃO DE AGENDA ──",
        "Instagram Reels: 12:00, 18:00 ou 21:00 (horário de pico)",
        "TikTok: mesmo vídeo, 1h depois do Reels",
        "YouTube Shorts: reutilizar do TikTok",
        "",
        "── LINKS ──",
        f"Afiliado Shopee: {p.link_afiliado}",
        f"Vitrine/Bio: {p.link_vitrine}",
        "",
        "── RASTREABILIDADE ──",
        f"Gerado com estilo: {estilo_label}",
        f"Clipes usados: {r.get('_meta', {}).get('n_clipes', '?')}",
        f"Gancho ângulo: {_angulo_do_gancho(p.pasta)}",
    ]
    arq = p.pasta / "pacote_post.txt"
    arq.write_text("\n".join(linhas), encoding="utf-8")
    return arq


def _angulo_do_gancho(pasta: Path) -> str:
    """Lê o ângulo do gancho salvo, se disponível."""
    arq = pasta / "gancho.json"
    if arq.exists():
        try:
            return json.loads(arq.read_text(encoding="utf-8")).get("angulo", "?")
        except Exception:
            pass
    return "manual"


def processar_lote(
    ids: list[str] | None = None,
    forcar: bool = False,
    estilo: str = "chocante",
    usar_ganchos: bool = True,
) -> list[dict]:
    """Processa a lista de produtos da planilha (todos, ou só os IDs passados)."""
    prods = ler_produtos()
    resultados = []
    for p in prods:
        if ids and p.id not in ids:
            continue
        try:
            res = processar_produto(p, forcar=forcar, estilo=estilo, usar_ganchos=usar_ganchos)
            resultados.append({"id": p.id, **res})
        except Exception as exc:
            logger.error("Falha em %s: %s", p.id, exc)
            resultados.append({"id": p.id, "ok": False, "erro": str(exc)})
    salvar_produtos(prods)
    return resultados


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    args = sys.argv[1:]
    forcar = "--forcar" in args
    sem_ganchos = "--sem-ganchos" in args

    # extrai --estilo <valor>
    estilo = "chocante"
    if "--estilo" in args:
        idx = args.index("--estilo")
        if idx + 1 < len(args):
            estilo_arg = args[idx + 1]
            if estilo_arg in ESTILOS:
                estilo = estilo_arg
            else:
                print(f"Estilo '{estilo_arg}' desconhecido. Opções: {', '.join(ESTILOS)}")
                sys.exit(1)

    # IDs são argumentos que começam com # ou são dígitos
    ids = [a for a in args if a.startswith("#") or (a.isdigit())]
    # normaliza: "01" → "#01"
    ids = [f"#{a}" if not a.startswith("#") else a for a in ids]

    res = processar_lote(
        ids=ids or None,
        forcar=forcar,
        estilo=estilo,
        usar_ganchos=not sem_ganchos,
    )

    print()
    for r in res:
        marca = "✓" if r.get("ok") else "✗"
        detalhe = "; ".join(r.get("log", []))
        erro = f" ERRO: {r['erro']}" if r.get("erro") else ""
        print(f"  {marca} {r['id']}: {detalhe}{erro}")

    ok = sum(1 for r in res if r.get("ok"))
    falha = len(res) - ok
    print(f"\n  ✓ {ok} prontos  ✗ {falha} com erro")
