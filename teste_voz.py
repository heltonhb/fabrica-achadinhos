"""Teste rápido do edge-tts: locução + word boundaries (timings por palavra)."""
import asyncio
import sys

import edge_tts

TEXTO = (
    "Isso aqui salvou a limpeza da minha mesa e do meu carro. "
    "Mini aspirador portátil USB, potência de sucção absurda. "
    "Chega de farelo de biscoito no teclado. "
    "Comenta QUERO que eu te mando o link."
)


async def main() -> None:
    tts = edge_tts.Communicate(TEXTO, voice="pt-BR-AntonioNeural", rate="+8%", boundary="WordBoundary")
    mp3 = "/home/helton/Loja_online/Produtos/_teste_voz.mp3"
    bounds = []
    with open(mp3, "wb") as f:
        async for chunk in tts.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                bounds.append(
                    {
                        "palavra": chunk["text"],
                        "inicio": chunk["offset"] / 1e7,
                        "dur": chunk["duration"] / 1e7,
                        "fim": (chunk["offset"] + chunk["duration"]) / 1e7,
                    }
                )
    print(f"MP3: {mp3}")
    print(f"Palavras com timing: {len(bounds)}")
    for b in bounds[:6]:
        print(f"  {b['inicio']:.2f}-{b['fim']:.2f}s  {b['palavra']}")
    print("  ...")
    for b in bounds[-3:]:
        print(f"  {b['inicio']:.2f}-{b['fim']:.2f}s  {b['palavra']}")


if __name__ == "__main__":
    asyncio.run(main())
