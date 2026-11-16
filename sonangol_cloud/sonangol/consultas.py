"""Camada de leitura: consultas com filtros, validação e paginação. Usada pela API REST, pelo Excel e pelo painel."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta

from . import db
from .config import (ESTADOS_BOMBA, ESTADOS_ENTREGA, ESTADOS_POSTO, ESTADOS_RESERVATORIO, LIMIAR_BAIXO, NOMES_PRODUTOS, PRODUTOS,
                     TIPOS_INSTALACAO, TIPOS_MOVIMENTO, agora, iso, txt)

PAGINA_MAX = 10000          # máximo de registos por pedido
PAGINA_PADRAO = 5000        # por omissão devolve tudo até 5000 (um pedido chega para a rede completa)


class ErroValidacao(ValueError):
    def __init__(self, mensagem: str, campo: str | None = None):
        super().__init__(mensagem)
        self.campo = campo


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


_SIN = {"gasoleo": "Gasóleo", "diesel": "Gasóleo", "gasoil": "Gasóleo", "gasolina": "Gasolina", "gasoline": "Gasolina",
        "petrol": "Gasolina", "jeta1": "Jet A1", "jet": "Jet A1", "petroleoiluminante": "Petróleo iluminante",
        "querosene": "Petróleo iluminante", "kerosene": "Petróleo iluminante", "iluminante": "Petróleo iluminante",
        "gpl": "GPL", "lpg": "GPL", "gas": "GPL"}


def produto_canonico(v) -> str:
    k = norm(v)
    if k in _SIN:
        return _SIN[k]
    for n in NOMES_PRODUTOS:
        if norm(n) == k:
            return n
    raise ErroValidacao(f"Produto desconhecido «{v}». Valores válidos: {', '.join(NOMES_PRODUTOS)}.", "produto")


def provincias() -> list[str]:
    return [r["nome"] for r in db.consultar("SELECT nome FROM provincias ORDER BY id")]


def provincia_canonica(v) -> str:
    k = norm(v)
    for n in provincias():
        if norm(n) == k:
            return n
    raise ErroValidacao(f"Província desconhecida «{v}». Use GET /provincias para a lista das 21 províncias.", "provincia")


def municipio_canonico(v, provincia: str | None = None) -> str:
    k = norm(v)
    sql, p = "SELECT nome, provincia FROM municipios", []
    if provincia:
        sql += " WHERE provincia=?"
        p.append(provincia)
    for r in db.consultar(sql, p):
        if norm(r["nome"]) == k:
            return r["nome"]
    raise ErroValidacao(f"Município desconhecido «{v}»" + (f" na província {provincia}" if provincia else "") + ".", "municipio")


def empresa_canonica(v) -> int:
    k = norm(v)
    for r in db.consultar("SELECT id,codigo,nome FROM empresas"):
        if k in (norm(r["codigo"]), norm(r["nome"]), str(r["id"])):
            return r["id"]
    raise ErroValidacao(f"Empresa desconhecida «{v}».", "empresa")


def data_filtro(v, campo: str, fim: bool = False) -> str | None:
    if v in (None, ""):
        return None
    s = str(v).strip().replace("T", " ")
    s = re.sub(r"(Z|[+-]\d\d:?\d\d)$", "", s).strip()
    for f, curto in (("%Y-%m-%d %H:%M:%S", False), ("%Y-%m-%d %H:%M", False), ("%Y-%m-%d", True)):
        try:
            d = datetime.strptime(s, f)
            if curto and fim:
                d = d + timedelta(days=1) - timedelta(seconds=1)
            return txt(d)
        except ValueError:
            continue
    raise ErroValidacao(f"Data inválida «{v}» em «{campo}». Use AAAA-MM-DD ou AAAA-MM-DDTHH:MM:SS.", campo)


def inteiro(v, campo: str, padrao: int, minimo: int, maximo: int) -> int:
    if v in (None, ""):
        return padrao
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ErroValidacao(f"«{campo}» deve ser um número inteiro.", campo)
    if not minimo <= n <= maximo:
        raise ErroValidacao(f"«{campo}» deve estar entre {minimo} e {maximo}.", campo)
    return n


def escolha(v, validos: list[str], campo: str) -> str | None:
    if v in (None, ""):
        return None
    for x in validos:
        if norm(x) == norm(v):
            return x
    raise ErroValidacao(f"Valor inválido «{v}» em «{campo}». Valores válidos: {', '.join(validos)}.", campo)


def pagina(sql: str, params: list, ordem: str, f: dict) -> tuple[list[dict], dict]:
    """Executa `sql` (sem ORDER/LIMIT) com paginação. Devolve (linhas, meta)."""
    pg = inteiro(f.get("page"), "page", 1, 1, 10_000_000)
    tam = inteiro(f.get("page_size", f.get("limit")), "page_size", PAGINA_PADRAO, 1, PAGINA_MAX)
    with db.leitura() as c:
        total = c.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]
        rows = [dict(r) for r in c.execute(f"{sql} ORDER BY {ordem} LIMIT ? OFFSET ?", params + [tam, (pg - 1) * tam]).fetchall()]
    paginas = max(1, -(-total // tam))
    return rows, dict(page=pg, page_size=tam, total=total, total_paginas=paginas, tem_proxima=pg < paginas)


def ultima_atualizacao() -> str | None:
    return iso(db.cfg_get("ultima_atualizacao"))


# ------------------------------------------------------------------ disponibilidade (derivada dos reservatórios e bombas)
SQL_DISP = f"""
SELECT p.id AS posto_uid, p.codigo AS posto_id, p.nome AS posto_nome, p.provincia, p.municipio, p.empresa_id, e.nome AS empresa,
       p.estado AS estado_posto, pp.produto,
       COALESCE(t.q, 0) AS stock_l, COALESCE(t.cap, 0) AS capacidade_l, COALESCE(t.util, 0) AS util_l,
       COALESCE(b.ok, 0) AS bombas_ok, COALESCE(b.n, 0) AS bombas_total,
       MAX(COALESCE(t.upd, ''), p.atualizado_em) AS atualizado_em,
       CASE WHEN p.estado='Operacional' AND COALESCE(b.ok,0) > 0 AND COALESCE(t.util,0) > 0 THEN 1 ELSE 0 END AS disponivel
