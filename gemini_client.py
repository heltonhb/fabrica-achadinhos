"""
gemini_client.py — Cliente Gemini compartilhado.

Centraliza a chamada à API em um único lugar para que prompts.py,
legenda.py e roteirista.py não dupliquem código.
"""

from __future__ import annotations

import logging
import time

from google import genai
from google.genai import types

from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

# Modelos em ordem de preferência (mais rápido/barato primeiro).
MODELOS_PADRAO: list[str] = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
]


def _chamar_gemini(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.8,
    response_mime_type: str | None = None,
    modelos: list[str] | None = None,
) -> str:
    """Chama o Gemini e retorna o texto gerado.

    Args:
        system_prompt: Instrução de sistema (persona / regras).
        user_prompt: Mensagem do usuário (o pedido concreto).
        temperature: Criatividade da resposta (0.0 – 1.0).
        response_mime_type: Se ``"application/json"``, força saída JSON.
        modelos: Lista de modelos a tentar, em ordem. Usa MODELOS_PADRAO se omitido.

    Returns:
        Texto gerado pelo modelo (já com .strip()).

    Raises:
        RuntimeError: Se nenhum modelo responder após todas as tentativas.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ausente no .env")

    client = genai.Client(api_key=GEMINI_API_KEY)
    lista = modelos or MODELOS_PADRAO

    for modelo in lista:
        for tentativa in range(3):
            try:
                config_kwargs: dict = {
                    "system_instruction": system_prompt,
                    "temperature": temperature,
                }
                if response_mime_type:
                    config_kwargs["response_mime_type"] = response_mime_type

                resp = client.models.generate_content(
                    model=modelo,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
                if resp.text:
                    return resp.text.strip()
            except Exception as exc:
                msg = str(exc)
                if any(code in msg for code in ("429", "500", "503")):
                    wait = 2 ** tentativa * 2
                    logger.debug("Gemini %s tentativa %d — aguardando %ds", modelo, tentativa + 1, wait)
                    time.sleep(wait)
                    continue
                logger.warning("Gemini %s falhou: %s", modelo, msg[:120])
                break  # erro não recuperável → próximo modelo

    raise RuntimeError("Gemini não respondeu em nenhum modelo disponível")
