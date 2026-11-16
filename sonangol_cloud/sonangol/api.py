"""API REST da plataforma SONANGOL (Flask). Prefixo /api/v1 · JSON · autenticação por API Key ou Bearer Token."""
from __future__ import annotations

import io
import time

from flask import Flask, Response, g, jsonify, request

from . import auth, consultas as q, db, excel, operacoes as ops
from .config import API_PREFIXO, AVISO_SIMULADO, PRODUTOS, agora, iso, txt

app = Flask(__name__)
app.json.ensure_ascii = False
app.json.sort_keys = False
P = API_PREFIXO

FILTROS_POSTO = [("provincia", "Nome da província (ex.: Luanda). Aceita maiúsculas/acentos indiferentes."), ("municipio", "Nome do município."),
                 ("empresa", "Código ou nome da empresa (ex.: SD, Pumangol)."), ("produto", "Gasolina, Gasóleo, Jet A1, Petróleo iluminante, GPL."),
                 ("estado", "Operacional, Inoperacional ou Encerrado.")]
PAGINACAO = [("page", "Página (a partir de 1)."), ("page_size", f"Registos por página (1–{q.PAGINA_MAX}; omissão {q.PAGINA_PADRAO}).")]
PERIODO = [("desde", "Início do período (AAAA-MM-DD ou AAAA-MM-DDTHH:MM:SS)."), ("ate", "Fim do período.")]

# registo dos endpoints (alimenta /openapi.json e /docs)
ENDPOINTS: list[dict] = []


def rota(caminho, resumo, params=(), publico=False, campos=""):
    def deco(f):
        ENDPOINTS.append(dict(caminho=caminho, resumo=resumo, params=list(params), publico=publico, campos=campos, nome=f.__name__))
        app.add_url_rule(P + caminho, f.__name__, f, methods=["GET"])
        return f
    return deco


def meta_base(**extra):
    return dict(ultima_atualizacao=q.ultima_atualizacao(), gerado_em=iso(txt(agora())), simulado=True, aviso=AVISO_SIMULADO, **extra)


def resposta(dados, meta=None):
    m = meta_base()
    m.update(meta or {})
    return jsonify(data=dados, meta=m)


def erro(status, codigo, mensagem, campo=None):
    d = dict(codigo=codigo, mensagem=mensagem)
    if campo:
        d["campo"] = campo
    r = jsonify(erro=d)
    r.status_code = status
    return r


@app.errorhandler(q.ErroValidacao)
def _val(e):
    return erro(400, "pedido_invalido", str(e), e.campo)


@app.errorhandler(404)
def _404(e):
    return erro(404, "nao_encontrado", "Recurso ou caminho inexistente.")


@app.errorhandler(405)
def _405(e):
    return erro(405, "metodo_nao_permitido", "Método não permitido (a API é só de leitura: use GET).")


@app.errorhandler(Exception)
def _500(e):
    app.logger.exception(e)
    return erro(500, "erro_interno", "Erro interno do servidor.")


def _credencial():
    h = request.headers
    if h.get("X-API-Key"):
        return h["X-API-Key"]
    a = h.get("Authorization", "")
    if a.lower().startswith("bearer "):
        return a[7:]
    if a.lower().startswith("apikey "):
        return a[7:]
    return request.args.get("api_key")


@app.before_request
def _autenticar():
    g.t0 = time.time()
    g.chave = None
    rel = request.path
    if request.method == "OPTIONS" or rel in ("/", "/docs", "/openapi.json", P + "/health", P + "/auth/token"):
        return None
    if not rel.startswith(P):
        return None
    k = auth.validar(_credencial())
    if not k:
        r = erro(401, "nao_autenticado", "Credencial em falta ou inválida. Envie a chave em «X-API-Key: <chave>» ou «Authorization: Bearer <chave ou token>».")
        r.headers["WWW-Authenticate"] = 'Bearer realm="SONANGOL"'
        return r
    g.chave = k


@app.after_request
def _registar(r):
    try:
        if request.path.startswith(P):
            ms = int((time.time() - g.get("t0", time.time())) * 1000)
            with db.tx() as c:
                c.execute("INSERT INTO api_log(data_hora,chave_id,metodo,caminho,estado,ms,ip) VALUES(?,?,?,?,?,?,?)",
                          (txt(agora()), (g.get("chave") or {}).get("id"), request.method, request.full_path.rstrip("?")[:300], r.status_code, ms, request.remote_addr))
            if g.get("chave"):
                auth.registar_uso(g.chave["id"])
    except Exception:
        pass
    r.headers["Cache-Control"] = "no-store"
    r.headers["X-Dados-Simulados"] = "true"
    return r


