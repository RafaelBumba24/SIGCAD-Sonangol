"""Camada de escrita: regras operacionais, CRUD, entregas e simulação de alterações. Todas as regras são aplicadas aqui."""
from __future__ import annotations

import math
import random
from datetime import timedelta

from . import db
from .config import (ESTADOS_BOMBA, ESTADOS_POSTO, ESTADOS_RESERVATORIO, FRACAO_MINIMO, NOMES_PRODUTOS, agora, txt)
from .consultas import ErroValidacao, produto_canonico, provincia_canonica, municipio_canonico


def auditar(c, utilizador, entidade, eid, acao, detalhe=""):
    c.execute("INSERT INTO auditoria(data_hora,utilizador,entidade,entidade_id,acao,detalhe) VALUES(?,?,?,?,?,?)",
              (txt(agora()), utilizador or "sistema", entidade, str(eid), acao, str(detalhe)[:500]))


def _tocar(c, quando: str):
    db.cfg_set("ultima_atualizacao", quando, c)


def _tanque(c, rid: int):
    r = c.execute("SELECT * FROM reservatorios WHERE id=?", (rid,)).fetchone()
    if not r:
        raise ErroValidacao("Reservatório inexistente.", "reservatorio")
    return r


def aplicar_movimento(c, rid: int, tipo: str, quantidade: float, quando=None, entrega_id=None, obs="", utilizador=None) -> float:
    """Regista um movimento e atualiza o stock. Receção soma; Venda/Distribuição subtraem; Ajuste define o delta (±)."""
    t = _tanque(c, rid)
    q = float(quantidade)
    if tipo in ("Receção", "Venda", "Distribuição") and q <= 0:
        raise ErroValidacao("A quantidade do movimento deve ser positiva.", "quantidade")
    if t["estado"] != "Operacional" and tipo in ("Receção", "Venda", "Distribuição"):
        raise ErroValidacao(f"O reservatório está «{t['estado']}» e não pode movimentar produto.", "reservatorio")
    delta = q if tipo == "Receção" else (-q if tipo in ("Venda", "Distribuição") else q)
    novo = round(t["quantidade_l"] + delta, 3)
    if novo < -0.001:
        raise ErroValidacao(f"Stock insuficiente: existem {t['quantidade_l']:.0f} L e o movimento pede {abs(delta):.0f} L.", "quantidade")
    if novo > t["capacidade_l"] + 0.001:
        raise ErroValidacao(f"Excede a capacidade do reservatório ({t['capacidade_l']:.0f} L): livre {t['capacidade_l'] - t['quantidade_l']:.0f} L.", "quantidade")
    novo = max(0.0, novo)
    quando = quando or txt(agora())
    c.execute("UPDATE reservatorios SET quantidade_l=?, atualizado_em=? WHERE id=?", (novo, quando, rid))
    c.execute("INSERT INTO movimentos(data_hora,tipo,reservatorio_id,posto_id,instalacao_id,produto,delta_l,stock_apos_l,entrega_id,observacao)"
              " VALUES(?,?,?,?,?,?,?,?,?,?)", (quando, tipo, rid, t["posto_id"], t["instalacao_id"], t["produto"], delta, novo, entrega_id, obs))
    if t["posto_id"]:
        c.execute("UPDATE postos SET atualizado_em=? WHERE id=?", (quando, t["posto_id"]))
    _tocar(c, quando)
    return novo


def definir_stock(c, rid: int, nova_quantidade: float, obs="Ajuste manual", utilizador=None):
    t = _tanque(c, rid)
    nq = float(nova_quantidade)
    if nq < 0 or nq > t["capacidade_l"] + 0.001:
        raise ErroValidacao(f"A quantidade deve estar entre 0 e a capacidade ({t['capacidade_l']:.0f} L).", "quantidade")
    d = round(nq - t["quantidade_l"], 3)
    if d == 0:
        return nq
    r = aplicar_movimento(c, rid, "Ajuste", d, obs=obs)
    auditar(c, utilizador, "reservatorio", rid, "ajuste_stock", f"{t['quantidade_l']:.0f} → {nq:.0f} L")
    return r


