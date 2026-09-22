"""
gemini_client.py — Cliente Gemini compartilhado.

Centraliza a chamada à API em um único lugar para que prompts.py,
legenda.py e roteirista.py não dupliquem código.

Estratégia de resiliência (baseada em falhas reais da free tier):
- 429 (cota esgotada, limite ~20 req/modelo): NÃO insiste no mesmo modelo —
  falha rápido para o próximo. Só se TODOS os modelos derem 429 é que se
  espera o "retry in Ns" sugerido pela API uma única vez e repete uma rodada.
- 503 (alta demanda): retry com backoff exponencial (transiente).
- Prazo total por chamada evita travar a UI por minutos.
"""

from __future__ import annotations

import json
import logging
import re
import time

from google import genai
from google.genai import types

from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

# Modelos em ordem de preferência (mais rápido/barato primeiro).
# Os últimos três são fallbacks verificados (lite/preview costumam
# ter fila menor quando os flash principais estão em 503/429).
MODELOS_PADRAO: list[str] = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3-flash-preview",
]

# Tentativas por modelo para erros transientes (503 / resposta vazia).
TENTATIVAS_POR_MODELO = 4
_ESPERA_BASE_S = 1.5
_ESPERA_MAX_S = 20.0

# Prazo máximo de uma chamada inteira (todos os modelos somados).
PRAZO_TOTAL_S = 150.0

# 429: uma tentativa por modelo por rodada; no máximo 2 rodadas por chamada,
# com uma única espera coletiva baseada no "retry in Ns" da própria API.
_RODADAS = 2
_ESPERA_429_MAX_S = 40.0
_RE_429_RETRY = re.compile(r"retry in ([\d.]+)\s*s", re.IGNORECASE)

# Erros de instabilidade temporária — valem backoff no MESMO modelo.
_CODIGOS_RECUPERAVEIS = ("500", "502", "503", "504", "UNAVAILABLE", "DEADLINE_EXCEEDED", "timeout", "Deadline")


def _espera_recoveravel(tentativa: int, msg: str) -> float | None:
    """Segundos para esperar, ou None se o erro não for recuperável."""
    if not any(code in msg for code in _CODIGOS_RECUPERAVEIS):
        return None
    # 1.5, 3, 6, 12… (503 costuma ceder com mais tentativas)
    return min(_ESPERA_MAX_S, _ESPERA_BASE_S * (2 ** tentativa))


def _reparar_json(texto: str) -> str | None:
    """Tenta normalizar JSON malformado (fences markdown, vírgula final).

    Retorna o JSON re-serializado ou None se irrecuperável.
    """
    t = texto.strip()
    base = [t]
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL | re.IGNORECASE)
    if m:
        base.append(m.group(1).strip())
    ini, fim = t.find("{"), t.rfind("}")
    if ini != -1 and fim > ini:
        base.append(t[ini:fim + 1])

    candidatos: list[str] = []
    for b in base:
        candidatos.append(b)
        candidatos.append(re.sub(r",\s*([\]}])", r"\1", b))  # vírgula final

    for c in candidatos:
        try:
            return json.dumps(json.loads(c), ensure_ascii=False)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _validar_saida(texto: str, response_mime_type: str | None) -> str | None:
    """Valida a resposta antes de devolver. Para JSON, repara o que der.

    Retorna None se a resposta estiver vazia ou for JSON irrecuperável
    (nesse caso o chamador tenta de novo).
    """
    if not texto:
        return None
    if response_mime_type != "application/json":
        return texto
    try:
        json.loads(texto)
        return texto
    except json.JSONDecodeError:
        return _reparar_json(texto)


def _dica_retry_429(msg: str) -> float | None:
    """Extrai o 'retry in Ns' que a API sugere num erro 429, se houver."""
    m = _RE_429_RETRY.search(msg)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:  # noqa: PERF203
        return None


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
        RuntimeError: Se nenhum modelo responder após todas as tentativas
            (a mensagem inclui o último erro da API).
    """
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY ausente — preencha no .env (local) "
            "ou no secret GEMINI_API_KEY (Streamlit Cloud)"
        )

    client = genai.Client(api_key=GEMINI_API_KEY)
    lista = modelos or MODELOS_PADRAO
    ultimo_erro = "sem tentativa"
    inicio = time.monotonic()
    dica_429: float | None = None  # menor "retry in Ns" visto na rodada 0

    def _prazo_ok(extra: float = 0.0) -> bool:
        return time.monotonic() - inicio + extra <= PRAZO_TOTAL_S

    for rodada in range(_RODADAS):
        só_429 = True  # todos os modelos falaram EXCLUSIVAMENTE com 429?

        for modelo in lista:
            if not _prazo_ok():
                só_429 = False
                break

            for tentativa in range(TENTATIVAS_POR_MODELO):
                if not _prazo_ok():
                    só_429 = False
                    break
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
                    texto = (resp.text or "").strip()
                    validado = _validar_saida(texto, response_mime_type)
                    if validado:
                        return validado
                    # 200 sem texto (safety / corte) ou JSON inválido → tenta de novo
                    só_429 = False
                    if texto and response_mime_type == "application/json":
                        ultimo_erro = f"{modelo}: JSON inválido na resposta"
                        logger.warning(
                            "Gemini %s devolveu JSON irrecuperável (tentativa %d)", modelo, tentativa + 1
                        )
                    else:
                        ultimo_erro = f"{modelo}: resposta vazia"
                        logger.warning("Gemini %s devolveu texto vazio (tentativa %d)", modelo, tentativa + 1)
                except Exception as exc:  # noqa: BLE001
                    msg = str(exc)
                    ultimo_erro = f"{modelo}: {msg}"

                    if "429" in msg:
                        # Cota do modelo: não insiste aqui — passa adiante.
                        dica = _dica_retry_429(msg)
                        if dica is not None:
                            dica_429 = dica if dica_429 is None else min(dica_429, dica)
                        logger.warning(
                            "Gemini %s na cota (429) — falhando rápido para o próximo modelo", modelo
                        )
                        break  # próximo modelo

                    só_429 = False
                    espera = _espera_recoveravel(tentativa, msg)
                    if espera is None:
                        logger.warning("Gemini %s falhou (não recuperável): %s", modelo, msg[:200])
                        break  # próximo modelo
                    logger.debug(
                        "Gemini %s tentativa %d/%d — aguardando %.1fs (%s)",
                        modelo, tentativa + 1, TENTATIVAS_POR_MODELO, espera, msg[:80],
                    )
                    time.sleep(espera)
                    continue
                # texto vazio → espera e repete no mesmo modelo
                time.sleep(min(_ESPERA_MAX_S, _ESPERA_BASE_S * (tentativa + 1)))

            if not _prazo_ok():
                só_429 = False
                break

        # Todos os modelos só erraram por 429 → espera a janela de cota
        # sugerida pela API (uma única vez) e repete uma rodada.
        if (
            rodada == 0
            and só_429
            and dica_429 is not None
            and _prazo_ok(min(_ESPERA_429_MAX_S, dica_429))
        ):
            espera = min(_ESPERA_429_MAX_S, dica_429)
            logger.info(
                "Gemini: todos os modelos na cota (429) — aguardando %.0fs e tentando de novo", espera
            )
            time.sleep(espera)
            continue
        break

    estourou = not _prazo_ok()
    prazo_txt = f" (prazo total de {PRAZO_TOTAL_S:.0f}s estourado)" if estourou else ""
    raise RuntimeError(
        f"Gemini não respondeu em nenhum modelo disponível{prazo_txt}. Último erro: {ultimo_erro}"
    )
