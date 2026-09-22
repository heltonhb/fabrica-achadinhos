import os
import csv
import requests
import logging
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BotInsta")

# Carrega variáveis do .env
load_dotenv()
PAGE_ID = os.getenv("INSTAGRAM_PAGE_ID", "")
ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "meu_token_secreto_123")  # Configure no painel da Meta

app = FastAPI(title="Bot Instagram - Fábrica de Achadinhos")

# ==========================================
# FUNÇÕES DE INTEGRAÇÃO COM INSTAGRAM
# ==========================================

def buscar_link_por_media_id(media_id: str) -> str:
    """
    Retorna o link afiliado associado ao media_id do Instagram.

    O mapeamento é lido de ``achados.csv``. A coluna ``Media ID Instagram``
    deve conter o ID da publicação (preenchida manualmente após cada post).
    Se não encontrar correspondência, devolve um link genérico da vitrine.
    """
    csv_path = Path(__file__).resolve().parent / "achados.csv"
    link_padrao = os.getenv("LINK_VITRINE_PADRAO", "https://beacons.ai/sualoja")

    if not csv_path.exists():
        logger.warning("achados.csv não encontrado — usando link padrão")
        return link_padrao

    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            for linha in csv.DictReader(f):
                if (linha.get("Media ID Instagram") or "").strip() == str(media_id).strip():
                    link = (linha.get("Link Afiliado Shopee") or "").strip()
                    if link:
                        logger.info("Link encontrado para media_id %s: %s", media_id, link)
                        return link
    except Exception as exc:
        logger.error("Erro ao ler achados.csv: %s", exc)

    logger.warning("media_id %s não encontrado no CSV — usando link padrão", media_id)
    return link_padrao

def curtir_comentario(comment_id: str):
    """Curte o comentário do usuário."""
    url = f"https://graph.facebook.com/v19.0/{comment_id}/likes"
    payload = {"access_token": ACCESS_TOKEN}
    try:
        requests.post(url, data=payload)
        logger.info(f"Comentário {comment_id} curtido.")
    except Exception as e:
        logger.error(f"Erro ao curtir comentário: {e}")

def responder_comentario(comment_id: str, mensagem: str):
    """Responde publicamente ao comentário."""
    url = f"https://graph.facebook.com/v19.0/{comment_id}/replies"
    payload = {
        "message": mensagem,
        "access_token": ACCESS_TOKEN
    }
    try:
        requests.post(url, json=payload)
        logger.info(f"Respondido ao comentário {comment_id}.")
    except Exception as e:
        logger.error(f"Erro ao responder comentário: {e}")

def enviar_direct_message(user_id: str, mensagem: str):
    """Envia uma mensagem direta (DM) para o usuário."""
    url = f"https://graph.facebook.com/v19.0/me/messages"
    payload = {
        "recipient": {"id": user_id},
        "message": {"text": mensagem},
        "messaging_type": "RESPONSE",
        "access_token": ACCESS_TOKEN
    }
    try:
        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        logger.info(f"Direct enviado para {user_id}: {mensagem}")
    except Exception as e:
        logger.error(f"Erro ao enviar DM: {e}")


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
async def handle_webhook(request: Request):
    """
    Endpoint que recebe os eventos (comentários, mensagens, etc) da Meta.
    """
    body = await request.json()
    logger.info(f"Evento recebido: {body}")

    if body.get("object") == "instagram":
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                # Processa apenas novos comentários
                if change.get("field") == "comments":
                    comentario = change.get("value", {})
                    
                    user_id = comentario.get("from", {}).get("id")
                    username = comentario.get("from", {}).get("username")
                    text = comentario.get("text", "").lower()
                    comment_id = comentario.get("id")
                    media_id = comentario.get("media", {}).get("id")
                    
                    # Evita o bot responder a si mesmo
                    if str(user_id) == str(PAGE_ID):
                        continue

                    # VERIFICAÇÃO DA PALAVRA CHAVE
                    if "quero" in text or "link" in text:
                        logger.info(f"Gatilho detectado de @{username} (ID: {user_id})")
                        
                        # 1. Busca o link afiliado (idealmente no seu DB)
                        link = buscar_link_por_media_id(media_id)
                        
                        mensagem_dm = (
                            f"Oii @{username}! Tudo bem? 😊\n\n"
                            f"Aqui está o link do achadinho que você pediu:\n{link}\n\n"
                            f"Qualquer dúvida, é só me chamar!"
                        )
                        
                        # 2. Envia DM
                        enviar_direct_message(user_id, mensagem_dm)
                        
                        # 3. Curte o comentário e responde
                        curtir_comentario(comment_id)
                        responder_comentario(comment_id, f"Oii @{username}! Te mandei o link no Direct! 🚀")
                        
    # O Facebook exige que retornemos 200 OK rapidamente
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    # Para rodar: python webhook_insta.py
    uvicorn.run(app, host="0.0.0.0", port=8000)