# ---------------------------------------------------------------- CRUD
def _validar_posto(d: dict):
    if not str(d.get("nome", "")).strip():
        raise ErroValidacao("Indique o nome do posto.", "nome")
    prov = provincia_canonica(d.get("provincia"))
    mun = municipio_canonico(d.get("municipio"), prov)
    for k, lim in (("lat", 90), ("lon", 180)):
        if d.get(k) not in (None, "") and abs(float(d[k])) > lim:
            raise ErroValidacao(f"{k} fora do intervalo.", k)
    if d.get("estado") and d["estado"] not in ESTADOS_POSTO:
        raise ErroValidacao("Estado do posto inválido.", "estado")
    return prov, mun


def criar_posto(d: dict, utilizador=None) -> int:
    prov, mun = _validar_posto(d)
    with db.tx() as c:
        emp = c.execute("SELECT id, codigo FROM empresas WHERE id=?", (d["empresa_id"],)).fetchone()
        if not emp:
            raise ErroValidacao("Empresa inexistente.", "empresa")
        cod = str(d.get("codigo") or "").strip()
        if not cod:
            pc = c.execute("SELECT codigo FROM provincias WHERE nome=?", (prov,)).fetchone()[0]
            n = c.execute("SELECT COUNT(*) FROM postos WHERE provincia=?", (prov,)).fetchone()[0] + 1
            cod = f"{emp['codigo']}-{pc}-{n:04d}"
            while c.execute("SELECT 1 FROM postos WHERE codigo=?", (cod,)).fetchone():
                n += 1
                cod = f"{emp['codigo']}-{pc}-{n:04d}"
        if c.execute("SELECT 1 FROM postos WHERE codigo=?", (cod,)).fetchone():
            raise ErroValidacao(f"Já existe um posto com o código {cod}.", "codigo")
        q = txt(agora())
        cur = c.execute("INSERT INTO postos(codigo,nome,empresa_id,provincia,municipio,lat,lon,tipo,servicos,estado,motivo,criado_em,atualizado_em,simulado)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (cod, d["nome"].strip(), emp["id"], prov, mun, d.get("lat") or None, d.get("lon") or None, d.get("tipo") or "Urbano",
                         "|".join(d["servicos"]) if isinstance(d.get("servicos"), list) else (d.get("servicos") or ""),
                         d.get("estado") or "Operacional", d.get("motivo") or "", q, q, int(d.get("simulado", 1))))
        pid = cur.lastrowid
        for pr in (d.get("produtos") or []):
            c.execute("INSERT OR IGNORE INTO posto_produtos(posto_id,produto) VALUES(?,?)", (pid, produto_canonico(pr)))
        auditar(c, utilizador, "posto", cod, "criar", d["nome"])
        _tocar(c, q)
        return pid


def atualizar_posto(pid: int, d: dict, utilizador=None):
    with db.tx() as c:
        a = c.execute("SELECT * FROM postos WHERE id=?", (pid,)).fetchone()
        if not a:
            raise ErroValidacao("Posto inexistente.", "posto")
        novo = dict(a)
        novo.update({k: v for k, v in d.items() if k in ("nome", "provincia", "municipio", "lat", "lon", "tipo", "estado", "motivo", "empresa_id")})
        prov, mun = _validar_posto(novo)
        if "servicos" in d:
            novo["servicos"] = "|".join(d["servicos"]) if isinstance(d["servicos"], list) else d["servicos"]
        q = txt(agora())
        c.execute("UPDATE postos SET nome=?,empresa_id=?,provincia=?,municipio=?,lat=?,lon=?,tipo=?,servicos=?,estado=?,motivo=?,atualizado_em=? WHERE id=?",
                  (novo["nome"], novo["empresa_id"], prov, mun, novo["lat"], novo["lon"], novo["tipo"], novo["servicos"], novo["estado"],
                   novo["motivo"] if novo["estado"] != "Operacional" else "", q, pid))
        if "produtos" in d:
            novos = {produto_canonico(x) for x in d["produtos"]}
            for pr in set(NOMES_PRODUTOS) - novos:
                if c.execute("SELECT 1 FROM reservatorios WHERE posto_id=? AND produto=? AND quantidade_l>0", (pid, pr)).fetchone():
                    raise ErroValidacao(f"Não pode deixar de comercializar {pr}: o posto ainda tem stock desse produto (ajuste o stock a 0 primeiro).", "produtos")
                c.execute("DELETE FROM posto_produtos WHERE posto_id=? AND produto=?", (pid, pr))
                c.execute("DELETE FROM reservatorios WHERE posto_id=? AND produto=?", (pid, pr))
                c.execute("DELETE FROM bombas WHERE posto_id=? AND produto=?", (pid, pr))
            for pr in novos:
                c.execute("INSERT OR IGNORE INTO posto_produtos(posto_id,produto) VALUES(?,?)", (pid, pr))
        auditar(c, utilizador, "posto", a["codigo"], "editar", {k: v for k, v in d.items() if k != "produtos"})
        _tocar(c, q)


