"""
voz.py — Locução TTS via edge-tts com timings por palavra.

A edge-tts (grátis, neural) devolve WordBoundary junto com o áudio:
isso dá as legendas estilo CapCut (palavra destacada) SEM transcrição.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import edge_tts

from config import VOZ_PADRAO, VOZ_RATE


async def _gerar_async(texto: str, mp3_path: Path, voz: str, rate: str) -> list[dict]:
    tts = edge_tts.Communicate(texto, voice=voz, rate=rate, boundary="WordBoundary")
    bounds: list[dict] = []
    with open(mp3_path, "wb") as f:
        async for chunk in tts.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                bounds.append({
                    "palavra": chunk["text"],
                    "inicio": chunk["offset"] / 1e7,
                    "fim": (chunk["offset"] + chunk["duration"]) / 1e7,
                })
    return bounds


def gerar_voz(texto: str, pasta: Path, voz: str = VOZ_PADRAO, rate: str = VOZ_RATE) -> dict:
    """Gera locucao.mp3 + palavras.json na pasta do produto.

    Retorna {"mp3": Path, "duracao": float, "palavras": [...]}.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    mp3 = pasta / "locucao.mp3"
    palavras = asyncio.run(_gerar_async(texto, mp3, voz, rate))

    import subprocess
    dur = float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(mp3)],
            capture_output=True, text=True,
        ).stdout.strip()
    )

    (pasta / "palavras.json").write_text(
        json.dumps(palavras, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return {"mp3": mp3, "duracao": dur, "palavras": palavras}


if __name__ == "__main__":
    # autoteste: python voz.py
    out = gerar_voz("Isso aqui salvou a limpeza da minha mesa.", Path("/tmp/teste_voz_dir"))
    print("duração:", out["duracao"], "| palavras:", len(out["palavras"]))
