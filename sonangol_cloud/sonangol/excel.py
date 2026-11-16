"""Exportação e importação Excel (.xlsx) com formatação profissional, filtros, folhas por categoria e compatibilidade com o SIG-CAD."""
from __future__ import annotations

import io
from datetime import datetime

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation
    OPENPYXL_OK = True
except ImportError:          # o painel e a API arrancam na mesma; só o Excel fica indisponível
    OPENPYXL_OK = False
    Workbook = load_workbook = Comment = Alignment = Border = Font = PatternFill = get_column_letter = DataValidation = None

    class Side:  # noqa: D401
        def __init__(self, *a, **k):
            pass


def _exige_openpyxl():
    if not OPENPYXL_OK:
        raise RuntimeError("Falta o pacote «openpyxl» (necessário só para Excel). Instale com:  py -m pip install openpyxl")


from . import consultas as q, db, operacoes as ops
from .config import (AVISO_SIMULADO, ESTADOS_BOMBA, ESTADOS_POSTO, ESTADOS_RESERVATORIO, NOMES_PRODUTOS, agora, txt)

AZUL = "0B3A6F"
FUNDO_ALT = "F3F6FA"
FINO = Side(style="thin", color="D5DBE5")

# coluna → (descrição/unidade, largura)
DESC = {
    "id": ("Identificador único do posto (código)", 16), "nome": ("Nome do posto", 30), "empresa": ("Empresa proprietária/operadora", 24),
    "provincia": ("Província (uma das 21)", 15), "municipio": ("Município", 18), "lat": ("Latitude (graus decimais, WGS84)", 11),
    "lon": ("Longitude (graus decimais, WGS84)", 11), "tipo": ("Tipo de posto", 14), "servicos": ("Serviços, separados por |", 34),
    "estado": ("Estado operacional", 14), "produtos": ("Produtos comercializados, separados por |", 34), "atualizado_em": ("Data/hora da última atualização (hora de Luanda)", 19),
    "posto_id": ("Identificador do posto", 16), "produto": ("Produto", 20), "disponivel": ("Disponível para venda (sim/não)", 12),
    "stock_l": ("Quantidade disponível em litros (L)", 14), "capacidade_l": ("Capacidade máxima em litros (L)", 15), "litros": ("Quantidade atual em litros (L)", 14),
    "reservatorio_id": ("Identificador do reservatório (no posto)", 14), "bomba_id": ("Identificador da bomba (no posto)", 12),
    "preco": ("Preço por unidade (Kz)", 12), "unidade": ("Unidade do preço", 16), "ocupacao_pct": ("Ocupação do reservatório (%)", 12),
    "minimo_operacional_l": ("Quantidade mínima operacional (L)", 16), "comercializado": ("O posto comercializa o produto (sim/não)", 14),
    "bombas_operacionais": ("Nº de bombas operacionais do produto", 14), "empresa_codigo": ("Código da empresa", 12),
    "quantidade_l": ("Quantidade em litros (L)", 14), "origem": ("Origem", 30), "destino": ("Destino", 30), "veiculo": ("Matrícula do veículo", 16),
    "data_saida": ("Data/hora de saída", 19), "data_prevista_chegada": ("Data/hora prevista de chegada", 19), "data_chegada": ("Data/hora de chegada", 19),
    "data_hora": ("Data/hora do movimento", 19), "variacao_l": ("Variação do stock em litros (+ entrada, − saída)", 14), "stock_apos_l": ("Stock após o movimento (L)", 14),
    "posto_nome": ("Nome do posto", 28), "instalacao_id": ("Identificador da instalação", 14), "entrega_id": ("Entrega associada", 22),
    "observacao": ("Observação", 34),
}
COLS = {
    "Postos": ["id", "nome", "empresa", "provincia", "municipio", "lat", "lon", "tipo", "servicos", "estado", "produtos", "atualizado_em"],
    "Disponibilidade": ["posto_id", "produto", "disponivel", "stock_l", "capacidade_l", "ocupacao_pct", "estado", "bombas_operacionais", "atualizado_em"],
    "Reservatorios": ["posto_id", "instalacao_id", "reservatorio_id", "produto", "capacidade_l", "litros", "ocupacao_pct", "minimo_operacional_l", "estado", "atualizado_em"],
    "Bombas": ["posto_id", "bomba_id", "produto", "estado", "atualizado_em"],
    "Precos": ["produto", "preco", "unidade", "atualizado_em"],
}
# compatibilidade: colunas exatamente como o SIG-CAD espera (padrão único) + extras não prejudiciais
SIGCAD_COLS = {
    "Postos": ["id", "nome", "provincia", "municipio", "lat", "lon", "tipo", "servicos", "estado", "produtos", "atualizado_em", "empresa"],
    "Disponibilidade": ["posto_id", "produto", "disponivel", "stock_l", "atualizado_em"],
    "Reservatorios": ["posto_id", "reservatorio_id", "produto", "capacidade_l", "litros", "atualizado_em"],
    "Bombas": ["posto_id", "bomba_id", "produto", "estado", "atualizado_em"],
    "Precos": ["produto", "preco", "unidade", "atualizado_em"],
}