def eliminar_posto(pid: int, utilizador=None):
    with db.tx() as c:
        a = c.execute("SELECT codigo FROM postos WHERE id=?", (pid,)).fetchone()
        if not a:
            raise ErroValidacao("Posto inexistente.", "posto")
        c.execute("DELETE FROM movimentos WHERE posto_id=?", (pid,))
        c.execute("UPDATE entregas SET destino_posto_id=NULL, destino_reservatorio_id=NULL WHERE destino_posto_id=?", (pid,))
        c.execute("DELETE FROM postos WHERE id=?", (pid,))
        auditar(c, utilizador, "posto", a["codigo"], "eliminar")
        _tocar(c, txt(agora()))


def criar_reservatorio(posto_id: int | None, instalacao_id: int | None, produto: str, capacidade_l: float, quantidade_l: float = 0.0,
                       codigo: str | None = None, minimo_l: float | None = None, utilizador=None) -> int:
    produto = produto_canonico(produto)
    if capacidade_l <= 0:
        raise ErroValidacao("A capacidade deve ser positiva.", "capacidade_l")
    if not 0 <= quantidade_l <= capacidade_l:
        raise ErroValidacao("A quantidade atual deve estar entre 0 e a capacidade.", "quantidade_l")
    with db.tx() as c:
        if posto_id:
            if not c.execute("SELECT 1 FROM posto_produtos WHERE posto_id=? AND produto=?", (posto_id, produto)).fetchone():
                raise ErroValidacao(f"O posto não comercializa {produto}: adicione primeiro o produto ao posto.", "produto")
        n = c.execute("SELECT COUNT(*) FROM reservatorios WHERE posto_id IS ? AND instalacao_id IS ?", (posto_id, instalacao_id)).fetchone()[0] + 1
        cod = codigo or f"R{n:02d}"
        while c.execute("SELECT 1 FROM reservatorios WHERE codigo=? AND posto_id IS ? AND instalacao_id IS ?", (cod, posto_id, instalacao_id)).fetchone():
            n += 1
            cod = f"R{n:02d}"
        q = txt(agora())
        rid = c.execute("INSERT INTO reservatorios(codigo,posto_id,instalacao_id,produto,capacidade_l,quantidade_l,minimo_operacional_l,estado,atualizado_em)"
                        " VALUES(?,?,?,?,?,?,?,?,?)", (cod, posto_id, instalacao_id, produto, capacidade_l, 0.0,
                                                         minimo_l if minimo_l is not None else round(capacidade_l * FRACAO_MINIMO), "Operacional", q)).lastrowid
        c.execute("INSERT INTO movimentos(data_hora,tipo,reservatorio_id,posto_id,instalacao_id,produto,delta_l,stock_apos_l,observacao)"
                  " VALUES(?,?,?,?,?,?,?,?,?)", (q, "Saldo inicial", rid, posto_id, instalacao_id, produto, 0.0, 0.0, "Reservatório criado"))
        if quantidade_l > 0:
            aplicar_movimento(c, rid, "Ajuste", quantidade_l, q, obs="Quantidade inicial")
        auditar(c, utilizador, "reservatorio", rid, "criar", f"{produto} {capacidade_l:.0f} L")
        return rid