def F():
    return request.args.to_dict()


# ------------------------------------------------------------------ metadados e autenticação
@app.route(P + "/health")
def health():
    from . import vivo
    return jsonify(estado="ok", servico="SONANGOL (simulada)", versao="1.1.0", hora=iso(txt(agora())), simulado=True, aviso=AVISO_SIMULADO,
                   modo_vivo=vivo.estado())


@app.route(P + "/auth/token", methods=["POST"])
def token():
    corpo = request.get_json(silent=True) or {}
    k = auth.validar(corpo.get("api_key") or request.headers.get("X-API-Key"))
    if not k:
        return erro(401, "nao_autenticado", "API Key inválida.")
    return jsonify(auth.emitir_token(k["id"]))


@rota("/meta", "Estado da plataforma, contagens e hora da última atualização.")
def meta():
    c = lambda t: db.um(f"SELECT COUNT(*) n FROM {t}")["n"]
    return resposta(dict(servico="SONANGOL (simulada)", versao="1.0.0", postos=c("postos"), instalacoes=c("instalacoes"), reservatorios=c("reservatorios"),
                         bombas=c("bombas"), entregas=c("entregas"), movimentos=c("movimentos"), produtos=list(PRODUTOS),
                         gerado_em=iso(db.cfg_get("gerado_em"))))


# ------------------------------------------------------------------ geografia e catálogos
@rota("/provincias", "As 21 províncias de Angola, com número de municípios e de postos.")
def r_provincias():
    d = q.listar_provincias()
    return resposta(d, dict(total=len(d)))


@rota("/municipios", "Municípios (326), com população e número de postos.", [("provincia", "Filtra por província.")] + PAGINACAO)
def r_municipios():
    d, m = q.listar_municipios(F())
    return resposta(d, m)


@rota("/empresas", "Empresas (operadoras, distribuidoras, refinação, logística).", PAGINACAO)
def r_empresas():
    d, m = q.listar_empresas(F())
    return resposta(d, m)


@rota("/produtos", "Catálogo de produtos e preços regulados de referência.")
def r_produtos():
    d = q.listar_produtos()
    return resposta(d, dict(total=len(d)))


@rota("/instalacoes", "Refinarias, terminais, bases logísticas e centros de distribuição.",
      [("tipo", "Refinaria, Terminal de armazenamento, Base logística, Centro de distribuição."), ("provincia", ""), ("empresa", "")] + PAGINACAO)
def r_instalacoes():
    d, m = q.listar_instalacoes(F())
    return resposta(d, m)


# ------------------------------------------------------------------ rede de postos
@rota("/postos", "Rede de postos de abastecimento.",
      FILTROS_POSTO + [("disponivel", "Com «produto»: true/false filtra por disponibilidade desse produto."),
                       ("atualizado_desde", "Só postos atualizados após esta data/hora."), ("incluir", "«disponibilidade» junta a disponibilidade por produto.")] + PAGINACAO,
      campos="id, nome, empresa, provincia, municipio, lat, lon, tipo, servicos[], produtos[], estado, situacao, motivo, atualizado_em")
def r_postos():
    f = F()
    d, m = q.listar_postos(f, detalhe="disponibilidade" in (f.get("incluir") or ""))
    return resposta(d, m)


@app.route(P + "/postos/<codigo>")
def r_posto(codigo):
    d = q.obter_posto(codigo)
    if not d:
        return erro(404, "nao_encontrado", f"Posto «{codigo}» inexistente.")
    return resposta(d)


ENDPOINTS.append(dict(caminho="/postos/{id}", resumo="Ficha completa de um posto (disponibilidade, reservatórios e bombas).", params=[], publico=False,
                      campos="…, disponibilidade[], reservatorios[], bombas[]", nome="r_posto"))


