"""Autenticação da API: chaves (API Key) e tokens Bearer assinados. As chaves nunca ficam guardadas em claro (só o hash SHA-256)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from . import db
from .config import agora, txt

PREFIXO = "snl_"
TOKEN_VALIDADE_S = 3600


def _hash(chave: str) -> str:
    return hashlib.sha256(chave.encode()).hexdigest()


def criar_chave(nome: str) -> str:
    """Gera uma chave nova. Devolve-a UMA vez (em claro); na base de dados fica só o hash."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Indique um nome para a chave (ex.: «SIG-CAD — teste»).")
    chave = PREFIXO + secrets.token_urlsafe(32)
    with db.tx() as c:
        c.execute("INSERT INTO api_chaves(nome,prefixo,hash,ativa,criada_em) VALUES(?,?,?,1,?)", (nome, chave[:10], _hash(chave), txt(agora())))
    return chave


def listar_chaves() -> list[dict]:
    return db.consultar("SELECT id,nome,prefixo,ativa,criada_em,ultimo_uso,pedidos FROM api_chaves ORDER BY id")


def definir_ativa(chave_id: int, ativa: bool):
    with db.tx() as c:
        c.execute("UPDATE api_chaves SET ativa=? WHERE id=?", (int(ativa), chave_id))


def eliminar_chave(chave_id: int):
    with db.tx() as c:
        c.execute("DELETE FROM api_chaves WHERE id=?", (chave_id,))


def _segredo() -> bytes:
    s = db.cfg_get("segredo_tokens")
    if not s:
        s = secrets.token_hex(32)
        db.cfg_set("segredo_tokens", s)
    return s.encode()


def emitir_token(chave_id: int) -> dict:
    exp = int(time.time()) + TOKEN_VALIDADE_S
    corpo = base64.urlsafe_b64encode(json.dumps(dict(k=chave_id, exp=exp)).encode()).decode().rstrip("=")
    assin = hmac.new(_segredo(), corpo.encode(), hashlib.sha256).hexdigest()
    return dict(access_token=f"snt.{corpo}.{assin}", token_type="Bearer", expires_in=TOKEN_VALIDADE_S)


def validar(credencial: str | None) -> dict | None:
    """Aceita uma API Key (snl_…) ou um token Bearer (snt.…). Devolve o registo da chave ou None."""
    if not credencial:
        return None
    credencial = credencial.strip()
    if credencial.startswith("snt."):
        try:
            _, corpo, assin = credencial.split(".")
            esperado = hmac.new(_segredo(), corpo.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(assin, esperado):
                return None
            dados = json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)))
            if dados["exp"] < time.time():
                return None
            return db.um("SELECT * FROM api_chaves WHERE id=? AND ativa=1", (dados["k"],))
        except Exception:
            return None
    return db.um("SELECT * FROM api_chaves WHERE hash=? AND ativa=1", (_hash(credencial),))


def registar_uso(chave_id: int):
    with db.tx() as c:
        c.execute("UPDATE api_chaves SET ultimo_uso=?, pedidos=pedidos+1 WHERE id=?", (txt(agora()), chave_id))
