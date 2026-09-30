# 📦 Módulos Legados — Renderização Local (FFmpeg)

Estes arquivos compunham o pipeline inicial de composição local de vídeos da **Fábrica de Achadinhos** (v1.0):

- `render.py`: Orquestrador FFmpeg para mesclar clipes, áudio BGM, locução e legendas.
- `voz.py`: Gerador de locução neural TTS via `edge-tts`.
- `visual.py`: Gerador de badges, setas de CTA e legendas ASS/Pillow.
- `trilha.py`: Processamento de áudio (ducking, normalização EBU R128 a -14 LUFS) via `numpy`/`scipy`.
- `teste_voz.py`: Script de teste rápido de voz TTS.
- `fonts/`: Fonte Montserrat-Bold utilizada na sobreposição de textos.

### Motivo do Arquivamento
O projeto evoluiu para o modelo de **geração de prompts autocontidos** (`prompts.py`) para renderizadores modernos (Google Vids, NotebookLM, Canva, CapCut), eliminando a necessidade de compilação pesada de `FFmpeg`, `numpy`, `scipy` e `Pillow` em ambientes de nuvem (Streamlit Community Cloud e Vercel).

Estes arquivos foram preservados aqui para fins de histórico e caso seja desejada uma futura reativação de renderização programática headless.