def atualizar_reservatorio(rid: int, capacidade_l=None, minimo_l=None, estado=None, utilizador=None):
    with db.tx() as c:
        t = _tanque(c, rid)
        cap = float(capacidade_l) if capacidade_l is not None else t["capacidade_l"]
        if cap < t["quantidade_l"]:
            raise ErroValidacao(f"A capacidade ({cap:.0f} L) não pode ser inferior ao stock atual ({t['quantidade_l']:.0f} L).", "capacidade_l")
        mn = float(minimo_l) if minimo_l is not None else t["minimo_operacional_l"]
        if mn < 0 or mn > cap:
            raise ErroValidacao("A quantidade mínima operacional deve estar entre 0 e a capacidade.", "minimo_l")
        est = estado or t["estado"]
        if est not in ESTADOS_RESERVATORIO:
            raise ErroValidacao("Estado do reservatório inválido.", "estado")
        q = txt(agora())
        c.execute("UPDATE reservatorios SET capacidade_l=?, minimo_operacional_l=?, estado=?, atualizado_em=? WHERE id=?", (cap, mn, est, q, rid))
        if t["posto_id"]:
            c.execute("UPDATE postos SET atualizado_em=? WHERE id=?", (q, t["posto_id"]))
        auditar(c, utilizador, "reservatorio", rid, "editar", f"cap={cap:.0f} min={mn:.0f} estado={est}")
        _tocar(c, q)


def eliminar_reservatorio(rid: int, utilizador=None):
    with db.tx() as c:
        t = _tanque(c, rid)
        if t["quantidade_l"] > 0:
            raise ErroValidacao("Só pode eliminar reservatórios vazios (ajuste o stock a 0 primeiro).", "reservatorio")
        c.execute("UPDATE entregas SET destino_reservatorio_id=NULL WHERE destino_reservatorio_id=?", (rid,))
        c.execute("DELETE FROM reservatorios WHERE id=?", (rid,))
        auditar(c, utilizador, "reservatorio", rid, "eliminar")
        _tocar(c, txt(agora()))


def criar_bomba(posto_id: int, produto: str, estado="Operacional", utilizador=None) -> int:
    produto = produto_canonico(produto)
    with db.tx() as c:
        if not c.execute("SELECT 1 FROM posto_produtos WHERE posto_id=? AND produto=?", (posto_id, produto)).fetchone():
            raise ErroValidacao(f"O posto não comercializa {produto}.", "produto")
        n = c.execute("SELECT COUNT(*) FROM bombas WHERE posto_id=?", (posto_id,)).fetchone()[0] + 1
        q = txt(agora())
        bid = c.execute("INSERT INTO bombas(codigo,posto_id,produto,estado,atualizado_em) VALUES(?,?,?,?,?)", (f"B{n:02d}", posto_id, produto, estado, q)).lastrowid
        auditar(c, utilizador, "bomba", bid, "criar", produto)
        _tocar(c, q)
        return bid


def estado_bomba(bid: int, estado: str, utilizador=None):
    if estado not in ESTADOS_BOMBA:
        raise ErroValidacao("Estado da bomba inválido.", "estado")
    with db.tx() as c:
        b = c.execute("SELECT posto_id FROM bombas WHERE id=?", (bid,)).fetchone()
        if not b:
            raise ErroValidacao("Bomba inexistente.", "bomba")
        q = txt(agora())
        c.execute("UPDATE bombas SET estado=?, atualizado_em=? WHERE id=?", (estado, q, bid))
        c.execute("UPDATE postos SET atualizado_em=? WHERE id=?", (q, b["posto_id"]))
        auditar(c, utilizador, "bomba", bid, "estado", estado)
        _tocar(c, q)


def eliminar_bomba(bid: int, utilizador=None):
    with db.tx() as c:
        c.execute("DELETE FROM bombas WHERE id=?", (bid,))
        auditar(c, utilizador, "bomba", bid, "eliminar")
        _tocar(c, txt(agora()))


def definir_preco(produto: str, preco: float, utilizador=None):
    produto = produto_canonico(produto)
    if preco <= 0:
        raise ErroValidacao("O preço deve ser positivo.", "preco")
    with db.tx() as c:
        q = txt(agora())
        c.execute("UPDATE produtos SET preco=?, preco_desde=? WHERE nome=?", (preco, q[:10], produto))
        auditar(c, utilizador, "produto", produto, "preco", preco)
        _tocar(c, q)


