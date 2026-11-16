"""Geração dos dados SIMULADOS (mas operacionalmente coerentes) da plataforma SONANGOL.

Princípios (todos verificados por `servicos.verificar_coerencia`):
  • stock nunca negativo nem acima da capacidade do reservatório;
  • stock de cada reservatório = soma dos seus movimentos (razão contabilística: saldo inicial + receções − vendas/distribuição ± ajustes);
  • um posto que não comercializa um produto não tem reservatórios nem bombas desse produto (disponibilidade 0);
  • entregas «Entregue» creditaram o destino; «Em trânsito» já debitaram a origem; «Planeada» ainda não movimentou stock.
Geografia real (21 províncias, 326 municípios, com população e coordenadas); postos distribuídos pela população."""
from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta

from . import db
from .config import (FRACAO_MINIMO, GEO_JSON, PRODUTOS, agora, txt)

CODIGOS_PROV = {"Luanda": "LDA", "Icolo e Bengo": "IEB", "Bengo": "BGO", "Benguela": "BGU", "Bié": "BIE", "Cabinda": "CAB",
                "Cuando": "CDO", "Cubango": "CBG", "Cuanza Norte": "CNO", "Cuanza Sul": "CSU", "Cunene": "CNN", "Huambo": "HUA",
                "Huíla": "HUI", "Lunda Norte": "LNO", "Lunda Sul": "LSU", "Malanje": "MAL", "Moxico": "MOX",
                "Moxico Leste": "MXL", "Namibe": "NAM", "Uíge": "UIG", "Zaire": "ZAI"}

EMPRESAS = [  # (código, nome, tipo)
    ("SD", "Sonangol Distribuidora", "Distribuidora"),
    ("PUM", "Pumangol", "Distribuidora"),
    ("RPS", "Rede Parceira SONANGOL", "Operadora"),
    ("SREF", "Sonangol Refinação", "Refinadora"),
    ("SLOG", "Sonangol Logística", "Logística"),
]
PESO_EMPRESA = [("SD", 0.60), ("PUM", 0.25), ("RPS", 0.15)]

# Instalações nacionais (coordenadas aproximadas; entidades e estados ilustrativos)
REFINARIAS = [("REF-LDA", "Refinaria de Luanda", "Luanda", "Cacuaco", -8.775, 13.372, "Operacional"),
              ("REF-CAB", "Refinaria de Cabinda", "Cabinda", "Cabinda", -5.547, 12.195, "Operacional"),
              ("REF-LOB", "Refinaria do Lobito", "Benguela", "Lobito", -12.348, 13.575, "Em construção")]
TERMINAIS = [("TRM-TOBD", "Terminal Oceânico da Barra do Dande", "Bengo", "Dande", -8.470, 13.355),
             ("TRM-LDA", "Terminal de Luanda (Porto)", "Luanda", "Luanda", -8.790, 13.245),
             ("TRM-CAB", "Terminal de Cabinda", "Cabinda", "Cabinda", -5.562, 12.188),
             ("TRM-ZAI", "Terminal do Soyo", "Zaire", "Soyo", -6.133, 12.352),
             ("TRM-CSU", "Terminal do Sumbe", "Cuanza Sul", "Sumbe", -11.205, 13.843),
             ("TRM-LOB", "Terminal do Lobito", "Benguela", "Lobito", -12.343, 13.548),
             ("TRM-NAM", "Terminal de Moçâmedes", "Namibe", "Moçâmedes", -15.196, 12.148)]
BASES = ["Malanje", "Huambo", "Huíla", "Lunda Sul", "Moxico", "Cubango", "Uíge", "Bié"]
SERVICOS = ["Loja de conveniência", "Lavagem", "Restaurante", "Caixa multibanco", "Oficina", "Troca de óleo",
            "Ar para pneus", "Casa de banho", "Estacionamento de camiões", "Venda de botijas GPL"]