@rota("/disponibilidade", "Disponibilidade por posto e produto (derivada dos reservatórios e das bombas).",
      FILTROS_POSTO[:3] + [FILTROS_POSTO[3], ("disponivel", "true/false."), ("atualizado_desde", ""),
                           ("incluir_nao_comercializados", "true: inclui linhas com disponibilidade 0 para produtos que o posto não vende.")] + PAGINACAO,
      campos="posto_id, produto, comercializado, disponivel, estado, stock_l, capacidade_l, ocupacao_pct, bombas_operacionais, atualizado_em")
def r_disp():
    f = F()
    d, m = q.listar_disponibilidade(f, str(f.get("incluir_nao_comercializados", "")).lower() in ("1", "true", "sim"))
    return resposta(d, m)


@rota("/reservatorios", "Reservatórios e tanques (de postos e de instalações).",
      [("posto", "Código do posto."), ("instalacao", "Código da instalação."), ("proprietario", "posto | instalacao"), ("provincia", ""), ("municipio", ""),
       ("empresa", ""), ("produto", ""), ("estado", "Operacional, Em manutenção, Fora de serviço."), ("stock_reduzido", "true: abaixo de 25% da capacidade."),
       ("atualizado_desde", "")] + PAGINACAO,
      campos="reservatorio_id, posto_id, instalacao_id, produto, capacidade_l, litros, ocupacao_pct, minimo_operacional_l, estado, atualizado_em")
def r_res():
    d, m = q.listar_reservatorios(F())
    return resposta(d, m)


@rota("/bombas", "Estado das bombas dos postos.", [("posto", ""), ("provincia", ""), ("empresa", ""), ("produto", ""), ("estado", "Operacional, Avariada.")] + PAGINACAO)
def r_bombas():
    d, m = q.listar_bombas(F())
    return resposta(d, m)


@rota("/precos", "Preços por produto (regulados, simulados).", [("produto", "")] + PAGINACAO)
def r_precos():
    d, m = q.listar_precos(F())
    return resposta(d, m)


# ------------------------------------------------------------------ distribuição
@rota("/movimentos", "Histórico de movimentações de stock (receções, vendas, distribuição, ajustes).",
      [("produto", ""), ("tipo", "Receção, Venda, Distribuição, Ajuste, Saldo inicial."), ("posto", ""), ("instalacao", ""), ("provincia", ""), ("empresa", ""),
       ("ordem", "asc | desc (omissão desc).")] + PERIODO + PAGINACAO)
def r_mov():
    d, m = q.listar_movimentos(F())
    return resposta(d, m)


@rota("/entregas", "Distribuição e abastecimento: entregas de combustível.",
      [("estado", "Planeada, Em trânsito, Entregue, Cancelada."), ("produto", ""), ("provincia", "Província de destino."), ("empresa", "")] + PERIODO + PAGINACAO,
      campos="id, produto, quantidade_l, origem, destino, veiculo, estado, data_saida, data_prevista_chegada, data_chegada")
def r_ent():
    d, m = q.listar_entregas(F())
    return resposta(d, m)


# ------------------------------------------------------------------ indicadores
@rota("/indicadores", "Indicadores operacionais globais (postos, volumes, produtos, situação geral).", [("provincia", ""), ("empresa", "")] + PERIODO)
def r_ind():
    return resposta(q.indicadores(F()))


@rota("/indicadores/provincias", "Indicadores por província (postos, disponibilidade por produto, necessidade de abastecimento).", [("empresa", "")] + PERIODO)
def r_ind_prov():
    d = q.indicadores_provincias(F())
    return resposta(d, dict(total=len(d)))


@rota("/indicadores/evolucao-stocks", "Evolução diária dos stocks por produto.", PERIODO)
def r_evol():
    d = q.evolucao_stocks(F())
    return resposta(d, dict(total=len(d)))


# ------------------------------------------------------------------ compatibilidade direta com o SIG-CAD (padrão único, campos canónicos)
def _todos(fn, f):
    f = dict(f, page_size=q.PAGINA_MAX)
    d, m = fn(f)
    return d, m


@rota("/stations", "[SIG-CAD] Postos no padrão único do SIG-CAD.", FILTROS_POSTO[:3] + PAGINACAO,
      campos="id, nome, provincia, municipio, lat, lon, tipo, servicos, estado, produtos, atualizado_em")
def sg_stations():
    d, m = q.listar_postos(F())
    out = [dict(id=x["id"], nome=x["nome"], provincia=x["provincia"], municipio=x["municipio"], lat=x["lat"], lon=x["lon"], tipo=x["tipo"],
                servicos="|".join(x["servicos"]), estado="Operacional" if x["estado"] == "Operacional" else "Inoperacional",
                produtos="|".join(x["produtos"]), atualizado_em=x["atualizado_em"]) for x in d]
    return resposta(out, m)


