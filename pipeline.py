"""
pipeline.py — Orquestrador: roteiro → voz → visual → trilha → render → pacote.

Um comando para um produto, um comando para a semana inteira.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from config import Produto, ler_produtos, salvar_produtos
from render import renderizar
from roteirista import gerar_roteiro
from trilha import gerar_trilha
from visual import gerar_badge, gerar_cta, gerar_legendas
from voz import gerar_voz

logger = logging.getLogger(__name__)


def processar_produto(p: Produto, forcar: bool = False) -> dict:
    """Roda o pipeline completo para UM produto.

    Retorna dict com: etapas executadas, caminhos e o pacote de post.
    """
    log: list[str] = []
    pasta = p.pasta
    pasta.mkdir(parents=True, exist_ok=True)

    # ── 1. Roteiro ────────────────────────────────────────────────────────────
    arq_roteiro = pasta / "roteiro.json"
    if arq_roteiro.exists() and not forcar:
        roteiro = json.loads(arq_roteiro.read_text(encoding="utf-8"))
        log.append("roteiro: reutilizado")
    else:
        roteiro = gerar_roteiro(p)
        if not roteiro:
            raise RuntimeError(f"Gemini não gerou roteiro para {p.id}")
        arq_roteiro.write_text(
            json.dumps(roteiro, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        log.append("roteiro: gerado")
    p.roteiro = roteiro

    # ── 2. Voz ───────────────────────────────────────────────────────────────
    if not (pasta / "locucao.mp3").exists() or forcar:
        info = gerar_voz(roteiro["locucao"], pasta)
        log.append(f"voz: {info['duracao']:.1f}s, {len(info['palavras'])} palavras")
    else:
        import subprocess
        dur = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(pasta / "locucao.mp3")],
            capture_output=True, text=True).stdout.strip())
        info = {"duracao": dur}
        log.append("voz: reutilizada")

    # ── 3. Visual: badge + CTA + legendas karaoke ────────────────────────────
    gerar_badge(pasta, p.id)
    gerar_cta(pasta)
    palavras = json.loads((pasta / "palavras.json").read_text(encoding="utf-8"))
    gerar_legendas(pasta, palavras)
    log.append("visual: badge + CTA + legendas OK")

    # ── 4. Trilha sintetizada na duração certa ───────────────────────────────
    dur_total = info["duracao"] + 1.0
    if not (pasta / "trilha.wav").exists() or forcar:
        gerar_trilha(dur_total + 2.0, pasta / "trilha.wav")
        log.append("trilha: gerada")
    else:
        log.append("trilha: reutilizada")

    # ── 5. Render (requer clipes em Midias/#NN_Slug/) ────────────────────────
    clipes = p.clipes()
    if not clipes:
        log.append(f"render: PENDENTE — jogue clipes em Midias/{p.slug}/")
        return {"ok": False, "log": log, "motivo": "sem_clipes"}

    video = renderizar(p)
    log.append(f"render: {video}")

    # ── 6. Pacote de post (caption + comentário fixo + agenda) ──────────────
    pacote = montar_pacote(p, str(video))
    log.append("pacote: pronto")

    # ── 7. Status na planilha ────────────────────────────────────────────────
    p.status = "Editado"
    p.post_agendado = "Nao"
    return {"ok": True, "log": log, "video": str(video), "pacote": pacote}


def montar_pacote(p: Produto, video_path: str) -> Path:
    """Gera pacote_post.txt com tudo que vai pro Meta Suite / TikTok Studio."""
    r = p.roteiro
    num = p.id.replace("#", "")
    linhas = [
        f"═══ ACHADINHO {p.id} — {p.nome} ═══",
        "",
        "▶ VÍDEO: " + video_path,
        "",
        "── LEGENDA (copiar/colar) ──",
        r.get("legenda", ""),
        "",
        "── HASHTAGS ──",
        " ".join("#" + h.lstrip('#') for h in r.get("hashtags", [])),
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
    ]
    arq = p.pasta / "pacote_post.txt"
    arq.write_text("\n".join(linhas), encoding="utf-8")
    return arq


def processar_lote(ids: list[str] | None = None, forcar: bool = False) -> list[dict]:
    """Processa a lista de produtos da planilha (todos, ou só os IDs passados)."""
    prods = ler_produtos()
    resultados = []
    for p in prods:
        if ids and p.id not in ids:
            continue
        try:
            res = processar_produto(p, forcar=forcar)
            resultados.append({"id": p.id, **res})
        except Exception as exc:
            logger.error("Falha em %s: %s", p.id, exc)
            resultados.append({"id": p.id, "ok": False, "erro": str(exc)})
    salvar_produtos(prods)
    return resultados


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    forcar = "--forcar" in sys.argv
    res = processar_lote(ids=args or None, forcar=forcar)
    for r in res:
        marca = "✓" if r.get("ok") else ("⊘" if r.get("motivo") == "sem_clipes" else "✗")
        print(f"{marca} {r['id']}: " + "; ".join(r.get("log", [])) + (f" ERRO: {r.get('erro', '')}" if r.get("erro") else ""))