def _dt(s):
    if not s:
        return None
    s = str(s).replace("T", " ")[:19]
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return s


def _folha(wb: Workbook, nome: str, colunas: list[str], linhas: list[dict], titulo: str | None = None, descricoes: bool = True):
    ws = wb.create_sheet(nome[:31])
    cab_fill = PatternFill("solid", fgColor=AZUL)
    for j, c in enumerate(colunas, 1):
        cel = ws.cell(row=1, column=j, value=c)
        cel.font = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
        cel.fill = cab_fill
        cel.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cel.border = Border(bottom=FINO, right=FINO)
        if descricoes and c in DESC:
            cel.comment = Comment(DESC[c][0], "SONANGOL (simulada)", width=260, height=60)
        ws.column_dimensions[get_column_letter(j)].width = DESC.get(c, ("", 16))[1]
    ws.row_dimensions[1].height = 30
    for i, r in enumerate(linhas, 2):
        for j, c in enumerate(colunas, 1):
            v = r.get(c)
            if c.endswith("_em") or c.startswith("data_"):
                v = _dt(v)
            elif isinstance(v, bool):
                v = "sim" if v else "não"
            elif isinstance(v, (list, tuple)):
                v = "|".join(map(str, v))
            cel = ws.cell(row=i, column=j, value=v)
            if isinstance(v, datetime):
                cel.number_format = "yyyy-mm-dd hh:mm:ss"
            elif c.endswith("_l"):
                cel.number_format = "#,##0"
            elif c in ("lat", "lon"):
                cel.number_format = "0.00000"
            elif c.endswith("_pct"):
                cel.number_format = "0.0"
            elif c == "preco":
                cel.number_format = "#,##0.00"
            if i % 2 == 1:
                cel.fill = PatternFill("solid", fgColor=FUNDO_ALT)
    ws.freeze_panes = "A2"
    if linhas:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(colunas))}{len(linhas) + 1}"
    ws.sheet_view.zoomScale = 100
    return ws


def _leia_me(wb: Workbook, categoria: str, filtros: dict, contagens: dict):
    ws = wb.active
    ws.title = "Leia-me"
    ws["A1"] = "SONANGOL — exportação de dados"
    ws["A1"].font = Font(bold=True, size=16, color=AZUL)
    ws["A2"] = AVISO_SIMULADO
    ws["A2"].font = Font(bold=True, color="9C2B00")
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells("A2:D2")
    ws.row_dimensions[2].height = 48
    info = [("Categoria", categoria), ("Gerado em (hora de Luanda)", txt(agora())), ("Última atualização dos dados", db.cfg_get("ultima_atualizacao")),
            ("Filtros aplicados", ", ".join(f"{k}={v}" for k, v in filtros.items() if v and k != "categoria") or "nenhum")]
    for i, (k, v) in enumerate(info, 4):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True)
        ws.cell(row=i, column=2, value=v)
    r = len(info) + 5
    ws.cell(row=r, column=1, value="Folha").font = Font(bold=True)
    ws.cell(row=r, column=2, value="Registos").font = Font(bold=True)
    for k, v in contagens.items():
        r += 1
        ws.cell(row=r, column=1, value=k)
        ws.cell(row=r, column=2, value=v)
    r += 2
    for t in ("Convenções: primeira linha = nomes técnicos das colunas (passe o rato por cima para ver a descrição e a unidade).",
              "Unidades: quantidades em litros (L); preços em Kz; datas em AAAA-MM-DD hh:mm:ss, hora de Luanda (UTC+1).",
              "Identificadores únicos: postos SD-LDA-0001 · reservatórios (posto_id + reservatorio_id) · bombas (posto_id + bomba_id).",
              "Esta estrutura (folhas Postos, Disponibilidade, Reservatorios, Bombas, Precos) é a que o SIG-CAD importa."):
        ws.cell(row=r, column=1, value=t)
        r += 1
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 40
    ws.column_dimensions["C"].width = 30
    ws.column_dimensions["D"].width = 30