@rota("/availability", "[SIG-CAD] Disponibilidade por posto e produto (só produtos comercializados).", FILTROS_POSTO[:4] + PAGINACAO,
      campos="posto_id, produto, disponivel, stock_l, atualizado_em")
def sg_avail():
    d, m = q.listar_disponibilidade(F())
    return resposta([dict(posto_id=x["posto_id"], produto=x["produto"], disponivel=x["disponivel"], stock_l=x["stock_l"],
                          atualizado_em=x["atualizado_em"]) for x in d], m)


@rota("/tanks", "[SIG-CAD] Reservatórios dos postos.", FILTROS_POSTO[:4] + PAGINACAO,
      campos="posto_id, reservatorio_id, produto, capacidade_l, litros, atualizado_em")
def sg_tanks():
    f = dict(F(), proprietario="posto")
    d, m = q.listar_reservatorios(f)
    return resposta([dict(posto_id=x["posto_id"], reservatorio_id=x["reservatorio_id"].split("/")[-1], produto=x["produto"],
                          capacidade_l=x["capacidade_l"], litros=x["litros"], atualizado_em=x["atualizado_em"]) for x in d], m)


@rota("/pumps", "[SIG-CAD] Estado das bombas.", FILTROS_POSTO[:1] + [("posto", ""), ("produto", "")] + PAGINACAO,
      campos="posto_id, bomba_id, produto, estado, atualizado_em")
def sg_pumps():
    d, m = q.listar_bombas(F())
    return resposta([dict(posto_id=x["posto_id"], bomba_id=x["bomba_id"].split("/")[-1], produto=x["produto"], estado=x["estado"],
                          atualizado_em=x["atualizado_em"]) for x in d], m)


@rota("/prices", "[SIG-CAD] Preços por produto.", [("produto", "")] + PAGINACAO, campos="produto, preco, unidade, atualizado_em")
def sg_prices():
    d, m = q.listar_precos(F())
    return resposta([dict(produto=x["produto"], preco=x["preco"], unidade=x["unidade"], atualizado_em=x["atualizado_em"]) for x in d], m)


# ------------------------------------------------------------------ Excel
@rota("/export/xlsx", "Descarrega um ficheiro Excel. «categoria»: completo, postos, disponibilidade, reservatorios, bombas, precos, entregas, "
      "movimentos, indicadores, instalacoes, sigcad (pacote compatível com a importação do SIG-CAD).",
      [("categoria", "Ver acima (omissão: completo)."), ("provincia", "Só para «postos» e «reservatorios»."), ("produto", "Só para stocks."), ("empresa", "")] + PERIODO)
