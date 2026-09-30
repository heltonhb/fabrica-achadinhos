"""
webhook_insta.py — Bot de automação do Instagram (comentários → DM com link afiliado).

Escuta eventos via Webhook da Meta Graph API e envia automaticamente o link de afiliado
por Direct Message (DM) para usuários que comentarem palavras-chave como "QUERO" ou "LINK".
Também curte o comentário e deixa uma resposta pública rápida.

Otimizações de resiliência:
- Processamento assíncrono via BackgroundTasks do FastAPI (Meta recebe 200 OK em <50ms).
- Cache em memória com TTL para produtos/links (evita chamadas HTTP repetidas ao Sheets).
- Timeouts explícitos em todas as requisições HTTP para a Meta Graph API.
- Resolução segura de segredos via config.obter_segredo.
"""

from __future__ import annotations

import logging
import os
import time

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
import requests

from config import obter_segredo
from sheets import ler_produtos

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BotInsta")

# Carrega variáveis do .env
load_dotenv()
PAGE_ID = obter_segredo("INSTAGRAM_PAGE_ID") or os.getenv("INSTAGRAM_PAGE_ID", "")
ACCESS_TOKEN = obter_segredo("INSTAGRAM_ACCESS_TOKEN") or os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
VERIFY_TOKEN = obter_segredo("META_VERIFY_TOKEN") or os.getenv("META_VERIFY_TOKEN", "meu_token_secreto_123")

TIMEOUT_REQUESTS: float = 10.0
CACHE_TTL_SEGUNDOS: float = 60.0

_cache_produtos: list = []
_cache_timestamp: float = 0.0

app = FastAPI(title="Bot Instagram - Fábrica de Achadinhos")


def limpar_cache() -> None:
    """Limpa o cache em memória de produtos (útil para testes e recarregamento forçado)."""
    global _cache_produtos, _cache_timestamp
    _cache_produtos = []
    _cache_timestamp = 0.0


def _obter_produtos_com_cache(forcar: bool = False) -> list:
    """Lê produtos com cache TTL em memória para não sobrecarregar a Sheets API."""
    global _cache_produtos, _cache_timestamp
    agora = time.time()
    if not forcar and _cache_produtos and (agora - _cache_timestamp < CACHE_TTL_SEGUNDOS):
        return _cache_produtos

    prods = ler_produtos()
    _cache_produtos = prods
    _cache_timestamp = agora
    return prods


# ==========================================
# FUNÇÕES DE INTEGRAÇÃO COM INSTAGRAM
# ==========================================

def buscar_link_por_media_id(media_id: str) -> str:
    """
    Retorna o link afiliado associado ao media_id do Instagram.

    Usa a porta única ``sheets.ler_produtos`` com cache TTL em memória
    para responder em milissegundos e não bater na Google Sheets API
    a cada comentário recebido.
    A coluna ``Media ID Instagram`` é preenchida após cada post.
    Se não encontrar correspondência, devolve um link genérico da vitrine.
    """
    link_padrao = (
        obter_segredo("LINK_VITRINE_PADRAO")
        or os.getenv("LINK_VITRINE_PADRAO", "https://beacons.ai/sualoja")
    )
    alvo = str(media_id).strip()

    try:
        prods = _obter_produtos_com_cache(forcar=False)
        for p in prods:
            if (p.media_id_instagram or "").strip() == alvo:
                link = (p.link_afiliado or "").strip()
                if link:
                    logger.info("Link encontrado para media_id %s: %s", media_id, link)
                    return link

        # Se não encontrou no cache e o cache já existe, tenta um refresh rápido
        if _cache_produtos:
            prods = _obter_produtos_com_cache(forcar=True)
            for p in prods:
                if (p.media_id_instagram or "").strip() == alvo:
                    link = (p.link_afiliado or "").strip()
                    if link:
                        logger.info("Link encontrado após refresh para media_id %s: %s", media_id, link)
                        return link
    except Exception as exc:
        logger.error("Erro ao ler produtos no webhook: %s", exc)

    logger.warning("media_id %s não encontrado — usando link padrão", media_id)
    return link_padrao


def curtir_comentario(comment_id: str) -> bool:
    """Curte o comentário do usuário."""
    url = f"https://graph.facebook.com/v19.0/{comment_id}/likes"
    payload = {"access_token": ACCESS_TOKEN}
    try:
        resp = requests.post(url, data=payload, timeout=TIMEOUT_REQUESTS)
        resp.raise_for_status()
        logger.info("Comentário %s curtido.", comment_id)
        return True
    except Exception as e:
        logger.error("Erro ao curtir comentário %s: %s", comment_id, e)
        return False