def _dados(nome: str, f: dict, sigcad: bool = False) -> list[dict]:
    f = dict(f, page_size=q.PAGINA_MAX)
    f.pop("page", None)
    if nome == "Postos":
        d, m = q.listar_postos(f)
        while m["tem_proxima"]:
            f["page"] = m["page"] + 1
            d2, m = q.listar_postos(f)
            d += d2
        for x in d:
            x["estado"] = ("Operacional" if x["estado"] == "Operacional" else "Inoperacional") if sigcad else x["estado"]
        return d
    if nome == "Disponibilidade":
        return q.listar_disponibilidade(f)[0]
    if nome == "Reservatorios":
        rows = q.listar_reservatorios(dict(f, proprietario="posto") if sigcad else f)[0]
        if sigcad:
            for r in rows:
                r["reservatorio_id"] = r["reservatorio_id"].split("/")[-1]
        else:
            for r in rows:
                r["reservatorio_id"] = r["reservatorio_id"].split("/")[-1]
        return rows
    if nome == "Bombas":
        rows = q.listar_bombas(f)[0]
        for r in rows:
            r["bomba_id"] = r["bomba_id"].split("/")[-1]
        return rows
    if nome == "Precos":
        return q.listar_precos(f)[0]
    raise KeyError(nome)


def exportar(categoria: str = "completo", filtros: dict | None = None) -> bytes:
    _exige_openpyxl()
    f = {k: v for k, v in (filtros or {}).items() if k in ("provincia", "municipio", "empresa", "produto", "estado", "desde", "ate")}
    wb = Workbook()
    cont = {}
    mapa = {"postos": ["Postos"], "disponibilidade": ["Disponibilidade"], "reservatorios": ["Reservatorios"], "bombas": ["Bombas"], "precos": ["Precos"]}
    cat = categoria.lower()
    sigcad = cat == "sigcad"
    if sigcad or cat == "completo" or cat in mapa:
        nomes = list(SIGCAD_COLS) if sigcad else (list(COLS) if cat == "completo" else mapa[cat])
        for n in nomes:
            linhas = _dados(n, f, sigcad)
            _folha(wb, n, (SIGCAD_COLS if sigcad else COLS)[n], linhas)
            cont[n] = len(linhas)
    if cat == "completo" or cat == "instalacoes":
        d = q.listar_instalacoes(dict(f, page_size=q.PAGINA_MAX))[0]
        _folha(wb, "Instalacoes", ["id", "nome", "tipo", "empresa", "provincia", "municipio", "lat", "lon", "estado", "capacidade_l", "stock_l", "ocupacao_pct", "atualizado_em"], d)
        cont["Instalacoes"] = len(d)
        if cat == "instalacoes":
            pass
    if cat in ("completo", "entregas"):
        d = q.listar_entregas(dict(f, page_size=q.PAGINA_MAX))[0]
        _folha(wb, "Entregas", ["id", "produto", "quantidade_l", "origem", "destino", "destino_provincia", "veiculo", "estado", "data_saida", "data_prevista_chegada", "data_chegada"], d)
        cont["Entregas"] = len(d)
    if cat in ("completo", "movimentos"):
        ff = dict(f)
        if cat == "completo" and not ff.get("desde"):
            from datetime import timedelta
            ff["desde"] = (agora() - timedelta(days=7)).strftime("%Y-%m-%d")
        d = q.listar_movimentos(dict(ff, page_size=q.PAGINA_MAX, ordem="asc"))[0]
        _folha(wb, "Movimentos", ["id", "data_hora", "tipo", "posto_id", "instalacao_id", "produto", "variacao_l", "stock_apos_l", "entrega_id", "observacao"], d)
        cont["Movimentos"] = len(d)
    if cat in ("completo", "indicadores"):
        ind = q.indicadores(f)
        prods = ind["produtos"]
        _folha(wb, "Indicadores_Produtos", list(prods[0].keys()), prods, descricoes=False)
        provs = q.indicadores_provincias(f)
        _folha(wb, "Indicadores_Provincias", [k for k in provs[0].keys() if k != "simulado"], provs, descricoes=False)
        ev = q.evolucao_stocks(f)
        _folha(wb, "Evolucao_Stocks", ["data", "produto", "stock_postos_l", "stock_instalacoes_l"], ev, descricoes=False)
        g = [dict(indicador=k, valor=v) for blk in ("postos", "volumes") for k, v in ind[blk].items()]
        g.append(dict(indicador="situacao_geral", valor=ind["situacao_geral"]["classificacao"]))
        _folha(wb, "Indicadores_Globais", ["indicador", "valor"], g, descricoes=False)
        cont.update({"Indicadores_Globais": len(g), "Indicadores_Produtos": len(prods), "Indicadores_Provincias": len(provs), "Evolucao_Stocks": len(ev)})
    if not cont:
        raise KeyError(categoria)
    _leia_me(wb, categoria, f, cont)
    wb.move_sheet("Leia-me", offset=-len(wb.sheetnames) + 1)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- modelo e importação