def r_xlsx():
    f = F()
    cat = (f.get("categoria") or "completo").lower()
    try:
        dados = excel.exportar(cat, f)
    except KeyError:
        return erro(400, "pedido_invalido", f"Categoria desconhecida «{cat}».", "categoria")
    return Response(dados, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="sonangol_{cat}_{agora():%Y%m%d_%H%M}.xlsx"'})


# ------------------------------------------------------------------ documentação
def openapi() -> dict:
    paths = {}
    for e in ENDPOINTS:
        paths[P + e["caminho"]] = {"get": dict(summary=e["resumo"], description=("Campos: " + e["campos"]) if e["campos"] else "",
                                               parameters=[dict(name=n, **{"in": "query"}, description=d, schema=dict(type="string")) for n, d in e["params"]]
                                               + ([dict(name="id", **{"in": "path"}, required=True, schema=dict(type="string"))] if "{id}" in e["caminho"] else []),
                                               responses={"200": dict(description="OK"), "400": dict(description="Pedido inválido"),
                                                          "401": dict(description="Não autenticado")})}
    paths[P + "/auth/token"] = {"post": dict(summary="Troca uma API Key por um token Bearer (1 hora).", requestBody=dict(content={"application/json": dict(
        schema=dict(type="object", properties=dict(api_key=dict(type="string"))))}), responses={"200": dict(description="Token")})}
    return dict(openapi="3.0.3", info=dict(title="SONANGOL API (dados simulados)", version="1.0.0", description=AVISO_SIMULADO),
                servers=[dict(url="/")], paths=paths,
                components=dict(securitySchemes=dict(ApiKey=dict(type="apiKey", name="X-API-Key", **{"in": "header"}), Bearer=dict(type="http", scheme="bearer"))),
                security=[dict(ApiKey=[]), dict(Bearer=[])])


@app.route("/openapi.json")
def r_openapi():
    return jsonify(openapi())


@app.route("/docs")
def r_docs():
    import html
    linhas = []
    for e in ENDPOINTS:
        ps = "".join(f"<tr><td><code>{html.escape(n)}</code></td><td>{html.escape(d)}</td></tr>" for n, d in e["params"])
        linhas.append(f"<div class='ep'><h3><span class='m'>GET</span> {html.escape(P + e['caminho'])}</h3><p>{html.escape(e['resumo'])}</p>"
                      + (f"<p><b>Campos:</b> <code>{html.escape(e['campos'])}</code></p>" if e["campos"] else "")
                      + (f"<table>{ps}</table>" if ps else "") + "</div>")
    pagina = f"""<!doctype html><html lang="pt"><head><meta charset="utf-8"><title>SONANGOL API — documentação</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#1b2430}}code{{background:#eef1f5;padding:1px 5px;border-radius:4px}}
.aviso{{background:#fff4d6;border:1px solid #e6c34d;padding:10px 14px;border-radius:8px}}.ep{{border:1px solid #dde2ea;border-radius:10px;padding:6px 16px;margin:12px 0}}
.m{{background:#0b5cad;color:#fff;border-radius:5px;padding:1px 7px;font-size:12px}}table{{border-collapse:collapse;margin-bottom:10px}}td{{border-top:1px solid #eee;padding:3px 10px 3px 0;vertical-align:top}}
pre{{background:#10151c;color:#e8edf3;padding:12px;border-radius:8px;overflow:auto}}</style></head><body>
<h1>SONANGOL API <small style="font-weight:400">v1.0</small></h1><p class="aviso"><b>{html.escape(AVISO_SIMULADO)}</b></p>
<h2>Autenticação</h2><p>Todos os endpoints (exceto <code>/api/v1/health</code>) exigem uma chave gerada no painel (separador «Painel de APIs»).</p>
<pre>curl -H "X-API-Key: SUA_CHAVE" "http://127.0.0.1:8000/api/v1/postos?provincia=Luanda&amp;page_size=20"
curl -H "Authorization: Bearer SUA_CHAVE" http://127.0.0.1:8000/api/v1/indicadores
curl -X POST -H "Content-Type: application/json" -d '{{"api_key":"SUA_CHAVE"}}' http://127.0.0.1:8000/api/v1/auth/token   # token Bearer de 1 hora</pre>
<h2>Respostas</h2><p>JSON <code>{{"data": …, "meta": {{page, page_size, total, total_paginas, tem_proxima, ultima_atualizacao, simulado}}}}</code>. Datas em ISO 8601 com fuso de Luanda (+01:00).
Erros: <code>{{"erro": {{"codigo", "mensagem", "campo"}}}}</code> com HTTP 400 (pedido inválido), 401 (sem/inválida credencial), 404, 500.
Identificadores únicos: postos <code>SD-LDA-0001</code>, reservatórios <code>SD-LDA-0001/R01</code>, bombas <code>SD-LDA-0001/B01</code>, entregas <code>ENT-AAAAMMDD-NNNNN</code>.</p>
<h2>Integração com o SIG-CAD</h2><p>Em «🔌 Integrações API» do SIG-CAD: Base URL = endereço desta API (<code>…/api/v1</code>), tipo <b>API Key</b>, cabeçalho <code>X-API-Key</code>.
Os endpoints <code>/stations</code>, <code>/availability</code>, <code>/tanks</code>, <code>/pumps</code> e <code>/prices</code> já devolvem o padrão único do SIG-CAD: o mapeamento por omissão funciona sem alterações.</p>
<h2>Endpoints</h2>{''.join(linhas)}<p>Especificação OpenAPI 3: <a href="/openapi.json">/openapi.json</a></p></body></html>"""
    return Response(pagina, mimetype="text/html")


@app.route("/")
def raiz():
    return jsonify(servico="SONANGOL (simulada)", docs="/docs", openapi="/openapi.json", api=P, aviso=AVISO_SIMULADO)
