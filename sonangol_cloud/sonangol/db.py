"""Base de dados SQLite (WAL) da plataforma SONANGOL."""
from __future__ import annotations

import contextlib
import sqlite3
import threading

from .config import CAMINHO_BD

_lock = threading.RLock()

ESQUEMA = """
CREATE TABLE IF NOT EXISTS provincias(
    id INTEGER PRIMARY KEY, codigo TEXT UNIQUE NOT NULL, nome TEXT UNIQUE NOT NULL, sede TEXT, lat REAL, lon REAL,
    populacao_milhoes REAL);
CREATE TABLE IF NOT EXISTS municipios(
    id INTEGER PRIMARY KEY, provincia TEXT NOT NULL REFERENCES provincias(nome), nome TEXT NOT NULL, lat REAL, lon REAL,
    area_km2 REAL, populacao INTEGER, capital INTEGER DEFAULT 0, UNIQUE(provincia, nome));
CREATE TABLE IF NOT EXISTS empresas(
    id INTEGER PRIMARY KEY, codigo TEXT UNIQUE NOT NULL, nome TEXT UNIQUE NOT NULL, tipo TEXT NOT NULL,
    simulado INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS produtos(
    nome TEXT PRIMARY KEY, categoria TEXT, unidade TEXT NOT NULL DEFAULT 'L', unidade_preco TEXT NOT NULL,
    preco REAL, preco_desde TEXT, ativo INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS instalacoes(
    id INTEGER PRIMARY KEY, codigo TEXT UNIQUE NOT NULL, nome TEXT NOT NULL, tipo TEXT NOT NULL, empresa_id INTEGER REFERENCES empresas(id),
    provincia TEXT NOT NULL REFERENCES provincias(nome), municipio TEXT, lat REAL, lon REAL,
    estado TEXT NOT NULL DEFAULT 'Operacional', criado_em TEXT, atualizado_em TEXT, simulado INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS postos(
    id INTEGER PRIMARY KEY, codigo TEXT UNIQUE NOT NULL, nome TEXT NOT NULL, empresa_id INTEGER NOT NULL REFERENCES empresas(id),
    provincia TEXT NOT NULL REFERENCES provincias(nome), municipio TEXT NOT NULL, lat REAL, lon REAL,
    tipo TEXT, servicos TEXT DEFAULT '', estado TEXT NOT NULL DEFAULT 'Operacional', motivo TEXT DEFAULT '',
    criado_em TEXT, atualizado_em TEXT NOT NULL, simulado INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS ix_postos_prov ON postos(provincia, municipio);
CREATE INDEX IF NOT EXISTS ix_postos_emp ON postos(empresa_id);
CREATE TABLE IF NOT EXISTS posto_produtos(
    posto_id INTEGER NOT NULL REFERENCES postos(id) ON DELETE CASCADE, produto TEXT NOT NULL REFERENCES produtos(nome),
    PRIMARY KEY(posto_id, produto));
CREATE TABLE IF NOT EXISTS reservatorios(
    id INTEGER PRIMARY KEY, codigo TEXT NOT NULL, posto_id INTEGER REFERENCES postos(id) ON DELETE CASCADE,
    instalacao_id INTEGER REFERENCES instalacoes(id) ON DELETE CASCADE, produto TEXT NOT NULL REFERENCES produtos(nome),
    capacidade_l REAL NOT NULL CHECK(capacidade_l > 0), quantidade_l REAL NOT NULL DEFAULT 0 CHECK(quantidade_l >= 0),
    minimo_operacional_l REAL NOT NULL DEFAULT 0 CHECK(minimo_operacional_l >= 0),
    estado TEXT NOT NULL DEFAULT 'Operacional', atualizado_em TEXT NOT NULL, simulado INTEGER NOT NULL DEFAULT 1,
    CHECK((posto_id IS NULL) != (instalacao_id IS NULL)), CHECK(quantidade_l <= capacidade_l + 0.001));
CREATE UNIQUE INDEX IF NOT EXISTS ux_res_cod ON reservatorios(COALESCE(posto_id,0), COALESCE(instalacao_id,0), codigo);
CREATE INDEX IF NOT EXISTS ix_res_posto ON reservatorios(posto_id, produto);
CREATE INDEX IF NOT EXISTS ix_res_inst ON reservatorios(instalacao_id, produto);
CREATE TABLE IF NOT EXISTS bombas(
    id INTEGER PRIMARY KEY, codigo TEXT NOT NULL, posto_id INTEGER NOT NULL REFERENCES postos(id) ON DELETE CASCADE,
    produto TEXT NOT NULL REFERENCES produtos(nome), estado TEXT NOT NULL DEFAULT 'Operacional', atualizado_em TEXT NOT NULL,
    simulado INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS ix_bombas_posto ON bombas(posto_id, produto);
CREATE TABLE IF NOT EXISTS entregas(
    id INTEGER PRIMARY KEY, codigo TEXT UNIQUE NOT NULL, produto TEXT NOT NULL REFERENCES produtos(nome),
    quantidade_l REAL NOT NULL CHECK(quantidade_l > 0), origem_instalacao_id INTEGER REFERENCES instalacoes(id),
    origem_descricao TEXT, destino_posto_id INTEGER REFERENCES postos(id), destino_instalacao_id INTEGER REFERENCES instalacoes(id),
    destino_reservatorio_id INTEGER REFERENCES reservatorios(id), veiculo TEXT, estado TEXT NOT NULL DEFAULT 'Planeada',
    data_saida TEXT, data_prevista_chegada TEXT, data_chegada TEXT, criado_em TEXT, atualizado_em TEXT NOT NULL,
    simulado INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS ix_ent_estado ON entregas(estado, produto);
CREATE TABLE IF NOT EXISTS movimentos(
    id INTEGER PRIMARY KEY, data_hora TEXT NOT NULL, tipo TEXT NOT NULL, reservatorio_id INTEGER NOT NULL REFERENCES reservatorios(id) ON DELETE CASCADE,
    posto_id INTEGER, instalacao_id INTEGER, produto TEXT NOT NULL, delta_l REAL NOT NULL, stock_apos_l REAL NOT NULL,
    entrega_id INTEGER, observacao TEXT DEFAULT '', simulado INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS ix_mov_data ON movimentos(data_hora);
CREATE INDEX IF NOT EXISTS ix_mov_res ON movimentos(reservatorio_id, id);
CREATE INDEX IF NOT EXISTS ix_mov_posto ON movimentos(posto_id, produto, data_hora);
CREATE TABLE IF NOT EXISTS api_chaves(
    id INTEGER PRIMARY KEY, nome TEXT NOT NULL, prefixo TEXT NOT NULL, hash TEXT NOT NULL UNIQUE, ativa INTEGER NOT NULL DEFAULT 1,
    criada_em TEXT NOT NULL, ultimo_uso TEXT, pedidos INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS api_log(
    id INTEGER PRIMARY KEY, data_hora TEXT NOT NULL, chave_id INTEGER, metodo TEXT, caminho TEXT, estado INTEGER, ms INTEGER, ip TEXT);
CREATE TABLE IF NOT EXISTS auditoria(
    id INTEGER PRIMARY KEY, data_hora TEXT NOT NULL, utilizador TEXT, entidade TEXT, entidade_id TEXT, acao TEXT, detalhe TEXT);
CREATE TABLE IF NOT EXISTS config(chave TEXT PRIMARY KEY, valor TEXT);
"""


def ligar() -> sqlite3.Connection:
    c = sqlite3.connect(str(CAMINHO_BD), timeout=30, isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def iniciar() -> None:
    c = ligar()
    try:
        c.executescript(ESQUEMA)
    finally:
        c.close()


@contextlib.contextmanager
def tx():
    """Ligação com transação de escrita atómica (BEGIN IMMEDIATE → COMMIT/ROLLBACK)."""
    c = ligar()
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.execute("COMMIT")
    except BaseException:
        try:
            c.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        c.close()


@contextlib.contextmanager
def leitura():
    c = ligar()
    try:
        yield c
    finally:
        c.close()


def consultar(sql: str, params=()) -> list[dict]:
    with leitura() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def um(sql: str, params=()) -> dict | None:
    r = consultar(sql, params)
    return r[0] if r else None


def cfg_get(chave: str, padrao=None):
    r = um("SELECT valor FROM config WHERE chave=?", (chave,))
    return r["valor"] if r else padrao


def cfg_set(chave: str, valor: str, c=None) -> None:
    if c is not None:
        c.execute("INSERT INTO config(chave,valor) VALUES(?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (chave, valor))
        return
    with tx() as cc:
        cfg_set(chave, valor, cc)