def responder_comentario(comment_id: str, mensagem: str) -> bool:
    """Responde publicamente ao comentário."""
    url = f"https://graph.facebook.com/v19.0/{comment_id}/replies"
    payload = {
        "message": mensagem,
        "access_token": ACCESS_TOKEN,
    }
    try:
        resp = requests.post(url, json=payload, timeout=TIMEOUT_REQUESTS)
        resp.raise_for_status()
        logger.info("Respondido ao comentário %s.", comment_id)
        return True
    except Exception as e:
        logger.error("Erro ao responder comentário %s: %s", comment_id, e)
        return False


def enviar_direct_message(user_id: str, mensagem: str) -> bool:
    """Envia uma mensagem direta (DM) para o usuário."""
    url = "https://graph.facebook.com/v19.0/me/messages"
    payload = {
        "recipient": {"id": user_id},
        "message": {"text": mensagem},
        "messaging_type": "RESPONSE",
        "access_token": ACCESS_TOKEN,
    }
    try:
        resp = requests.post(url, json=payload, timeout=TIMEOUT_REQUESTS)
        resp.raise_for_status()
        logger.info("Direct enviado para %s: %s", user_id, mensagem)
        return True
    except Exception as e:
        logger.error("Erro ao enviar DM para %s: %s", user_id, e)
        return False


def processar_gatilho_comentario(
    user_id: str,
    username: str,
    comment_id: str,
    media_id: str,
) -> None:
    """Processa o disparo de DM, curtida e resposta em segundo plano."""
    try:
        link = buscar_link_por_media_id(media_id)

        mensagem_dm = (
            f"Oii @{username}! Tudo bem? 😊\n\n"
            f"Aqui está o link do achadinho que você pediu:\n{link}\n\n"
            f"Qualquer dúvida, é só me chamar!"
        )

        # 1. Envia direct message
        enviar_direct_message(user_id, mensagem_dm)

        # 2. Curte o comentário
        curtir_comentario(comment_id)

        # 3. Responde publicamente
        responder_comentario(comment_id, f"Oii @{username}! Te mandei o link no Direct! 🚀")
    except Exception as exc:
        logger.error("Falha ao processar gatilho em segundo plano: %s", exc)


# ==========================================
# ENDPOINTS DO WEBHOOK
# ==========================================

@app.get("/webhook")
async def verify_webhook(request: Request):
    """
    Endpoint usado pelo Facebook/Meta apenas para validar a URL do Webhook.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook validado pela Meta com sucesso!")
        return int(challenge)

    raise HTTPException(status_code=403, detail="Token de verificação inválido")


@app.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint que recebe os eventos (comentários, mensagens, etc) da Meta.
    Envia tarefas demoradas para background_tasks para responder 200 OK imediatamente.
    """
    try:
        body = await request.json()
    except Exception as exc:
        logger.warning("Payload do webhook inválido: %s", exc)
        return {"status": "ignored"}

    logger.info("Evento recebido: %s", body)

    if body.get("object") == "instagram":
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                # Processa apenas novos comentários
                if change.get("field") == "comments":
                    comentario = change.get("value", {})

                    user_id = comentario.get("from", {}).get("id")
                    username = comentario.get("from", {}).get("username", "")
                    text = comentario.get("text", "").lower()
                    comment_id = comentario.get("id")
                    media_id = comentario.get("media", {}).get("id")

                    # Evita o bot responder a si mesmo
                    if str(user_id) == str(PAGE_ID):
                        continue

                    # VERIFICAÇÃO DA PALAVRA CHAVE
                    if "quero" in text or "link" in text:
                        logger.info("Gatilho detectado de @%s (ID: %s)", username, user_id)
                        background_tasks.add_task(
                            processar_gatilho_comentario,
                            user_id=str(user_id),
                            username=str(username),
                            comment_id=str(comment_id),
                            media_id=str(media_id),
                        )

    # O Facebook exige que retornemos 200 OK rapidamente
    return {"status": "success"}


if __name__ == "__main__":
    import uvicorn
    # Para rodar: python webhook_insta.py
    uvicorn.run(app, host="0.0.0.0", port=8000)