def modelo_importacao() -> bytes:
    _exige_openpyxl()
    wb = Workbook()
    ws = wb.active
    ws.title = "Instruções"
    txts = ["Modelo de importação SONANGOL", AVISO_SIMULADO, "",
            "1. Preencha as folhas Postos, Reservatorios, Bombas e Precos (a folha Disponibilidade é calculada pela plataforma e não é importada).",
            "2. A primeira linha de cada folha contém os nomes técnicos das colunas: não os altere.",
            "3. Postos novos precisam de: id (opcional — gera-se), nome, empresa, provincia, municipio. Postos existentes (mesmo id) são atualizados.",
            "4. Reservatorios: posto_id + reservatorio_id identificam o reservatório. Novo: capacidade_l obrigatória. Existente: litros ajusta o stock (gera um movimento «Ajuste»).",
            "5. Regras: 0 ≤ litros ≤ capacidade_l; produtos válidos: " + ", ".join(NOMES_PRODUTOS) + ".",
            "6. As linhas inválidas são rejeitadas com a indicação do motivo; as válidas são aplicadas."]
    for i, t in enumerate(txts, 1):
        ws.cell(row=i, column=1, value=t)
    ws["A1"].font = Font(bold=True, size=15, color=AZUL)
    ws.column_dimensions["A"].width = 130
    exemplos = {
        "Postos": [dict(id="SD-LDA-9001", nome="Posto Exemplo 01", empresa="Sonangol Distribuidora", provincia="Luanda", municipio="Viana", lat=-8.9, lon=13.37,
                        tipo="Urbano", servicos="Loja de conveniência|Lavagem", estado="Operacional", produtos="Gasolina|Gasóleo")],
        "Reservatorios": [dict(posto_id="SD-LDA-9001", reservatorio_id="R01", produto="Gasóleo", capacidade_l=40000, litros=25000, minimo_operacional_l=4000, estado="Operacional")],
        "Bombas": [dict(posto_id="SD-LDA-9001", bomba_id="B01", produto="Gasóleo", estado="Operacional")],
        "Precos": [dict(produto="Gasóleo", preco=400, unidade="Kz/L")],
    }
    cols = {"Postos": ["id", "nome", "empresa", "provincia", "municipio", "lat", "lon", "tipo", "servicos", "estado", "produtos"],
            "Reservatorios": ["posto_id", "reservatorio_id", "produto", "capacidade_l", "litros", "minimo_operacional_l", "estado"],
            "Bombas": ["posto_id", "bomba_id", "produto", "estado"], "Precos": ["produto", "preco", "unidade"]}
    for n, cs in cols.items():
        w = _folha(wb, n, cs, exemplos[n])
        for col, lista in (("estado", None),):
            pass
    wsr = wb["Reservatorios"]
    dv = DataValidation(type="list", formula1='"' + ",".join(NOMES_PRODUTOS) + '"', allow_blank=True)
    wsr.add_data_validation(dv)
    dv.add("C2:C2000")
    dv2 = DataValidation(type="list", formula1='"' + ",".join(ESTADOS_RESERVATORIO) + '"', allow_blank=True)
    wsr.add_data_validation(dv2)
    dv2.add("G2:G2000")
    dv3 = DataValidation(type="list", formula1='"' + ",".join(ESTADOS_POSTO) + '"', allow_blank=True)
    wb["Postos"].add_data_validation(dv3)
    dv3.add("J2:J2000")
    dv4 = DataValidation(type="list", formula1='"' + ",".join(ESTADOS_BOMBA) + '"', allow_blank=True)
    wb["Bombas"].add_data_validation(dv4)
    dv4.add("D2:D2000")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _linhas(ws) -> list[dict]:
    it = ws.iter_rows(values_only=True)
    cab = next(it, None)
    if not cab:
        return []
    cab = [q.norm(c) if c is not None else "" for c in cab]
    nomes = [str(c).strip().lower() if c is not None else "" for c in next(iter([[*ws.iter_rows(min_row=1, max_row=1, values_only=True)][0]]))]
    out = []
    for n, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if all(v in (None, "") for v in row):
            continue
        d = {nomes[i]: v for i, v in enumerate(row) if i < len(nomes) and nomes[i]}
        d["_linha"] = n
        out.append(d)
    return out