FROM posto_produtos pp
JOIN postos p ON p.id = pp.posto_id
JOIN empresas e ON e.id = p.empresa_id
LEFT JOIN (SELECT posto_id, produto, SUM(quantidade_l) q, SUM(capacidade_l) cap, MAX(atualizado_em) upd,
                  SUM(CASE WHEN estado='Operacional' THEN MAX(quantidade_l - minimo_operacional_l, 0) ELSE 0 END) util
           FROM reservatorios WHERE posto_id IS NOT NULL GROUP BY posto_id, produto) t ON t.posto_id=p.id AND t.produto=pp.produto
LEFT JOIN (SELECT posto_id, produto, SUM(estado='Operacional') ok, COUNT(*) n FROM bombas GROUP BY posto_id, produto) b
       ON b.posto_id=p.id AND b.produto=pp.produto
"""


def estado_disponibilidade(r: dict) -> str:
    if r["estado_posto"] != "Operacional":
        return "Posto " + ("encerrado" if r["estado_posto"] == "Encerrado" else "inoperacional")
    if not r["disponivel"]:
        if r["bombas_ok"] == 0:
            return "Indisponível (bombas inoperacionais)"
        return "Indisponível (sem stock)"
    if r["capacidade_l"] and r["stock_l"] / r["capacidade_l"] < LIMIAR_BAIXO:
        return "Stock reduzido"
    return "Disponível"


def _filtros_posto(f: dict, alias: str = "p") -> tuple[str, list]:
    w, p = [], []
    prov = provincia_canonica(f["provincia"]) if f.get("provincia") else None
    if prov:
        w.append(f"{alias}.provincia=?")
        p.append(prov)
    if f.get("municipio"):
        w.append(f"{alias}.municipio=?")
        p.append(municipio_canonico(f["municipio"], prov))
    if f.get("empresa"):
        w.append(f"{alias}.empresa_id=?")
        p.append(empresa_canonica(f["empresa"]))
    est = escolha(f.get("estado"), ESTADOS_POSTO, "estado")
    if est:
        w.append(f"{alias}.estado=?")
        p.append(est)
    return (" AND ".join(w), p)


def _juntar(base_where: str, extra: str) -> str:
    partes = [x for x in (base_where, extra) if x]
    return (" WHERE " + " AND ".join(partes)) if partes else ""


# ------------------------------------------------------------------ postos
def _produtos_por_posto() -> dict:
    out = {}
    for r in db.consultar("SELECT posto_id, produto FROM posto_produtos ORDER BY posto_id, produto"):
        out.setdefault(r["posto_id"], []).append(r["produto"])
    return out


def listar_postos(f: dict, detalhe: bool = False) -> tuple[list[dict], dict]:
    where, params = _filtros_posto(f)
    extra = []
    if f.get("produto"):
        pr = produto_canonico(f["produto"])
        extra.append("EXISTS (SELECT 1 FROM posto_produtos x WHERE x.posto_id=p.id AND x.produto=?)")
        params.append(pr)
        if str(f.get("disponivel", "")).lower() in ("1", "true", "sim"):
            extra.append("EXISTS (SELECT 1 FROM (" + SQL_DISP + ") d WHERE d.posto_uid=p.id AND d.produto=? AND d.disponivel=1)")
            params.append(pr)
        elif str(f.get("disponivel", "")).lower() in ("0", "false", "nao", "não"):
            extra.append("EXISTS (SELECT 1 FROM (" + SQL_DISP + ") d WHERE d.posto_uid=p.id AND d.produto=? AND d.disponivel=0)")
            params.append(pr)
    des = data_filtro(f.get("atualizado_desde") or f.get("desde"), "atualizado_desde")
    if des:
        extra.append("p.atualizado_em>=?")
        params.append(des)
    sql = ("SELECT p.id AS uid, p.codigo AS id, p.nome, p.empresa_id, e.codigo AS empresa_codigo, e.nome AS empresa, p.provincia, p.municipio, "
           "p.lat, p.lon, p.tipo, p.servicos, p.estado, p.motivo, p.atualizado_em FROM postos p JOIN empresas e ON e.id=p.empresa_id"
           + _juntar(where, " AND ".join(extra)))
    rows, meta = pagina(sql, params, "p.id", f)
    prods = _produtos_por_posto()
    for r in rows:
        r["produtos"] = prods.get(r["uid"], [])
        r["servicos"] = [s for s in (r["servicos"] or "").split("|") if s]
        r["situacao"] = "Em funcionamento" if r["estado"] == "Operacional" else r["estado"]
        r["atualizado_em"] = iso(r["atualizado_em"])
        r["simulado"] = True
    if detalhe and rows:
        ids = [r["uid"] for r in rows]
        marcas = ",".join("?" * len(ids))
        disp = db.consultar(f"SELECT * FROM ({SQL_DISP}) WHERE posto_uid IN ({marcas})", ids)
        por = {}
        for d in disp:
            por.setdefault(d["posto_uid"], []).append(dict(
                produto=d["produto"], disponivel=bool(d["disponivel"]), estado=estado_disponibilidade(d), stock_l=d["stock_l"],
                capacidade_l=d["capacidade_l"], ocupacao_pct=round(100 * d["stock_l"] / d["capacidade_l"], 1) if d["capacidade_l"] else 0.0))
        for r in rows:
            r["disponibilidade"] = por.get(r["uid"], [])
    for r in rows:
        r.pop("empresa_id", None)
    return rows, meta


def obter_posto(codigo: str) -> dict | None:
    p = db.um("SELECT uid FROM (SELECT id AS uid, codigo FROM postos) WHERE codigo=?", (codigo,))
    if not p:
        return None
    where = "p.id=?"
    sql = ("SELECT p.id AS uid, p.codigo AS id, p.nome, e.codigo AS empresa_codigo, e.nome AS empresa, p.provincia, p.municipio, "
           "p.lat, p.lon, p.tipo, p.servicos, p.estado, p.motivo, p.atualizado_em FROM postos p JOIN empresas e ON e.id=p.empresa_id WHERE " + where)
    r = db.um(sql, (p["uid"],))
    r["produtos"] = _produtos_por_posto().get(r["uid"], [])
    r["servicos"] = [s for s in (r["servicos"] or "").split("|") if s]
    r["situacao"] = "Em funcionamento" if r["estado"] == "Operacional" else r["estado"]
    r["atualizado_em"] = iso(r["atualizado_em"])
    r["simulado"] = True
    disp = db.consultar(f"SELECT * FROM ({SQL_DISP}) WHERE posto_uid=?", (r["uid"],))
    r["disponibilidade"] = [dict(produto=d["produto"], disponivel=bool(d["disponivel"]), estado=estado_disponibilidade(d), stock_l=d["stock_l"],
                                 capacidade_l=d["capacidade_l"], bombas_operacionais=d["bombas_ok"], bombas_total=d["bombas_total"],
                                 ocupacao_pct=round(100 * d["stock_l"] / d["capacidade_l"], 1) if d["capacidade_l"] else 0.0,
                                 atualizado_em=iso(d["atualizado_em"])) for d in disp]
    r["reservatorios"], _ = listar_reservatorios(dict(posto=codigo))
    r["bombas"], _ = listar_bombas(dict(posto=codigo))
    return r


# ------------------------------------------------------------------ disponibilidade (linhas planas)
def listar_disponibilidade(f: dict, incluir_nao_comercializados: bool = False) -> tuple[list[dict], dict]:
    where, params = _filtros_posto(f)
    extra = []
    if f.get("produto"):
        extra.append("d.produto=?")
        params.append(produto_canonico(f["produto"]))
    disp = str(f.get("disponivel", "")).lower()
    if disp in ("1", "true", "sim"):
        extra.append("d.disponivel=1")
    elif disp in ("0", "false", "nao", "não"):
        extra.append("d.disponivel=0")
    des = data_filtro(f.get("atualizado_desde") or f.get("desde"), "atualizado_desde")
    if des:
        extra.append("d.atualizado_em>=?")
        params.append(des)
    # `where` usa o alias p → no SQL_DISP o alias de postos também é p
    sql = f"SELECT * FROM ({SQL_DISP}" + _juntar(where, "") + ") d" + _juntar("", " AND ".join(extra))
    rows, meta = pagina(sql, params, "d.posto_uid, d.produto", f)
    out = []
    for d in rows:
        out.append(dict(posto_id=d["posto_id"], posto=d["posto_nome"], provincia=d["provincia"], municipio=d["municipio"],
                        empresa=d["empresa"], produto=d["produto"], comercializado=True, disponivel=bool(d["disponivel"]),
                        estado=estado_disponibilidade(d), stock_l=d["stock_l"], capacidade_l=d["capacidade_l"],
                        ocupacao_pct=round(100 * d["stock_l"] / d["capacidade_l"], 1) if d["capacidade_l"] else 0.0,
                        bombas_operacionais=d["bombas_ok"], atualizado_em=iso(d["atualizado_em"]), simulado=True))
    if incluir_nao_comercializados:      # linhas com disponibilidade 0 para produtos que o posto não vende
        vendidos = {(r["posto_id"], r["produto"]) for r in out}
        extra_rows = []
        for p, _ in [listar_postos(dict(f, page_size=PAGINA_MAX))]:
            for x in p:
                for pr in NOMES_PRODUTOS:
                    if (x["id"], pr) not in vendidos and (not f.get("produto") or produto_canonico(f["produto"]) == pr):
                        extra_rows.append(dict(posto_id=x["id"], posto=x["nome"], provincia=x["provincia"], municipio=x["municipio"],
                                               empresa=x["empresa"], produto=pr, comercializado=False, disponivel=False,
                                               estado="Não comercializado", stock_l=0.0, capacidade_l=0.0, ocupacao_pct=0.0,
                                               bombas_operacionais=0, atualizado_em=x["atualizado_em"], simulado=True))
        out += extra_rows
        meta["total"] += len(extra_rows)
    return out, meta


# ------------------------------------------------------------------ reservatórios e bombas
def listar_reservatorios(f: dict) -> tuple[list[dict], dict]:
    w, p = [], []
    if f.get("posto"):
        w.append("po.codigo=?")
        p.append(str(f["posto"]))
    if f.get("instalacao"):
        w.append("i.codigo=?")
        p.append(str(f["instalacao"]))
    if f.get("proprietario") in ("posto", "instalacao"):
        w.append("r.posto_id IS NOT NULL" if f["proprietario"] == "posto" else "r.instalacao_id IS NOT NULL")
    if f.get("provincia"):
        prov = provincia_canonica(f["provincia"])
        w.append("COALESCE(po.provincia, i.provincia)=?")
        p.append(prov)
    if f.get("municipio"):
        w.append("COALESCE(po.municipio, i.municipio)=?")
        p.append(municipio_canonico(f["municipio"], provincia_canonica(f["provincia"]) if f.get("provincia") else None))
    if f.get("empresa"):
        w.append("COALESCE(po.empresa_id, i.empresa_id)=?")
        p.append(empresa_canonica(f["empresa"]))
    if f.get("produto"):
        w.append("r.produto=?")
        p.append(produto_canonico(f["produto"]))
    est = escolha(f.get("estado"), ESTADOS_RESERVATORIO, "estado")
    if est:
        w.append("r.estado=?")
        p.append(est)
    if str(f.get("stock_reduzido", "")).lower() in ("1", "true", "sim"):
        w.append(f"r.quantidade_l < {LIMIAR_BAIXO} * r.capacidade_l")
    des = data_filtro(f.get("atualizado_desde") or f.get("desde"), "atualizado_desde")
    if des:
        w.append("r.atualizado_em>=?")
        p.append(des)
    sql = ("SELECT r.id AS uid, COALESCE(po.codigo || '/' || r.codigo, i.codigo || '/' || r.codigo) AS reservatorio_id, "
           "po.codigo AS posto_id, i.codigo AS instalacao_id, COALESCE(po.nome, i.nome) AS pertence_a, "
           "CASE WHEN r.posto_id IS NOT NULL THEN 'Posto' ELSE i.tipo END AS tipo_proprietario, "
           "COALESCE(po.provincia, i.provincia) AS provincia, COALESCE(po.municipio, i.municipio) AS municipio, "
           "r.produto, r.capacidade_l, r.quantidade_l AS litros, r.minimo_operacional_l, r.estado, r.atualizado_em "
           "FROM reservatorios r LEFT JOIN postos po ON po.id=r.posto_id LEFT JOIN instalacoes i ON i.id=r.instalacao_id"
           + _juntar(" AND ".join(w), ""))
    rows, meta = pagina(sql, p, "r.id", f)
    for r in rows:
        cap = r["capacidade_l"]
        r["ocupacao_pct"] = round(100 * r["litros"] / cap, 1) if cap else 0.0
        r["abaixo_do_minimo"] = r["litros"] <= r["minimo_operacional_l"]
        r["stock_reduzido"] = r["litros"] < LIMIAR_BAIXO * cap
        r["atualizado_em"] = iso(r["atualizado_em"])
        r["simulado"] = True
    return rows, meta


def listar_bombas(f: dict) -> tuple[list[dict], dict]:
    w, p = [], []
    if f.get("posto"):
        w.append("po.codigo=?")
        p.append(str(f["posto"]))
    if f.get("provincia"):
        w.append("po.provincia=?")
        p.append(provincia_canonica(f["provincia"]))
    if f.get("empresa"):
        w.append("po.empresa_id=?")
        p.append(empresa_canonica(f["empresa"]))
    if f.get("produto"):
        w.append("b.produto=?")
        p.append(produto_canonico(f["produto"]))
    est = escolha(f.get("estado"), ESTADOS_BOMBA, "estado")
    if est:
        w.append("b.estado=?")
        p.append(est)
    sql = ("SELECT b.id AS uid, po.codigo || '/' || b.codigo AS bomba_id, po.codigo AS posto_id, po.provincia, b.produto, b.estado, b.atualizado_em "
           "FROM bombas b JOIN postos po ON po.id=b.posto_id" + _juntar(" AND ".join(w), ""))
    rows, meta = pagina(sql, p, "b.id", f)
    for r in rows:
        r["atualizado_em"] = iso(r["atualizado_em"])
        r["simulado"] = True
    return rows, meta


# ------------------------------------------------------------------ preços, produtos, empresas, instalações, geografia
def listar_precos(f: dict) -> tuple[list[dict], dict]:
    p = []
    sql = "SELECT nome AS produto, preco, unidade_preco AS unidade, preco_desde AS vigente_desde, categoria FROM produtos WHERE ativo=1"
    if f.get("produto"):
        sql += " AND nome=?"
        p.append(produto_canonico(f["produto"]))
    rows, meta = pagina(sql, p, "nome", f)
    atual = iso(txt(agora()))
    for r in rows:
        r["moeda"] = "AOA"
        r["regulado"] = True
        r["atualizado_em"] = iso(db.cfg_get("ultima_atualizacao")) or atual
        r["simulado"] = True
    return rows, meta


def listar_empresas(f: dict) -> tuple[list[dict], dict]:
    rows, meta = pagina("SELECT e.id AS uid, e.codigo AS id, e.nome, e.tipo, "
                        "(SELECT COUNT(*) FROM postos p WHERE p.empresa_id=e.id) AS postos, "
                        "(SELECT COUNT(*) FROM instalacoes i WHERE i.empresa_id=e.id) AS instalacoes FROM empresas e", [], "e.id", f)
    for r in rows:
        r["simulado"] = True
    return rows, meta


def listar_instalacoes(f: dict) -> tuple[list[dict], dict]:
    w, p = [], []
    t = escolha(f.get("tipo"), TIPOS_INSTALACAO, "tipo")
    if t:
        w.append("i.tipo=?")
        p.append(t)
    if f.get("provincia"):
        w.append("i.provincia=?")
        p.append(provincia_canonica(f["provincia"]))
    if f.get("empresa"):
        w.append("i.empresa_id=?")
        p.append(empresa_canonica(f["empresa"]))
    sql = ("SELECT i.id AS uid, i.codigo AS id, i.nome, i.tipo, e.nome AS empresa, i.provincia, i.municipio, i.lat, i.lon, i.estado, "
           "(SELECT COALESCE(SUM(capacidade_l),0) FROM reservatorios r WHERE r.instalacao_id=i.id) AS capacidade_l, "
           "(SELECT COALESCE(SUM(quantidade_l),0) FROM reservatorios r WHERE r.instalacao_id=i.id) AS stock_l, i.atualizado_em "
           "FROM instalacoes i LEFT JOIN empresas e ON e.id=i.empresa_id" + _juntar(" AND ".join(w), ""))
    rows, meta = pagina(sql, p, "i.id", f)
    for r in rows:
        r["ocupacao_pct"] = round(100 * r["stock_l"] / r["capacidade_l"], 1) if r["capacidade_l"] else 0.0
        r["atualizado_em"] = iso(r["atualizado_em"])
        r["simulado"] = True
    return rows, meta


def listar_provincias() -> list[dict]:
    rows = db.consultar(
        "SELECT p.codigo AS id, p.nome, p.sede, p.lat, p.lon, p.populacao_milhoes, "
        "(SELECT COUNT(*) FROM municipios m WHERE m.provincia=p.nome) AS municipios, "
        "(SELECT COUNT(*) FROM postos x WHERE x.provincia=p.nome) AS postos FROM provincias p ORDER BY p.id")
    return rows


def listar_municipios(f: dict) -> tuple[list[dict], dict]:
    w, p = [], []
    if f.get("provincia"):
        w.append("provincia=?")
        p.append(provincia_canonica(f["provincia"]))
    sql = ("SELECT id AS uid, nome, provincia, lat, lon, area_km2, populacao, capital, "
           "(SELECT COUNT(*) FROM postos x WHERE x.provincia=m.provincia AND x.municipio=m.nome) AS postos FROM municipios m" + _juntar(" AND ".join(w), ""))
    return pagina(sql, p, "id", f)


def listar_produtos() -> list[dict]:
    return db.consultar("SELECT nome AS id, nome, categoria, unidade, unidade_preco, preco, preco_desde FROM produtos WHERE ativo=1 ORDER BY rowid")


# ------------------------------------------------------------------ movimentos e entregas
def listar_movimentos(f: dict) -> tuple[list[dict], dict]:
    w, p = [], []
    if f.get("produto"):
        w.append("m.produto=?")
        p.append(produto_canonico(f["produto"]))
    tp = escolha(f.get("tipo"), TIPOS_MOVIMENTO, "tipo")
    if tp:
        w.append("m.tipo=?")
        p.append(tp)
    if f.get("posto"):
        w.append("po.codigo=?")
        p.append(str(f["posto"]))
    if f.get("instalacao"):
        w.append("i.codigo=?")
        p.append(str(f["instalacao"]))
    if f.get("provincia"):
        w.append("COALESCE(po.provincia, i.provincia)=?")
        p.append(provincia_canonica(f["provincia"]))
    if f.get("empresa"):
        w.append("po.empresa_id=?")
        p.append(empresa_canonica(f["empresa"]))
    d1, d2 = data_filtro(f.get("desde"), "desde"), data_filtro(f.get("ate"), "ate", True)
    if d1:
        w.append("m.data_hora>=?")
        p.append(d1)
    if d2:
        w.append("m.data_hora<=?")
        p.append(d2)
    sql = ("SELECT m.id AS id, m.data_hora, m.tipo, po.codigo AS posto_id, i.codigo AS instalacao_id, "
           "COALESCE(po.provincia, i.provincia) AS provincia, m.produto, m.delta_l AS variacao_l, m.stock_apos_l, en.codigo AS entrega_id, m.observacao "
           "FROM movimentos m LEFT JOIN postos po ON po.id=m.posto_id LEFT JOIN instalacoes i ON i.id=m.instalacao_id "
           "LEFT JOIN entregas en ON en.id=m.entrega_id" + _juntar(" AND ".join(w), ""))
    rows, meta = pagina(sql, p, "m.data_hora DESC, m.id DESC" if str(f.get("ordem", "")) != "asc" else "m.data_hora, m.id", f)
    for r in rows:
        r["data_hora"] = iso(r["data_hora"])
        r["simulado"] = True
    return rows, meta


def listar_entregas(f: dict) -> tuple[list[dict], dict]:
    w, p = [], []
    est = escolha(f.get("estado"), ESTADOS_ENTREGA, "estado")
    if est:
        w.append("e.estado=?")
        p.append(est)
    if f.get("produto"):
        w.append("e.produto=?")
        p.append(produto_canonico(f["produto"]))
    if f.get("provincia"):
        w.append("COALESCE(po.provincia, di.provincia)=?")
        p.append(provincia_canonica(f["provincia"]))
    if f.get("empresa"):
        w.append("po.empresa_id=?")
        p.append(empresa_canonica(f["empresa"]))
    d1, d2 = data_filtro(f.get("desde"), "desde"), data_filtro(f.get("ate"), "ate", True)
    if d1:
        w.append("e.data_saida>=?")
        p.append(d1)
    if d2:
        w.append("e.data_saida<=?")
        p.append(d2)
    sql = ("SELECT e.id AS uid, e.codigo AS id, e.produto, e.quantidade_l, oi.codigo AS origem_id, COALESCE(oi.nome, e.origem_descricao) AS origem, "
           "oi.provincia AS origem_provincia, COALESCE(po.codigo, di.codigo) AS destino_id, COALESCE(po.nome, di.nome) AS destino, "
           "COALESCE(po.provincia, di.provincia) AS destino_provincia, e.veiculo, e.estado, e.data_saida, e.data_prevista_chegada, "
           "e.data_chegada, e.atualizado_em FROM entregas e LEFT JOIN instalacoes oi ON oi.id=e.origem_instalacao_id "
           "LEFT JOIN postos po ON po.id=e.destino_posto_id LEFT JOIN instalacoes di ON di.id=e.destino_instalacao_id" + _juntar(" AND ".join(w), ""))
    rows, meta = pagina(sql, p, "e.data_saida DESC, e.id DESC", f)
    for r in rows:
        for k in ("data_saida", "data_prevista_chegada", "data_chegada", "atualizado_em"):
            r[k] = iso(r[k])
        r["simulado"] = True
    return rows, meta


# ------------------------------------------------------------------ indicadores
def _periodo(f: dict) -> tuple[str, str]:
    fim = data_filtro(f.get("ate"), "ate", True) or txt(agora())
    ini = data_filtro(f.get("desde"), "desde") or txt(datetime.strptime(fim, "%Y-%m-%d %H:%M:%S") - timedelta(days=7))
    if ini > fim:
        raise ErroValidacao("«desde» não pode ser posterior a «ate».", "desde")
    return ini, fim


def indicadores(f: dict | None = None) -> dict:
    f = f or {}
    ini, fim = _periodo(f)
    emp = empresa_canonica(f["empresa"]) if f.get("empresa") else None
    prov = provincia_canonica(f["provincia"]) if f.get("provincia") else None
    cond, pr = "", []
    if emp:
        cond += " AND p.empresa_id=?"
        pr.append(emp)
    if prov:
        cond += " AND p.provincia=?"
        pr.append(prov)
    postos = db.consultar(f"SELECT p.estado, COUNT(*) n FROM postos p WHERE 1=1{cond} GROUP BY p.estado", pr)
    n_est = {r["estado"]: r["n"] for r in postos}
    disp = db.consultar(f"SELECT d.* FROM ({SQL_DISP}) d JOIN postos p ON p.id=d.posto_uid WHERE 1=1{cond}", pr)
    por_posto = {}
    for d in disp:
        por_posto.setdefault(d["posto_uid"], []).append(d)
    sem, reduzido, com_gas, com_gaso = 0, 0, 0, 0
    for uid, ds in por_posto.items():
        if ds[0]["estado_posto"] != "Operacional":
            continue
        if not any(x["disponivel"] for x in ds):
            sem += 1
        if any(x["disponivel"] and x["capacidade_l"] and x["stock_l"] / x["capacidade_l"] < LIMIAR_BAIXO for x in ds):
            reduzido += 1
    por_prod = {}
    for pr_ in NOMES_PRODUTOS:
        ds = [d for d in disp if d["produto"] == pr_]
        op = [d for d in ds if d["estado_posto"] == "Operacional"]
        por_prod[pr_] = dict(postos_que_vendem=len(ds), com_stock=sum(1 for d in op if d["disponivel"]),
                             sem_stock=sum(1 for d in op if not d["disponivel"]),
                             stock_reduzido=sum(1 for d in op if d["disponivel"] and d["capacidade_l"] and d["stock_l"] / d["capacidade_l"] < LIMIAR_BAIXO),
                             volume_postos_l=round(sum(d["stock_l"] for d in ds), 0))
    # volumes por produto
    cp = cond.replace("p.", "po.")
    base = (f"FROM movimentos m LEFT JOIN postos po ON po.id=m.posto_id LEFT JOIN instalacoes i ON i.id=m.instalacao_id "
            f"WHERE m.data_hora>=? AND m.data_hora<=?{cp}")
    prm = [ini, fim] + pr
    mv = db.consultar(f"SELECT m.produto, m.tipo, m.posto_id IS NOT NULL AS em_posto, SUM(m.delta_l) s {base} GROUP BY 1,2,3", prm)
    vol = {n: dict(vendido_l=0.0, distribuido_l=0.0, recebido_l=0.0) for n in NOMES_PRODUTOS}
    for r in mv:
        v = vol[r["produto"]]
        if r["tipo"] == "Venda":
            v["vendido_l"] += -r["s"]
        elif r["tipo"] == "Distribuição":
            v["distribuido_l"] += -r["s"]
        elif r["tipo"] == "Receção":
            v["recebido_l"] += r["s"]
    arm = {r["produto"]: r for r in db.consultar(
        "SELECT produto, SUM(CASE WHEN posto_id IS NOT NULL THEN quantidade_l ELSE 0 END) postos_l, "
        "SUM(CASE WHEN instalacao_id IS NOT NULL THEN quantidade_l ELSE 0 END) instalacoes_l, SUM(quantidade_l) total_l FROM reservatorios GROUP BY produto")}
    produtos = []
    for n in NOMES_PRODUTOS:
        a = arm.get(n, {})
        produtos.append(dict(produto=n, **por_prod[n], armazenado_postos_l=round(a.get("postos_l") or 0), armazenado_instalacoes_l=round(a.get("instalacoes_l") or 0),
                             armazenado_total_l=round(a.get("total_l") or 0), vendido_periodo_l=round(vol[n]["vendido_l"]),
                             distribuido_periodo_l=round(vol[n]["distribuido_l"]), recebido_periodo_l=round(vol[n]["recebido_l"]),
                             consumo_medio_diario_l=round(vol[n]["vendido_l"] / max(1, (datetime.strptime(fim, "%Y-%m-%d %H:%M:%S") - datetime.strptime(ini, "%Y-%m-%d %H:%M:%S")).days or 1))))
    total_postos = sum(n_est.values())
    op = n_est.get("Operacional", 0)
    pct_sem = 100 * sem / op if op else 0
    situacao = "Normal" if pct_sem < 5 else ("Atenção" if pct_sem < 12 else "Crítica")
    return dict(
        periodo=dict(desde=iso(ini), ate=iso(fim)), ultima_atualizacao=ultima_atualizacao(),
        postos=dict(total=total_postos, operacionais=op, inoperacionais=n_est.get("Inoperacional", 0), encerrados=n_est.get("Encerrado", 0),
                    sem_combustivel=sem, com_disponibilidade_reduzida=reduzido),
        volumes=dict(disponivel_postos_l=sum(p["armazenado_postos_l"] for p in produtos), armazenado_instalacoes_l=sum(p["armazenado_instalacoes_l"] for p in produtos),
                     armazenado_total_l=sum(p["armazenado_total_l"] for p in produtos), distribuido_periodo_l=sum(p["distribuido_periodo_l"] for p in produtos),
                     vendido_periodo_l=sum(p["vendido_periodo_l"] for p in produtos), recebido_periodo_l=sum(p["recebido_periodo_l"] for p in produtos)),
        produtos=produtos,
        situacao_geral=dict(classificacao=situacao, postos_operacionais_sem_combustivel_pct=round(pct_sem, 1),
                            descricao={"Normal": "Cadeia de abastecimento estável.", "Atenção": "Alguns postos operacionais sem combustível.",
                                       "Crítica": "Rutura generalizada em postos operacionais."}[situacao]),
        simulado=True)


def indicadores_provincias(f: dict | None = None) -> list[dict]:
    f = f or {}
    ini, fim = _periodo(f)
    emp = empresa_canonica(f["empresa"]) if f.get("empresa") else None
    cond, pr = "", []
    if emp:
        cond, pr = " AND p.empresa_id=?", [emp]
    disp = db.consultar(f"SELECT d.* FROM ({SQL_DISP}) d JOIN postos p ON p.id=d.posto_uid WHERE 1=1{cond}", pr)
    postos = db.consultar(f"SELECT p.id, p.provincia, p.estado FROM postos p WHERE 1=1{cond}", pr)
    vend = {r["provincia"]: r["s"] for r in db.consultar(
        "SELECT po.provincia, -SUM(m.delta_l) s FROM movimentos m JOIN postos po ON po.id=m.posto_id "
        f"WHERE m.tipo='Venda' AND m.data_hora>=? AND m.data_hora<=?{cond.replace('p.', 'po.')} GROUP BY 1", [ini, fim] + pr)}
    dist = {r["provincia"]: r["s"] for r in db.consultar(
        "SELECT COALESCE(po.provincia, i.provincia) provincia, SUM(m.delta_l) s FROM movimentos m LEFT JOIN postos po ON po.id=m.posto_id "
        "LEFT JOIN instalacoes i ON i.id=m.instalacao_id WHERE m.tipo='Receção' AND m.posto_id IS NOT NULL AND m.data_hora>=? AND m.data_hora<=? GROUP BY 1", [ini, fim])}
    pops = {r["nome"]: r["populacao_milhoes"] for r in db.consultar("SELECT nome, populacao_milhoes FROM provincias")}
    out = []
    for prov in provincias():
        ps = [x for x in postos if x["provincia"] == prov]
        ds = [d for d in disp if d["provincia"] == prov]
        op_ids = {x["id"] for x in ps if x["estado"] == "Operacional"}
        sem = sum(1 for uid in op_ids if not any(d["disponivel"] for d in ds if d["posto_uid"] == uid))
        row = dict(provincia=prov, postos=len(ps), operacionais=len(op_ids), inoperacionais=sum(1 for x in ps if x["estado"] == "Inoperacional"),
                   encerrados=sum(1 for x in ps if x["estado"] == "Encerrado"), sem_combustivel=sem)
        for n in NOMES_PRODUTOS:
            dn = [d for d in ds if d["produto"] == n and d["estado_posto"] == "Operacional"]
            row[f"com_{norm(n)}"] = sum(1 for d in dn if d["disponivel"])
            row[f"sem_{norm(n)}"] = sum(1 for d in dn if not d["disponivel"])
        cap = sum(d["capacidade_l"] for d in ds)
        row["volume_postos_l"] = round(sum(d["stock_l"] for d in ds))
        row["nivel_medio_pct"] = round(100 * sum(d["stock_l"] for d in ds) / cap, 1) if cap else 0.0
        row["vendido_periodo_l"] = round(vend.get(prov, 0))
        row["recebido_periodo_l"] = round(dist.get(prov, 0))
        pop = pops.get(prov) or 0
        row["postos_por_milhao_hab"] = round(len(ps) / pop, 1) if pop else None
        # necessidade de abastecimento: 0–100 (ruturas de produto + stock baixo + postos parados), ponderada
        n_prod_linhas = max(1, sum(1 for d in ds if d["estado_posto"] == "Operacional"))
        ruturas = sum(1 for d in ds if d["estado_posto"] == "Operacional" and not d["disponivel"]) / n_prod_linhas
        baixos = sum(1 for d in ds if d["disponivel"] and d["capacidade_l"] and d["stock_l"] / d["capacidade_l"] < LIMIAR_BAIXO) / n_prod_linhas
        parados = (row["inoperacionais"] + row["encerrados"]) / max(1, len(ps))
        row["necessidade_abastecimento"] = round(min(100, 100 * (0.5 * ruturas + 0.3 * baixos + 0.2 * parados) * 2.2), 1)
        row["nivel_necessidade"] = "Alta" if row["necessidade_abastecimento"] >= 40 else ("Média" if row["necessidade_abastecimento"] >= 20 else "Baixa")
        row["simulado"] = True
        out.append(row)
    return out


def evolucao_stocks(f: dict | None = None) -> list[dict]:
    """Stock total em reservatórios de postos e de instalações ao fim de cada dia, por produto (soma cumulativa do razão)."""
    f = f or {}
    ini, fim = _periodo(dict(f, desde=f.get("desde") or txt(agora() - timedelta(days=30))))
    rows = db.consultar("SELECT substr(data_hora,1,10) dia, produto, posto_id IS NOT NULL AS em_posto, SUM(delta_l) s FROM movimentos GROUP BY 1,2,3 ORDER BY 1")
    acum, saida = {}, []
    d_ini, d_fim = ini[:10], fim[:10]
    dias = sorted({r["dia"] for r in rows})
    por_dia = {}
    for r in rows:
        por_dia.setdefault(r["dia"], []).append(r)
    for dia in dias:
        for r in por_dia[dia]:
            k = (r["produto"], r["em_posto"])
            acum[k] = acum.get(k, 0) + r["s"]
        if d_ini <= dia <= d_fim:
            for n in NOMES_PRODUTOS:
                saida.append(dict(data=dia, produto=n, stock_postos_l=round(acum.get((n, 1), 0)), stock_instalacoes_l=round(acum.get((n, 0), 0))))
    return saida


def alertas_stock(limite: int = 200) -> list[dict]:
    rows, _ = listar_reservatorios(dict(stock_reduzido="1", proprietario="posto", page_size=limite))
    rows = [r for r in rows if r["estado"] == "Operacional"]
    rows.sort(key=lambda r: r["ocupacao_pct"])
    return rows[:limite]