# ---------------------------------------------------------------- entregas
def _prox_codigo_entrega(c) -> str:
    n = (c.execute("SELECT COALESCE(MAX(id),0) FROM entregas").fetchone()[0] or 0) + 1
    return f"ENT-{agora():%Y%m%d}-{n:05d}"


def criar_entrega(origem_instalacao_id: int, destino_reservatorio_id: int, quantidade_l: float, saida=None, horas_viagem: float = 6.0,
                  veiculo: str = "", utilizador=None) -> int:
    with db.tx() as c:
        d = _tanque(c, destino_reservatorio_id)
        o = c.execute("SELECT * FROM reservatorios WHERE instalacao_id=? AND produto=?", (origem_instalacao_id, d["produto"])).fetchone()
        if not o:
            raise ErroValidacao("A instalação de origem não tem reservatório deste produto.", "origem")
        if quantidade_l <= 0:
            raise ErroValidacao("A quantidade deve ser positiva.", "quantidade_l")
        if quantidade_l > d["capacidade_l"] - d["quantidade_l"] + 0.001:
            raise ErroValidacao(f"Excede o espaço livre do destino ({d['capacidade_l'] - d['quantidade_l']:.0f} L).", "quantidade_l")
        from datetime import datetime
        ts = datetime.strptime(saida, "%Y-%m-%d %H:%M:%S") if isinstance(saida, str) else (saida or agora())
        eid = c.execute("INSERT INTO entregas(codigo,produto,quantidade_l,origem_instalacao_id,destino_posto_id,destino_instalacao_id,destino_reservatorio_id,"
                        "veiculo,estado,data_saida,data_prevista_chegada,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (_prox_codigo_entrega(c), d["produto"], quantidade_l, origem_instalacao_id, d["posto_id"], d["instalacao_id"], destino_reservatorio_id,
                         veiculo or "LD-00-00-AA", "Planeada", txt(ts), txt(ts + timedelta(hours=horas_viagem)), txt(agora()), txt(agora()))).lastrowid
        auditar(c, utilizador, "entrega", eid, "criar", f"{quantidade_l:.0f} L {d['produto']}")
        return eid


def avancar_entrega(eid: int, novo_estado: str, utilizador=None):
    """Planeada → Em trânsito (debita a origem) → Entregue (credita o destino); Cancelada devolve a carga se já saiu."""
    with db.tx() as c:
        e = c.execute("SELECT * FROM entregas WHERE id=?", (eid,)).fetchone()
        if not e:
            raise ErroValidacao("Entrega inexistente.", "entrega")
        q = txt(agora())
        o = c.execute("SELECT * FROM reservatorios WHERE instalacao_id=? AND produto=?", (e["origem_instalacao_id"], e["produto"])).fetchone() \
            if e["origem_instalacao_id"] else None
        if novo_estado == "Em trânsito" and e["estado"] == "Planeada":
            if o:
                aplicar_movimento(c, o["id"], "Distribuição", e["quantidade_l"], q, eid, f"Saída para {e['codigo']}")
            c.execute("UPDATE entregas SET estado='Em trânsito', data_saida=?, atualizado_em=? WHERE id=?", (q, q, eid))
        elif novo_estado == "Entregue" and e["estado"] in ("Planeada", "Em trânsito"):
            if e["estado"] == "Planeada" and o:
                aplicar_movimento(c, o["id"], "Distribuição", e["quantidade_l"], q, eid, f"Saída para {e['codigo']}")
            aplicar_movimento(c, e["destino_reservatorio_id"], "Receção", e["quantidade_l"], q, eid, f"Entrega {e['codigo']}")
            c.execute("UPDATE entregas SET estado='Entregue', data_chegada=?, atualizado_em=? WHERE id=?", (q, q, eid))
        elif novo_estado == "Cancelada" and e["estado"] in ("Planeada", "Em trânsito"):
            if e["estado"] == "Em trânsito" and o:
                aplicar_movimento(c, o["id"], "Ajuste", e["quantidade_l"], q, eid, f"Devolução {e['codigo']}")
            c.execute("UPDATE entregas SET estado='Cancelada', atualizado_em=? WHERE id=?", (q, eid))
        else:
            raise ErroValidacao(f"Transição inválida: {e['estado']} → {novo_estado}.", "estado")
        auditar(c, utilizador, "entrega", e["codigo"], "estado", novo_estado)