def _txt(v):
    return "" if v is None else str(v).strip()


def _num(v, campo):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", ".")) if isinstance(v, str) else float(v)
    except ValueError:
        raise q.ErroValidacao(f"«{campo}» não é um número: {v}", campo)


def importar(conteudo: bytes, utilizador: str = "importação Excel", aplicar: bool = True) -> dict:
    _exige_openpyxl()
    """Importa um .xlsx. Devolve {folha: {inseridos, atualizados, rejeitados, erros[]}}. Com aplicar=False só valida (simulação)."""
    wb = load_workbook(io.BytesIO(conteudo), data_only=True)
    rel = {}
    def novo(n):
        rel[n] = dict(inseridos=0, atualizados=0, rejeitados=0, erros=[])
        return rel[n]
    def falha(r, linha, e):
        r["rejeitados"] += 1
        if len(r["erros"]) < 50:
            r["erros"].append(f"linha {linha['_linha']}: {e}")
    nomes = {q.norm(n): n for n in wb.sheetnames}
    emp = {q.norm(x["nome"]): x["id"] for x in db.consultar("SELECT id,nome FROM empresas")}
    emp.update({q.norm(x["codigo"]): x["id"] for x in db.consultar("SELECT id,codigo FROM empresas")})
    if "postos" in nomes:
        r = novo("Postos")
        for l in _linhas(wb[nomes["postos"]]):
            try:
                if not _txt(l.get("nome")):
                    raise q.ErroValidacao("nome em falta", "nome")
                prov = q.provincia_canonica(l.get("provincia"))
                mun = q.municipio_canonico(l.get("municipio"), prov)
                est = q.escolha(_txt(l.get("estado")) or "Operacional", ESTADOS_POSTO, "estado")
                prods = [q.produto_canonico(x) for x in _txt(l.get("produtos")).split("|") if x.strip()]
                existente = db.um("SELECT id FROM postos WHERE codigo=?", (_txt(l.get("id")),)) if _txt(l.get("id")) else None
                d = dict(nome=_txt(l["nome"]), provincia=prov, municipio=mun, lat=_num(l.get("lat"), "lat"), lon=_num(l.get("lon"), "lon"),
                         tipo=_txt(l.get("tipo")) or "Urbano", servicos=_txt(l.get("servicos")), estado=est, produtos=prods,
                         motivo="" if est == "Operacional" else "Importado de Excel")
                e = emp.get(q.norm(l.get("empresa")))
                if existente:
                    if e:
                        d["empresa_id"] = e
                    if aplicar:
                        ops.atualizar_posto(existente["id"], d, utilizador)
                    r["atualizados"] += 1
                else:
                    if not e:
                        raise q.ErroValidacao(f"empresa desconhecida «{l.get('empresa')}»", "empresa")
                    d["empresa_id"] = e
                    d["codigo"] = _txt(l.get("id"))
                    if aplicar:
                        ops.criar_posto(d, utilizador)
                    r["inseridos"] += 1
            except (q.ErroValidacao, ValueError) as ex:
                falha(r, l, ex)
    if "reservatorios" in nomes:
        r = novo("Reservatorios")
        for l in _linhas(wb[nomes["reservatorios"]]):
            try:
                p = db.um("SELECT id FROM postos WHERE codigo=?", (_txt(l.get("posto_id")),))
                if not p:
                    raise q.ErroValidacao(f"posto «{l.get('posto_id')}» inexistente", "posto_id")
                rc = _txt(l.get("reservatorio_id"))
                if not rc:
                    raise q.ErroValidacao("reservatorio_id em falta", "reservatorio_id")
                prod = q.produto_canonico(l.get("produto"))
                cap, lit, mn = _num(l.get("capacidade_l"), "capacidade_l"), _num(l.get("litros"), "litros"), _num(l.get("minimo_operacional_l"), "minimo_operacional_l")
                est = q.escolha(_txt(l.get("estado")), ESTADOS_RESERVATORIO, "estado")
                t = db.um("SELECT id, produto FROM reservatorios WHERE posto_id=? AND codigo=?", (p["id"], rc))
                if t:
                    if t["produto"] != prod:
                        raise q.ErroValidacao("o produto do reservatório não pode mudar", "produto")
                    if aplicar:
                        ops.atualizar_reservatorio(t["id"], cap, mn, est, utilizador)
                        if lit is not None:
                            with db.tx() as c:
                                ops.definir_stock(c, t["id"], lit, "Importação Excel", utilizador)
                    elif lit is not None and cap is None:
                        cp = db.um("SELECT capacidade_l c FROM reservatorios WHERE id=?", (t["id"],))["c"]
                        if not 0 <= lit <= cp:
                            raise q.ErroValidacao("litros fora de [0, capacidade]", "litros")
                    r["atualizados"] += 1
                else:
                    if cap is None:
                        raise q.ErroValidacao("capacidade_l obrigatória para criar o reservatório", "capacidade_l")
                    if lit is not None and not 0 <= lit <= cap:
                        raise q.ErroValidacao("litros fora de [0, capacidade]", "litros")
                    if aplicar:
                        ops.criar_reservatorio(p["id"], None, prod, cap, lit or 0.0, rc, mn, utilizador)
                    r["inseridos"] += 1
            except (q.ErroValidacao, ValueError) as ex:
                falha(r, l, ex)
    if "bombas" in nomes:
        r = novo("Bombas")
        for l in _linhas(wb[nomes["bombas"]]):
            try:
                p = db.um("SELECT id FROM postos WHERE codigo=?", (_txt(l.get("posto_id")),))
                if not p:
                    raise q.ErroValidacao(f"posto «{l.get('posto_id')}» inexistente", "posto_id")
                prod = q.produto_canonico(l.get("produto"))
                est = q.escolha(_txt(l.get("estado")) or "Operacional", ESTADOS_BOMBA, "estado")
                b = db.um("SELECT id FROM bombas WHERE posto_id=? AND codigo=?", (p["id"], _txt(l.get("bomba_id"))))
                if b:
                    if aplicar:
                        ops.estado_bomba(b["id"], est, utilizador)
                    r["atualizados"] += 1
                else:
                    if aplicar:
                        ops.criar_bomba(p["id"], prod, est, utilizador)
                    r["inseridos"] += 1
            except (q.ErroValidacao, ValueError) as ex:
                falha(r, l, ex)
    if "precos" in nomes:
        r = novo("Precos")
        for l in _linhas(wb[nomes["precos"]]):
            try:
                pr = q.produto_canonico(l.get("produto"))
                v = _num(l.get("preco"), "preco")
                if v is None or v <= 0:
                    raise q.ErroValidacao("preço deve ser positivo", "preco")
                if aplicar:
                    ops.definir_preco(pr, v, utilizador)
                r["atualizados"] += 1
            except (q.ErroValidacao, ValueError) as ex:
                falha(r, l, ex)
    if not rel:
        raise q.ErroValidacao("O ficheiro não tem nenhuma folha reconhecida (Postos, Reservatorios, Bombas, Precos).")
    return rel