TAGS = ["Centro", "Norte", "Sul", "Nascente", "Poente", "Mercado", "Rotunda", "Entrada", "Saída", "Bairro Novo", "Cruzamento", "Avenida",
        "Circular", "Terminal", "Praça", "Ponte", "Hospital", "Escola", "Estação", "Zona Industrial", "Estrada Nacional", "Rio", "Colina", "Jardim",
        "Alfa", "Beta", "Gama", "Delta", "Épsilon", "Zeta", "Eta", "Teta", "Iota", "Capa", "Lambda", "Sigma", "Ómega", "Cidade Alta", "Cidade Baixa", "Marginal"]
MOTIVOS_INOP = ["Falta de abastecimento regular", "Avaria de bombas/equipamento", "Licenciamento/fiscalização pendente"]


def _km(a, b) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    x = math.sin((la2 - la1) * p / 2) ** 2 + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


def _repartir(total: int, pesos: dict, minimo: int = 3) -> dict:
    """Método do maior resto: reparte `total` pelos pesos, com um mínimo por chave."""
    s = sum(pesos.values())
    base = {k: max(minimo, int(total * v / s)) for k, v in pesos.items()}
    dif = total - sum(base.values())
    resto = sorted(pesos, key=lambda k: -(total * pesos[k] / s - int(total * pesos[k] / s)))
    i = 0
    while dif != 0 and resto:
        k = resto[i % len(resto)]
        if dif > 0:
            base[k] += 1
            dif -= 1
        elif base[k] > minimo:
            base[k] -= 1
            dif += 1
        i += 1
        if i > 100000:
            break
    return base


def _reset():
    c = db.ligar()
    try:
        c.execute("PRAGMA foreign_keys=OFF")
        nomes = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        guardar = {"api_chaves", "api_log"}
        for n in nomes:
            if n not in guardar:
                c.execute(f'DROP TABLE IF EXISTS "{n}"')
        c.execute("PRAGMA foreign_keys=ON")
    finally:
        c.close()
    db.iniciar()


