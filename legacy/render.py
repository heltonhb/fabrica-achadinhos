"""
render.py — Montagem final do vídeo (ffmpeg) para um produto.

Entradas (pasta Produtos/#NN_Slug/):
  locucao.mp3   palavras.json   badge.png   cta.png   legendas.ass   trilha.wav
  + clipes brutos em Midias/#NN_Slug/*.mp4

Etapas:
  1. Clipes: normaliza 1080x1920, emenda com xfade 0.25s, corta na duração
     da locução (+1s de cauda para o CTA respirar).
  2. Overlays: badge no topo (do início ao fim), CTA nos últimos 6s.
  3. Legendas: burn-in do .ass karaoke (palavra ativa amarela).
  4. Áudio: locução em primeiro plano + trilha com ducking (sidechain).
  5. Loudness: mix final normalizado a -14 LUFS (padrão Reels).
Saída: renders/#NN_Slug.mp4
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from config import BGM_VOLUME, DURACAO_ALVO, FPS, H, W, XFADE, Produto

logger = logging.getLogger(__name__)


def _ffprobe_dur(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip())


def _esc(p: Path | str) -> str:
    """Escapa caminho para filter_complex (legendas/imagens)."""
    s = str(p).replace("\\", "/")
    return (s.replace(":", r"\:").replace("'", r"\'")
             .replace("[", r"\[").replace("]", r"\]").replace(",", r"\,"))


def renderizar(produto: Produto, duracao_min: float = 8.0) -> Path:
    """Renderiza o vídeo final. Retorna o caminho do .mp4."""
    pasta = produto.pasta
    clipes = produto.clipes()
    if not clipes:
        raise RuntimeError(f"Nenhum clipe em {produto.pasta_clipes}")

    locucao = pasta / "locucao.mp3"
    trilha = pasta / "trilha.wav"
    badge = pasta / "badge.png"
    cta = pasta / "cta.png"
    ass = pasta / "legendas.ass"
    for f in (locucao, trilha, badge, cta, ass):
        if not f.exists():
            raise RuntimeError(f"Arquivo ausente: {f}")

    dur_voz = _ffprobe_dur(locucao)
    dur_total = min(max(dur_voz + 1.0, duracao_min), DURACAO_ALVO + 5)

    # ── 1. Vídeo base: normaliza + xfade encadeado ────────────────────────────
    inputs = []
    for c in clipes:
        inputs += ["-i", str(c)]
    inputs += ["-i", str(locucao), "-i", str(trilha), "-i", str(badge), "-i", str(cta)]

    n = len(clipes)
    partes_v: list[str] = []
    acc = 0.0
    label_v = ""
    for i in range(n):
        partes_v.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS},settb=1/{FPS},format=yuv420p[v{i}]"
        )
        dur_i = _ffprobe_dur(clipes[i])
        if i == 0:
            acc = dur_i
            label_v = "[v0]"
            continue
        offset = max(0.0, acc - XFADE)
        out = f"[vx{i}]"
        partes_v.append(
            f"{label_v}[v{i}]xfade=transition=fade:duration={XFADE}:offset={offset:.3f}{out}"
        )
        acc = acc + dur_i - XFADE
        label_v = out

    # corta na duração final e hold do último frame no CTA (2s)
    partes_v.append(f"{label_v}tpad=stop_mode=clone:stop_duration=2.0,"
                    f"trim=duration={dur_total:.3f},setpts=PTS-STARTPTS,"
                    f"fade=t=in:st=0:d=0.2,fade=t=out:st={dur_total - 0.4:.3f}:d=0.4[vbase]")

    # ── 2. Overlays: badge (sempre) + CTA (últimos 6s) ──────────────────────
    nvoz, ntrilha, nbadge, ncta = n, n + 1, n + 2, n + 3
    ini_cta = max(0.0, dur_total - 6.0)
    partes_v.append(
        f"[{nbadge}:v]format=rgba[vbadge];"
        f"[{ncta}:v]format=rgba[vcta];"
        f"[vbase][vbadge]overlay=0:150:format=auto[vb];"
        f"[vb][vcta]overlay=(W-w)/2:1450:enable='gte(t,{ini_cta:.2f})'[vvid]"
    )

    # ── 3. Legendas .ass ─────────────────────────────────────────────────────
    partes_v.append(
        f"[vvid]ass='{_esc(ass)}'[vfinal]"
    )

    # ── 4. Áudio: voz primeiro plano + trilha ducked ─────────────────────────
    partes_a = [
        f"[{nvoz}:a]aresample=48000,pan=stereo|c0=c0|c1=c1[vz]",
        f"[{ntrilha}:a]aresample=48000,pan=stereo|c0=c0|c1=c1,volume={BGM_VOLUME}[bd]",
        f"[bd][vz]sidechaincompress=threshold=0.015:ratio=8:attack=25:release=400[ducker]",
        f"[vz][ducker]amix=inputs=2:duration=first:normalize=0,"
        f"apad=whole_dur={dur_total:.3f},"
        f"alimiter=limit=0.95,aresample=48000[afinal]",
    ]
    # NOTA: alimiter AQUI é só no master final (2bus) — prática validada nos
    # projetos de trilha; nunca entre narração e bed (corrompe a voz).

    filtro = ";".join(partes_v + partes_a)

    out = Path("renders") / f"{produto.slug}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = (
        ["ffmpeg", "-y", "-hide_banner"] + inputs
        + ["-filter_complex", filtro,
           "-map", "[vfinal]", "-map", "[afinal]",
           "-c:v", "libx264", "-preset", "fast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-r", str(FPS),
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-movflags", "+faststart", str(out)]
    )
    logger.info("Renderizando %s (%d clipes, %.1fs)", produto.id, n, dur_total)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou:\n{r.stderr[-2500:]}")

    # ── 5. Normaliza loudness para -14 LUFS (segunda passada) ───────────────
    med = subprocess.run(
        ["ffmpeg", "-i", str(out), "-af", "ebur128=framelogged=0", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    import re as _re
    m = _re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", med.stderr)
    if m:
        lufs_atual = float(m.group(1))
        delta = -14.0 - lufs_atual
        if abs(delta) > 0.5:
            tmp = out.with_suffix(".tmp.mp4")
            r2 = subprocess.run(
                ["ffmpeg", "-y", "-i", str(out), "-af", f"volume={delta:+.2f}dB",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(tmp)],
                capture_output=True, text=True,
            )
            if r2.returncode == 0:
                tmp.replace(out)
    return out


if __name__ == "__main__":
    # autoteste com clipes sintéticos: python render.py
    from config import PRODUTOS_DIR
    import numpy as np
    pasta = PRODUTOS_DIR / "_teste_render"
    pasta_midia = Path("Midias") / "_teste_render"
    pasta_midia.mkdir(parents=True, exist_ok=True)
    pasta_midia = Path(pasta_midia).resolve()

    # gera 3 clipes sintéticos coloridos de 4s com tom de áudio
    for i, cor in enumerate(["0x2244AA", "0xAA4422", "0x22AA55"]):
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner",
            "-f", "lavfi", "-i", f"color=c={cor}:s=1080x1920:d=4:r=30",
            "-f", "lavfi", "-i", f"sine=frequency={440 + i * 80}:duration=4",
            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
            str(pasta_midia / f"clipe{i + 1}.mp4"),
        ], capture_output=True)

    from config import Produto as P
    p = P(id="_teste_render", nome="Render Teste")
    p.pasta_clipes  # noqa
    import config
    config.MIDIAS_DIR = pasta_midia.parent
    print("clipes de teste em:", pasta_midia)