# ---------------------------------------------------------------- simulação de alterações
def simular_passo(horas: int = 24, semente=None, utilizador="simulador") -> dict:
    """Avança a simulação: vendas nos postos operacionais, chegada das entregas em trânsito e novos pedidos de reabastecimento."""
    rnd = random.Random(semente)
    r = dict(vendas_l=0.0, entregas_recebidas=0, entregas_criadas=0)
    with db.tx() as c:
        agora_ = agora()
        q = txt(agora_)
        for e in c.execute("SELECT * FROM entregas WHERE estado='Em trânsito' AND data_prevista_chegada<=?", (q,)).fetchall():
            d = c.execute("SELECT * FROM reservatorios WHERE id=?", (e["destino_reservatorio_id"],)).fetchone()
            if d and d["estado"] == "Operacional":
                vol = min(e["quantidade_l"], d["capacidade_l"] - d["quantidade_l"])
                if vol > 0:
                    aplicar_movimento(c, d["id"], "Receção", vol, q, e["id"], f"Entrega {e['codigo']}")
                    c.execute("UPDATE entregas SET estado='Entregue', quantidade_l=?, data_chegada=?, atualizado_em=? WHERE id=?", (vol, q, q, e["id"]))
                    r["entregas_recebidas"] += 1
        for e in c.execute("SELECT * FROM entregas WHERE estado='Planeada' AND data_saida<=?", (q,)).fetchall():
            o = c.execute("SELECT * FROM reservatorios WHERE instalacao_id=? AND produto=?", (e["origem_instalacao_id"], e["produto"])).fetchone()
            if o and o["quantidade_l"] >= e["quantidade_l"]:
                aplicar_movimento(c, o["id"], "Distribuição", e["quantidade_l"], q, e["id"], f"Saída para {e['codigo']}")
                c.execute("UPDATE entregas SET estado='Em trânsito', atualizado_em=? WHERE id=?", (q, e["id"]))
        taxa = {"Gasolina": 0.105, "Gasóleo": 0.115, "GPL": 0.045, "Petróleo iluminante": 0.04, "Jet A1": 0.06}
        for t in c.execute("SELECT r.*, p.estado AS pe FROM reservatorios r JOIN postos p ON p.id=r.posto_id WHERE r.posto_id IS NOT NULL").fetchall():
            if t["pe"] != "Operacional" or t["estado"] != "Operacional" or t["quantidade_l"] <= 0:
                continue
            if not c.execute("SELECT 1 FROM bombas WHERE posto_id=? AND produto=? AND estado='Operacional'", (t["posto_id"], t["produto"])).fetchone():
                continue
            v = min(t["quantidade_l"], round(t["capacidade_l"] * taxa[t["produto"]] * horas / 24 * rnd.uniform(0.6, 1.4) / 10) * 10)
            if v > 0:
                aplicar_movimento(c, t["id"], "Venda", v, q, None, "Vendas (simulação)")
                r["vendas_l"] += v
            t2 = c.execute("SELECT quantidade_l FROM reservatorios WHERE id=?", (t["id"],)).fetchone()
            if t2["quantidade_l"] < 0.30 * t["capacidade_l"] and not c.execute(
                    "SELECT 1 FROM entregas WHERE destino_reservatorio_id=? AND estado IN ('Planeada','Em trânsito')", (t["id"],)).fetchone():
                vol = math.floor((0.92 * t["capacidade_l"] - t2["quantidade_l"]) / 1000) * 1000
                cd = c.execute("SELECT i.id FROM instalacoes i JOIN postos p ON p.provincia=i.provincia WHERE p.id=? AND i.tipo='Centro de distribuição'",
                               (t["posto_id"],)).fetchone()
                if vol >= 2000 and cd:
                    c.execute("INSERT INTO entregas(codigo,produto,quantidade_l,origem_instalacao_id,destino_posto_id,destino_reservatorio_id,veiculo,estado,"
                              "data_saida,data_prevista_chegada,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                              (_prox_codigo_entrega(c), t["produto"], vol, cd["id"], t["posto_id"], t["id"], f"LD-{rnd.randint(10,99)}-{rnd.randint(10,99)}-AB",
                               "Planeada", txt(agora_ + timedelta(hours=2)), txt(agora_ + timedelta(hours=2 + rnd.randint(4, 30))), q, q))
                    r["entregas_criadas"] += 1
        _tocar(c, q)
    r["vendas_l"] = round(r["vendas_l"])
    return r