def gerar(n_postos: int = 500, dias: int = 30, semente: int = 2025, progresso=None) -> dict:
    """Recria a base de dados de demonstração. Devolve um resumo."""
    rnd = random.Random(semente)
    log = progresso or (lambda m: None)
    _reset()
    geo = json.load(open(GEO_JSON, encoding="utf-8"))
    agora_ = agora()
    inicio = (agora_ - timedelta(days=dias)).replace(hour=0, minute=0, second=0)

    with db.tx() as c:
        # ---------- geografia ----------
        for i, p in enumerate(geo["provincias"], 1):
            c.execute("INSERT INTO provincias(id,codigo,nome,sede,lat,lon,populacao_milhoes) VALUES(?,?,?,?,?,?,?)",
                      (i, CODIGOS_PROV[p["nome"]], p["nome"], p["sede"], p["lat"], p["lon"], p["pop"]))
        for i, m in enumerate(geo["municipios"], 1):
            c.execute("INSERT INTO municipios(id,provincia,nome,lat,lon,area_km2,populacao,capital) VALUES(?,?,?,?,?,?,?,?)",
                      (i, m["provincia"], m["nome"], m["lat"], m["lon"], m["area_km2"], m["pop"], int(m["capital"])))
        for n, d in PRODUTOS.items():
            c.execute("INSERT INTO produtos(nome,categoria,unidade,unidade_preco,preco,preco_desde) VALUES(?,?,?,?,?,?)",
                      (n, d["categoria"], d["unidade"], d["unidade_preco"], d["preco"], "2025-07-04"))
        emp_id = {}
        for i, (cod, nome, tipo) in enumerate(EMPRESAS, 1):
            c.execute("INSERT INTO empresas(id,codigo,nome,tipo) VALUES(?,?,?,?)", (i, cod, nome, tipo))
            emp_id[cod] = i
        log("geografia e catálogo")

        # ---------- instalações ----------
        inst = []     # dicts
        def nova_inst(cod, nome, tipo, emp, prov, mun, lat, lon, estado="Operacional"):
            iid = len(inst) + 1
            inst.append(dict(id=iid, codigo=cod, nome=nome, tipo=tipo, prov=prov, lat=lat, lon=lon, estado=estado))
            c.execute("INSERT INTO instalacoes(id,codigo,nome,tipo,empresa_id,provincia,municipio,lat,lon,estado,criado_em,atualizado_em)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (iid, cod, nome, tipo, emp_id[emp], prov, mun, lat, lon, estado,
                                                             txt(inicio), txt(agora_)))
            return iid
        for cod, nome, prov, mun, la, lo, est in REFINARIAS:
            nova_inst(cod, nome, "Refinaria", "SREF", prov, mun, la, lo, est)
        terminais = []
        for cod, nome, prov, mun, la, lo in TERMINAIS:
            terminais.append(nova_inst(cod, nome, "Terminal de armazenamento", "SLOG", prov, mun, la, lo))
        pmap = {p["nome"]: p for p in geo["provincias"]}
        centro = {}
        for p in geo["provincias"]:
            n = p["nome"]
            centro[n] = nova_inst(f"CD-{CODIGOS_PROV[n]}", f"Centro de Distribuição de {p['sede']}", "Centro de distribuição", "SLOG",
                                  n, p["sede"], round(p["lat"] + 0.02, 4), round(p["lon"] + 0.02, 4))
        for n in BASES:
            p = pmap[n]
            nova_inst(f"BL-{CODIGOS_PROV[n]}", f"Base Logística de {p['sede']}", "Base logística", "SLOG", n, p["sede"],
                      round(p["lat"] - 0.03, 4), round(p["lon"] - 0.02, 4))
        I = {i["id"]: i for i in inst}
        # terminal mais próximo de cada província
        term_de = {}
        for n, p in pmap.items():
            term_de[n] = min(terminais, key=lambda t: _km((p["lat"], p["lon"]), (I[t]["lat"], I[t]["lon"])))

        # ---------- postos ----------
        quota = _repartir(n_postos, geo["peso_postos"], minimo=3)
        muns_por_prov = {}
        for m in geo["municipios"]:
            muns_por_prov.setdefault(m["provincia"], []).append(m)
        elet = {"Luanda": .69, "Cunene": .10}
        postos = []
        seq_prov = {}
        seq_mun = {}
        for prov, q in quota.items():
            ms = muns_por_prov[prov]
            pesos = [max(m["pop"], 1000) ** 0.9 for m in ms]
            for _ in range(q):
                m = rnd.choices(ms, weights=pesos)[0]
                seq_prov[prov] = seq_prov.get(prov, 0) + 1
                seq_mun[(prov, m["nome"])] = seq_mun.get((prov, m["nome"]), 0) + 1
                r_km = min(14.0, 0.45 * math.sqrt(m["area_km2"] / math.pi))
                ang, dist = rnd.uniform(0, 2 * math.pi), r_km * math.sqrt(rnd.random())
                lat = m["lat"] + dist * math.cos(ang) / 111.0
                lon = m["lon"] + dist * math.sin(ang) / (111.0 * max(0.2, math.cos(math.radians(m["lat"]))))
                urbano = m["capital"] or m["pop"] > 150000
                tipo = rnd.choices(["Urbano", "Rodoviário", "Rural", "Camionista"],
                                   weights=[.55, .25, .12, .08] if urbano else [.15, .40, .35, .10])[0]
                ecod = rnd.choices([e for e, _ in PESO_EMPRESA], weights=[w for _, w in PESO_EMPRESA])[0]
                postos.append(dict(prov=prov, mun=m["nome"], lat=round(lat, 5), lon=round(lon, 5), tipo=tipo, ecod=ecod,
                                   seq=seq_prov[prov], nseq=seq_mun[(prov, m["nome"])], urbano=urbano, pop=m["pop"]))
        # postos aeroportuários (Jet A1): capitais de províncias com aeroporto relevante
        aero = ["Luanda", "Cabinda", "Benguela", "Huíla", "Huambo", "Zaire", "Lunda Sul", "Lunda Norte", "Moxico", "Cubango", "Cunene", "Namibe"]
        for p in postos:
            p["jet"] = False
        for prov in aero:
            cand = [p for p in postos if p["prov"] == prov and p["urbano"]]
            if cand:
                x = rnd.choice(cand)
                x["tipo"], x["jet"] = "Aeroportuário", True
        # estados
        for p in postos:
            r = rnd.random()
            p["estado"] = "Operacional" if r < 0.89 else ("Inoperacional" if r < 0.96 else "Encerrado")
            p["motivo"] = "" if p["estado"] == "Operacional" else (
                rnd.choice(MOTIVOS_INOP) if p["estado"] == "Inoperacional" else "Encerramento temporário por obras")
        postos.sort(key=lambda x: (list(CODIGOS_PROV).index(x["prov"]), x["seq"]))
        for i, p in enumerate(postos, 1):
            p["id"] = i
            p["codigo"] = f"{p['ecod']}-{CODIGOS_PROV[p['prov']]}-{p['seq']:04d}"
            tag = TAGS[(p["nseq"] - 1) % len(TAGS)] + ("" if p["nseq"] <= len(TAGS) else " " + "I" * (-(-p["nseq"] // len(TAGS)) - 1))
            p["nome"] = f"{'Posto ' + p['mun'] if p['ecod'] != 'PUM' else 'Pumangol ' + p['mun']} {tag}"
            n_serv = {"Urbano": 4, "Rodoviário": 3, "Rural": 1, "Camionista": 3, "Aeroportuário": 4}[p["tipo"]]
            p["servicos"] = "|".join(rnd.sample(SERVICOS[:-1], rnd.randint(max(0, n_serv - 2), n_serv)))
            # produtos comercializados
            prods = ["Gasolina", "Gasóleo"]
            e = 0.35 + 0.0 * elet.get(p["prov"], 0)
            if rnd.random() < (0.50 if p["urbano"] else 0.40):
                prods.append("GPL")
            if rnd.random() < (0.18 if p["urbano"] else 0.45):
                prods.append("Petróleo iluminante")
            if p["jet"]:
                prods.append("Jet A1")
            p["produtos"] = prods
            if "Venda de botijas GPL" not in p["servicos"] and "GPL" in prods:
                p["servicos"] = (p["servicos"] + "|" if p["servicos"] else "") + "Venda de botijas GPL"
            c.execute("INSERT INTO postos(id,codigo,nome,empresa_id,provincia,municipio,lat,lon,tipo,servicos,estado,motivo,criado_em,atualizado_em)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (p["id"], p["codigo"], p["nome"], emp_id[p["ecod"]], p["prov"], p["mun"], p["lat"], p["lon"], p["tipo"],
                       p["servicos"], p["estado"], p["motivo"], txt(inicio), txt(agora_)))
            for pr in prods:
                c.execute("INSERT INTO posto_produtos(posto_id,produto) VALUES(?,?)", (p["id"], pr))
        log(f"{len(postos)} postos")

        # ---------- reservatórios e bombas (estado inicial) ----------
        tanques = []   # dicts em memória
        bombas = []
        def novo_tanque(cod, posto, instal, prod, cap, qty, estado="Operacional", taxa=0.0):
            t = dict(id=len(tanques) + 1, cod=cod, posto=posto, inst=instal, prod=prod, cap=float(cap), qty=float(qty),
                     min=round(cap * FRACAO_MINIMO, 0), estado=estado, taxa=taxa, ini=float(qty), prod_ativa=True)
            tanques.append(t)
            return t
        base_cap = {"Gasolina": [20, 30, 40, 50, 60], "Gasóleo": [20, 30, 40, 50, 60, 80], "GPL": [8, 12, 16, 20],
                    "Petróleo iluminante": [5, 8, 10, 15], "Jet A1": [30, 50, 80]}
        taxa_base = {"Gasolina": 0.105, "Gasóleo": 0.115, "GPL": 0.045, "Petróleo iluminante": 0.040, "Jet A1": 0.06}
        for p in postos:
            tam = rnd.lognormvariate(0, 0.25) * (1.25 if p["urbano"] else 0.9)
            p["tanques"] = {}
            for pr in p["produtos"]:
                n = 2 if (pr in ("Gasolina", "Gasóleo") and rnd.random() < (0.35 if p["urbano"] else 0.15)) else 1
                for k in range(n):
                    cap = rnd.choice(base_cap[pr]) * 1000
                    if pr in ("Gasolina", "Gasóleo"):
                        cap = max(10000, round(cap * (0.8 if not p["urbano"] else 1.0) / 1000) * 1000)
                    nivel = min(1.0, max(0.0, rnd.betavariate(2.2, 2.2) * 0.9 + 0.08))
                    if rnd.random() < 0.04:
                        nivel = rnd.uniform(0.0, 0.08)
                    qty = round(cap * nivel / 100) * 100
                    taxa = taxa_base[pr] * tam * rnd.uniform(0.7, 1.3) / n
                    p["ntq"] = p.get("ntq", 0) + 1
                    t = novo_tanque(f"R{p['ntq']:02d}", p["id"], None, pr, cap, qty, taxa=taxa)
                    if rnd.random() < 0.015:
                        t["estado"] = "Em manutenção"
                    p["tanques"].setdefault(pr, []).append(t)
            # bombas
            nb = 0
            for pr in p["produtos"]:
                n_b = {"Gasolina": rnd.randint(2, 4), "Gasóleo": rnd.randint(2, 4), "GPL": 1, "Petróleo iluminante": 1,
                       "Jet A1": 2}[pr]
                if not p["urbano"] and pr in ("Gasolina", "Gasóleo"):
                    n_b = max(1, n_b - 1)
                for _ in range(n_b):
                    nb += 1
                    estado = "Avariada" if rnd.random() < 0.06 else "Operacional"
                    bombas.append(dict(cod=f"B{nb:02d}", posto=p["id"], prod=pr, estado=estado))
            if p["estado"] != "Operacional":          # posto não opera: bombas paradas
                for b in bombas[-nb:]:
                    if p["estado"] == "Inoperacional" and p["motivo"].startswith("Avaria"):
                        b["estado"] = "Avariada"
        # rutura localizada de abastecimento: ~7% dos pares posto-produto deixam de receber nos últimos dias
        suprimir = {}
        for p in postos:
            if p["estado"] != "Operacional":
                continue
            for pr, ts in p["tanques"].items():
                if pr in ("Gasolina", "Gasóleo", "GPL") and rnd.random() < 0.07:
                    for t in ts:
                        suprimir[t["id"]] = rnd.randint(max(1, dias - 8), dias - 3)
        # instalações: reservatórios grandes
        def tanque_inst(i, prod, cap_l, nivel):
            return novo_tanque(f"T-{prod[:3].upper()}-{len([t for t in tanques if t['inst'] == i['id']]) + 1:02d}", None, i["id"], prod,
                               cap_l, round(cap_l * nivel / 1000) * 1000)
        cap_prov = {}
        for p in postos:
            for pr, ts in p["tanques"].items():
                cap_prov[(p["prov"], pr)] = cap_prov.get((p["prov"], pr), 0) + sum(t["cap"] for t in ts)
        dep = {}      # (inst_id, produto) → tanque
        for i in inst:
            if i["tipo"] == "Centro de distribuição":
                for pr in PRODUTOS:
                    if pr == "Jet A1" and (i["prov"], pr) not in cap_prov:
                        cap = 300_000.0
                    else:
                        cap = max(400_000.0, 4.0 * cap_prov.get((i["prov"], pr), 0))
                    dep[(i["id"], pr)] = tanque_inst(i, pr, round(cap / 10000) * 10000, rnd.uniform(0.55, 0.9))
            elif i["tipo"] == "Base logística":
                for pr in ("Gasolina", "Gasóleo", "GPL", "Petróleo iluminante"):
                    dep[(i["id"], pr)] = tanque_inst(i, pr, rnd.choice([300_000, 500_000, 800_000]), rnd.uniform(0.5, 0.9))
            elif i["tipo"] == "Terminal de armazenamento":
                grande = i["codigo"] in ("TRM-TOBD", "TRM-LDA")
                for pr in PRODUTOS:
                    cap = (60_000_000 if pr in ("Gasolina", "Gasóleo") else 15_000_000) if grande else (8_000_000 if pr in ("Gasolina", "Gasóleo") else 2_000_000)
                    dep[(i["id"], pr)] = tanque_inst(i, pr, cap, rnd.uniform(0.6, 0.9))
            elif i["tipo"] == "Refinaria" and i["estado"] == "Operacional":
                for pr in ("Gasolina", "Gasóleo", "Jet A1", "GPL", "Petróleo iluminante"):
                    cap = 25_000_000 if pr in ("Gasolina", "Gasóleo") else 8_000_000
                    dep[(i["id"], pr)] = tanque_inst(i, pr, cap, rnd.uniform(0.55, 0.9))
        log(f"{len(tanques)} reservatórios, {len(bombas)} bombas")

        # ---------- simulação operacional (razão contabilística) ----------
        movs = []         # (data_hora, tipo, tanque, delta, stock_apos, entrega_id, obs)
        entregas = []
        pendentes = []    # eventos: (t, 'saida'|'chegada', entrega)
        for t in tanques:
            movs.append([txt(inicio), "Saldo inicial", t, t["qty"], t["qty"], None, "Saldo inicial da simulação"])
        T = {t["id"]: t for t in tanques}
        seq_ent = [0]
        pend_tanque = set()
        prov_de_posto = {p["id"]: p["prov"] for p in postos}
        def mov(quando, tipo, t, delta, ent=None, obs=""):
            t["qty"] = round(t["qty"] + delta, 3)
            movs.append([txt(quando), tipo, t, round(delta, 3), t["qty"], ent["id"] if ent else None, obs])
        def criar_entrega(quando, origem_inst, origem_desc, destino_t, volume, produto, dist_km):
            seq_ent[0] += 1
            saida = quando
            horas = 3 + dist_km / 45.0 + rnd.uniform(0, 5)
            e = dict(id=seq_ent[0], codigo=f"ENT-{quando:%Y%m%d}-{seq_ent[0]:05d}", prod=produto, qtd=volume, orig=origem_inst,
                     orig_desc=origem_desc, dest_t=destino_t, saida=saida, prev=saida + timedelta(hours=horas), chegada=None,
                     estado="Planeada", veiculo=None, orig_t=dep.get((origem_inst, produto)) if origem_inst else None)
            ent_prov = prov_de_posto.get(destino_t["posto"]) if destino_t["posto"] else I[destino_t["inst"]]["prov"]
            e["veiculo"] = f"{CODIGOS_PROV.get(ent_prov, 'LD')[:2]}-{rnd.randint(10, 99)}-{rnd.randint(10, 99)}-{rnd.choice('ABCDEFGH')}{rnd.choice('ABCDEFGH')}"
            entregas.append(e)
            pend_tanque.add(destino_t["id"])
            return e
        def processar_evento(t_evt, tipo, e):
            if tipo == "saida":
                o = e["orig_t"]
                if o is None:                       # origem externa (refinaria/importação)
                    e["estado"] = "Em trânsito"
                    return
                vol = min(e["qtd"], max(0.0, o["qty"] - o["min"] * 0.0))
                vol = math.floor(vol / 1000) * 1000
                if vol < 1000:                      # origem sem produto: entrega cancelada
                    e["estado"] = "Cancelada"
                    pend_tanque.discard(e["dest_t"]["id"])
                    return
                e["qtd"] = vol
                mov(t_evt, "Distribuição", o, -vol, e, f"Saída para {e['codigo']}")
                e["estado"] = "Em trânsito"
            elif tipo == "chegada" and e["estado"] == "Em trânsito":
                d = e["dest_t"]
                vol = min(e["qtd"], d["cap"] - d["qty"])
                if d["estado"] != "Operacional" or vol < 1:
                    # destino não pode receber: devolve a carga à origem se existir; senão fica em trânsito
                    if e["orig_t"] is not None and e["orig_t"]["cap"] - e["orig_t"]["qty"] >= e["qtd"]:
                        mov(t_evt, "Ajuste", e["orig_t"], e["qtd"], e, f"Devolução {e['codigo']}")
                    e["estado"] = "Cancelada"
                    pend_tanque.discard(d["id"])
                    return
                if vol < e["qtd"] and e["orig_t"] is not None:   # excedente volta à origem
                    volta = min(e["qtd"] - vol, e["orig_t"]["cap"] - e["orig_t"]["qty"])
                    if volta > 0:
                        mov(t_evt, "Ajuste", e["orig_t"], volta, e, f"Excedente devolvido {e['codigo']}")
                e["qtd"] = vol
                mov(t_evt, "Receção", d, vol, e, f"Entrega {e['codigo']}")
                e["estado"] = "Entregue"
                e["chegada"] = t_evt
                pend_tanque.discard(d["id"])
        fim = agora_
        eventos = []      # heap simples por dia
        for d in range(dias + 1):
            dia = inicio + timedelta(days=d)
            if dia > fim:
                break
            # 1) importações/reabastecimento de terminais e refinarias (receção direta de navio/produção)
            for (iid, pr), t in dep.items():
                if I[iid]["tipo"] in ("Terminal de armazenamento", "Refinaria") and t["qty"] < 0.40 * t["cap"]:
                    q = math.floor((0.90 * t["cap"] - t["qty"]) / 10000) * 10000
                    if q > 0:
                        quando = dia + timedelta(hours=rnd.randint(1, 5))
                        if quando <= fim:
                            mov(quando, "Receção", t, q, None, "Importação (navio-tanque, simulada)" if I[iid]["tipo"] != "Refinaria"
                                else "Produção da refinaria (simulada)")
            # 2) eventos agendados que caem neste dia + vendas
            marcos = []
            for e in entregas:
                if e["estado"] == "Planeada" and dia <= e["saida"] < dia + timedelta(days=1):
                    marcos.append((e["saida"], "saida", e))
                if e["estado"] in ("Planeada", "Em trânsito") and dia <= e["prev"] < dia + timedelta(days=1):
                    marcos.append((e["prev"], "chegada", e))
            for p in postos:
                if p["estado"] == "Operacional":
                    marcos.append((dia + timedelta(hours=20), "venda", p))
            marcos.append((dia + timedelta(hours=23, minutes=30), "reposicao", None))
            marcos.sort(key=lambda m: (m[0], {"saida": 0, "chegada": 1, "venda": 2, "reposicao": 3}[m[1]]))
            for quando, tipo, obj in marcos:
                if quando > fim:
                    continue
                if tipo in ("saida", "chegada"):
                    if tipo == "chegada" and obj["estado"] == "Planeada":
                        processar_evento(obj["saida"], "saida", obj)
                    if tipo == "saida" and obj["estado"] != "Planeada":
                        continue
                    processar_evento(quando, tipo, obj)
                elif tipo == "venda":
                    p = obj
                    for pr, ts in p["tanques"].items():
                        bombas_ok = any(b["posto"] == p["id"] and b["prod"] == pr and b["estado"] == "Operacional" for b in bombas)
                        for t in ts:
                            if t["estado"] != "Operacional" or not bombas_ok:
                                continue
                            dow = quando.weekday()
                            fator = 1.12 if dow in (4, 5) else (0.85 if dow == 6 else 1.0)
                            v = min(t["qty"], round(t["cap"] * t["taxa"] * fator * rnd.uniform(0.65, 1.35) / 10) * 10)
                            if v > 0:
                                mov(quando, "Venda", t, -v, None, "Vendas do dia (agregado)")
                else:        # reposição: pedidos de reabastecimento
                    for p in postos:
                        if p["estado"] != "Operacional":
                            continue
                        for pr, ts in p["tanques"].items():
                            for t in ts:
                                if t["id"] in pend_tanque or t["estado"] != "Operacional":
                                    continue
                                if t["id"] in suprimir and d >= suprimir[t["id"]]:
                                    continue
                                if t["qty"] < 0.30 * t["cap"]:
                                    vol = math.floor((0.92 * t["cap"] - t["qty"]) / 1000) * 1000
                                    if vol < 2000:
                                        continue
                                    cd = centro[p["prov"]]
                                    km = _km((p["lat"], p["lon"]), (I[cd]["lat"], I[cd]["lon"]))
                                    criar_entrega(quando + timedelta(hours=rnd.randint(7, 14)), cd, I[cd]["nome"], t, vol, pr, km)
                    for (iid, pr), t in list(dep.items()):
                        if I[iid]["tipo"] in ("Centro de distribuição", "Base logística") and t["id"] not in pend_tanque \
                                and t["qty"] < 0.35 * t["cap"]:
                            vol = math.floor((0.85 * t["cap"] - t["qty"]) / 10000) * 10000
                            if vol < 20000:
                                continue
                            tm = term_de.get(I[iid]["prov"], terminais[0])
                            km = _km((I[iid]["lat"], I[iid]["lon"]), (I[tm]["lat"], I[tm]["lon"]))
                            criar_entrega(quando + timedelta(hours=rnd.randint(6, 12)), tm, I[tm]["nome"], t, vol, pr, km)
        # as entregas que ainda não saíram ficam «Planeada»; entregas com saída ≤ agora e chegada > agora ficam «Em trânsito»
        for e in entregas:
            if e["estado"] == "Planeada" and e["saida"] <= fim:
                processar_evento(e["saida"], "saida", e)
        log(f"{len(movs)} movimentos, {len(entregas)} entregas")

        # ---------- gravação ----------
        agora_txt = txt(agora_)
        ult = {}
        for m in movs:
            ult[m[2]["id"]] = m[0]
        for t in tanques:
            c.execute("INSERT INTO reservatorios(id,codigo,posto_id,instalacao_id,produto,capacidade_l,quantidade_l,minimo_operacional_l,estado,atualizado_em)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (t["id"], t["cod"], t["posto"], t["inst"], t["prod"], t["cap"], t["qty"], t["min"], t["estado"], ult.get(t["id"], txt(inicio))))
        for i, b in enumerate(bombas, 1):
            c.execute("INSERT INTO bombas(id,codigo,posto_id,produto,estado,atualizado_em) VALUES(?,?,?,?,?,?)",
                      (i, b["cod"], b["posto"], b["prod"], b["estado"], agora_txt))
        for e in entregas:
            d = e["dest_t"]
            c.execute("INSERT INTO entregas(id,codigo,produto,quantidade_l,origem_instalacao_id,origem_descricao,destino_posto_id,destino_instalacao_id,"
                      "destino_reservatorio_id,veiculo,estado,data_saida,data_prevista_chegada,data_chegada,criado_em,atualizado_em)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (e["id"], e["codigo"], e["prod"], e["qtd"], e["orig"], e["orig_desc"], d["posto"], d["inst"], d["id"], e["veiculo"],
                       e["estado"], txt(e["saida"]), txt(e["prev"]), txt(e["chegada"]), txt(e["saida"]), txt(e["chegada"] or e["saida"])))
        def cm(rows):
            c.executemany("INSERT INTO movimentos(data_hora,tipo,reservatorio_id,posto_id,instalacao_id,produto,delta_l,stock_apos_l,entrega_id,observacao)"
                          " VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
        ent_id = {e["id"]: e for e in entregas}
        rows = []
        for q, tipo, t, delta, apos, eid, obs in movs:
            rows.append((q, tipo, t["id"], t["posto"], t["inst"], t["prod"], delta, apos, eid, obs))
        rows.sort(key=lambda r: (r[0], r[2]))
        cm(rows)
        db.cfg_set("ultima_atualizacao", agora_txt, c)
        db.cfg_set("semente", str(semente), c)
        db.cfg_set("gerado_em", agora_txt, c)
        db.cfg_set("dias_historico", str(dias), c)
    log("concluído")
    return dict(postos=len(postos), reservatorios=len(tanques), bombas=len(bombas), movimentos=len(movs), entregas=len(entregas),
                instalacoes=len(inst))