def renovar_leituras(utilizador="simulador") -> dict:
    """Simula o «batimento» dos sistemas dos postos: todos reportam agora (datas de atualização = agora). Sem isto, os dados envelhecem e o
    SIG-CAD (validade de 6 h para dados de API) passa a mostrar «Sem confirmação atualizada»."""
    with db.tx() as c:
        q = txt(agora())
        n = {t: c.execute(f"UPDATE {t} SET atualizado_em=?", (q,)).rowcount for t in ("postos", "reservatorios", "bombas", "instalacoes")}
        _tocar(c, q)
    return n


def simular_ruptura(posto_id: int, produto: str, utilizador="simulador"):
    """Esgota o produto num posto (venda do stock utilizável até ao mínimo operacional ou zero)."""
    produto = produto_canonico(produto)
    with db.tx() as c:
        ts = c.execute("SELECT id FROM reservatorios WHERE posto_id=? AND produto=?", (posto_id, produto)).fetchall()
        if not ts:
            raise ErroValidacao("O posto não comercializa este produto.", "produto")
        for t in ts:
            tq = c.execute("SELECT quantidade_l FROM reservatorios WHERE id=?", (t["id"],)).fetchone()[0]
            if tq > 0:
                aplicar_movimento(c, t["id"], "Venda", tq, None, None, "Ruptura simulada")
        auditar(c, utilizador, "posto", posto_id, "simular_ruptura", produto)


def simular_indisponibilidade(posto_id: int, estado: str = "Inoperacional", motivo: str = "Avaria de bombas/equipamento", utilizador="simulador"):
    atualizar_posto(posto_id, dict(estado=estado, motivo=motivo), utilizador)


def restaurar_posto(posto_id: int, utilizador="simulador"):
    atualizar_posto(posto_id, dict(estado="Operacional", motivo=""), utilizador)
    with db.tx() as c:
        c.execute("UPDATE bombas SET estado='Operacional', atualizado_em=? WHERE posto_id=?", (txt(agora()), posto_id))


# ---------------------------------------------------------------- verificação de coerência
def verificar_coerencia() -> list[str]:
    """Devolve a lista de violações das regras operacionais (vazia = tudo coerente)."""
    erros = []
    q = db.consultar
    for r in q("SELECT id,codigo FROM reservatorios WHERE quantidade_l<0 OR quantidade_l>capacidade_l+0.001"):
        erros.append(f"Reservatório {r['id']}: stock fora de [0, capacidade].")
    for r in q("SELECT r.id FROM reservatorios r WHERE ABS(r.quantidade_l - COALESCE((SELECT SUM(delta_l) FROM movimentos m WHERE m.reservatorio_id=r.id),0))>0.01"):
        erros.append(f"Reservatório {r['id']}: stock ≠ soma dos movimentos.")
    for r in q("SELECT r.id FROM reservatorios r JOIN postos p ON p.id=r.posto_id LEFT JOIN posto_produtos pp ON pp.posto_id=p.id AND pp.produto=r.produto WHERE pp.posto_id IS NULL"):
        erros.append(f"Reservatório {r['id']}: produto não comercializado pelo posto.")
    for r in q("SELECT b.id FROM bombas b LEFT JOIN posto_produtos pp ON pp.posto_id=b.posto_id AND pp.produto=b.produto WHERE pp.posto_id IS NULL"):
        erros.append(f"Bomba {r['id']}: produto não comercializado pelo posto.")
    for r in q("SELECT id FROM entregas WHERE estado='Entregue' AND data_chegada IS NULL"):
        erros.append(f"Entrega {r['id']} entregue sem data de chegada.")
    return erros
