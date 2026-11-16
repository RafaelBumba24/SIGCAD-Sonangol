"""Painel de administração da plataforma SONANGOL (dados SIMULADOS) — Streamlit.
Executar:  streamlit run painel.py"""
import hashlib
import hmac
import os
import time

import pandas as pd
import streamlit as st

from sonangol import auth, consultas as q, db, excel, operacoes as ops, seed
from sonangol.config import (API_HOST, API_PORTA, AVISO_SIMULADO, ESTADOS_BOMBA, ESTADOS_ENTREGA, ESTADOS_POSTO, ESTADOS_RESERVATORIO, NOMES_PRODUTOS,
                             TIPOS_POSTO, agora, txt)

st.set_page_config(page_title="SONANGOL · Painel (simulado)", page_icon="🛢️", layout="wide", initial_sidebar_state="auto")
db.iniciar()
if not db.um("SELECT 1 FROM sqlite_master WHERE name='postos'") or not db.um("SELECT 1 FROM postos LIMIT 1"):
    with st.spinner("A gerar a base de dados de demonstração (500 postos)…"):
        seed.gerar()

st.markdown("""<style>
.block-container{padding-top:1.4rem} .aviso{background:#fff4d6;border:1px solid #e6c34d;border-radius:8px;padding:8px 14px;font-size:.88rem;margin-bottom:10px}
.kpi{border:1px solid #dde2ea;border-radius:12px;padding:10px 14px;background:#fff}.kpi .v{font-size:1.7rem;font-weight:700;color:#0b3a6f}.kpi .l{color:#5b6877;font-size:.82rem}
html,body{max-width:100vw;overflow-x:hidden}.stMarkdown table{display:block;max-width:100%;overflow-x:auto}
@media (max-width:1024px){.block-container{padding-left:1.1rem;padding-right:1.1rem}div[data-testid="stHorizontalBlock"]:has(.kpi){flex-wrap:wrap!important;row-gap:.7rem!important}div[data-testid="stHorizontalBlock"]:has(.kpi)>div[data-testid="stColumn"]{flex:1 1 calc(33% - 1rem)!important;min-width:calc(33% - 1rem)!important}}
@media (max-width:640px){h1{font-size:1.7rem!important}.block-container{padding:3.2rem .8rem 2rem .8rem}div[data-testid="stHorizontalBlock"]:has(.kpi)>div[data-testid="stColumn"]{flex:1 1 calc(50% - .8rem)!important;min-width:calc(50% - .8rem)!important}.kpi .v{font-size:1.25rem}.stButton>button,.stDownloadButton>button,div[data-testid="stFormSubmitButton"] button{width:100%;min-height:44px}input,textarea{font-size:16px!important}header[data-testid="stHeader"]{background:#fff}}
@media (prefers-color-scheme: dark){.kpi{background:#161b22;border-color:#30363d}.kpi .v{color:#7db4ff}.aviso{background:#3a3112;border-color:#8a7424}}
</style>""", unsafe_allow_html=True)

def _senha_admin():
    try:
        return str(st.secrets["sonangol"]["admin_senha"])      # Streamlit Cloud → Settings → Secrets
    except Exception:
        return os.environ.get("SONANGOL_ADMIN_SENHA", "sonangol-demo")


SENHA = _senha_admin()


@st.cache_resource
def _modo_vivo():
    """Mantém as leituras «frescas» também quando o painel corre sozinho (ex.: Streamlit Community Cloud, sem run_api.py)."""
    try:
        from sonangol import vivo
        vivo.iniciar()
        return True
    except Exception:
        return False


_modo_vivo()


def kpi(col, rotulo, valor, sub=""):
    col.markdown(f"<div class='kpi'><div class='l'>{rotulo}</div><div class='v'>{valor}</div><div class='l'>{sub}</div></div>", unsafe_allow_html=True)


def n(x):
    return f"{x:,.0f}".replace(",", " ")


# ----------------------------------------------------------------- acesso
if not st.session_state.get("ok"):
    st.title("🛢️ SONANGOL · Painel de administração")
    st.markdown(f"<div class='aviso'><b>{AVISO_SIMULADO}</b></div>", unsafe_allow_html=True)
    with st.form("login"):
        senha = st.text_input("Palavra-passe de administração", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            if hmac.compare_digest(hashlib.sha256(senha.encode()).digest(), hashlib.sha256(SENHA.encode()).digest()):
                st.session_state["ok"] = True
                st.rerun()
            st.error("Palavra-passe incorreta.")
    st.caption("Por omissão: «sonangol-demo» (altere com a variável SONANGOL_ADMIN_SENHA).")
    st.stop()

st.sidebar.markdown("### 🛢️ SONANGOL")
st.sidebar.caption("Plataforma empresarial · **dados simulados**")
PAG = st.sidebar.radio("Menu", ["📊 Dashboard", "⛽ Postos e reservatórios", "🏭 Instalações e entregas", "🔌 Painel de APIs", "📗 Excel",
                                "🧪 Simulador", "🧾 Auditoria"], label_visibility="collapsed")
st.sidebar.caption(f"Última atualização dos dados: {db.cfg_get('ultima_atualizacao', '—')}")
if st.sidebar.button("Terminar sessão"):
    st.session_state.clear()
    st.rerun()
st.markdown(f"<div class='aviso'><b>DADOS SIMULADOS</b> — não são informações oficiais nem reais da Sonangol.</div>", unsafe_allow_html=True)
UTIL = "admin"


def erro_op(fn, *a, ok="Feito.", **k):
    try:
        r = fn(*a, **k)
        st.success(ok)
        return r
    except q.ErroValidacao as e:
        st.error(str(e))
    except Exception as e:  # noqa: BLE001
        st.error(f"Erro: {e}")


# ----------------------------------------------------------------- dashboard
if PAG.startswith("📊"):
    st.title("Dashboard empresarial")
    c1, c2, c3 = st.columns(3)
    emp = c1.selectbox("Empresa", ["(todas)"] + [e["nome"] for e in q.listar_empresas({})[0] if e["postos"]], key="d_emp")
    prov = c2.selectbox("Província", ["(todas)"] + q.provincias(), key="d_prov")
    dias = c3.selectbox("Período", [1, 7, 15, 30], index=1, format_func=lambda d: f"Últimos {d} dias", key="d_dias")
    f = dict(desde=(agora() - pd.Timedelta(days=dias)).strftime("%Y-%m-%d"))
    if emp != "(todas)":
        f["empresa"] = emp
    if prov != "(todas)":
        f["provincia"] = prov
    ind = q.indicadores(f)
    p, v = ind["postos"], ind["volumes"]
    k = st.columns(6)
    kpi(k[0], "Postos registados", n(p["total"]), f"{p['operacionais']} operacionais")
    kpi(k[1], "Instalações", n(db.um("SELECT COUNT(*) n FROM instalacoes")["n"]), "refinarias, terminais, bases, centros")
    kpi(k[2], "Armazenado (total)", f"{v['armazenado_total_l'] / 1e6:,.1f} M L".replace(",", " "), "postos + instalações")
    kpi(k[3], "Distribuído", f"{v['distribuido_periodo_l'] / 1e6:,.1f} M L".replace(",", " "), f"últimos {dias} dias")
    kpi(k[4], "Sem combustível", n(p["sem_combustivel"]), f"{p['com_disponibilidade_reduzida']} com stock reduzido")
    kpi(k[5], "Situação geral", ind["situacao_geral"]["classificacao"], f"{ind['situacao_geral']['postos_operacionais_sem_combustivel_pct']}% sem combustível")
    st.write("")
    a, b = st.columns(2)
    with a:
        st.subheader("Disponibilidade por produto")
        dfp = pd.DataFrame(ind["produtos"])[["produto", "com_stock", "sem_stock", "stock_reduzido"]].set_index("produto")
        st.bar_chart(dfp)
    with b:
        st.subheader("Situação operacional por província")
        dfv = pd.DataFrame(q.indicadores_provincias(f if emp != "(todas)" else dict(desde=f["desde"])))
        st.bar_chart(dfv.set_index("provincia")[["operacionais", "inoperacionais", "encerrados"]])
    a, b = st.columns(2)
    with a:
        st.subheader("Evolução dos stocks (milhões de L)")
        ev = pd.DataFrame(q.evolucao_stocks(dict(desde=(agora() - pd.Timedelta(days=30)).strftime("%Y-%m-%d"))))
        if not ev.empty:
            ev["M L"] = (ev["stock_postos_l"] + ev["stock_instalacoes_l"]) / 1e6
            st.line_chart(ev.pivot(index="data", columns="produto", values="M L"))
    with b:
        st.subheader("Volumes por produto no período")
        dv = pd.DataFrame(ind["produtos"]).set_index("produto")[["vendido_periodo_l", "distribuido_periodo_l", "recebido_periodo_l"]] / 1e6
        st.bar_chart(dv)
    st.subheader("⚠️ Alertas de stock reduzido (reservatórios de postos abaixo de 25 %)")
    al = pd.DataFrame(q.alertas_stock(100))
    if al.empty:
        st.success("Sem alertas.")
    else:
        st.dataframe(al[["posto_id", "pertence_a", "provincia", "produto", "litros", "capacidade_l", "ocupacao_pct", "estado"]].rename(
            columns=dict(pertence_a="posto", litros="litros (L)", capacidade_l="capacidade (L)", ocupacao_pct="ocupação %")), hide_index=True, width="stretch")
    st.subheader("Histórico de operações recentes")
    mv = pd.DataFrame(q.listar_movimentos(dict(page_size=30))[0])
    st.dataframe(mv[["data_hora", "tipo", "posto_id", "instalacao_id", "produto", "variacao_l", "stock_apos_l", "entrega_id"]], hide_index=True, width="stretch")

# ----------------------------------------------------------------- postos
elif PAG.startswith("⛽"):
    st.title("Postos, reservatórios e bombas")
    t1, t2, t3 = st.tabs(["📋 Lista e edição", "➕ Novo posto", "🛢️ Reservatórios, bombas e stock"])
    with t1:
        c = st.columns(5)
        prov = c[0].selectbox("Província", ["(todas)"] + q.provincias(), key="p_prov")
        mun_opts = ["(todos)"] + ([m["nome"] for m in q.listar_municipios(dict(provincia=prov, page_size=1000))[0]] if prov != "(todas)" else [])
        mun = c[1].selectbox("Município", mun_opts, key="p_mun")
        emp = c[2].selectbox("Empresa", ["(todas)"] + [e["nome"] for e in q.listar_empresas({})[0] if e["postos"]], key="p_emp")
        est = c[3].selectbox("Estado", ["(todos)"] + ESTADOS_POSTO, key="p_est")
        prod = c[4].selectbox("Vende", ["(todos)"] + NOMES_PRODUTOS, key="p_prod")
        f = dict(page_size=2000)
        for k_, val in (("provincia", prov), ("municipio", mun), ("empresa", emp), ("estado", est), ("produto", prod)):
            if val not in ("(todas)", "(todos)"):
                f[k_] = val
        rows, meta = q.listar_postos(f)
        st.caption(f"{meta['total']} posto(s)")
        df = pd.DataFrame(rows)
        if not df.empty:
            st.dataframe(df[["id", "nome", "empresa", "provincia", "municipio", "tipo", "estado", "produtos", "atualizado_em"]], hide_index=True, width="stretch", height=300)
            sel = st.selectbox("Posto a gerir", [r["id"] for r in rows], format_func=lambda i: f"{i} — " + next(r["nome"] for r in rows if r["id"] == i), key="p_sel")
            d = q.obter_posto(sel)
            st.markdown(f"#### {d['nome']}  ·  {d['estado']}")
            e1, e2, e3 = st.columns(3)
            nome = e1.text_input("Nome", d["nome"], key=f"e_nome_{sel}")
            estado = e2.selectbox("Estado", ESTADOS_POSTO, index=ESTADOS_POSTO.index(d["estado"]), key=f"e_est_{sel}")
            motivo = e3.text_input("Motivo (se não operacional)", d["motivo"] or "", key=f"e_mot_{sel}")
            prods = st.multiselect("Produtos comercializados", NOMES_PRODUTOS, default=d["produtos"], key=f"e_pr_{sel}")
            serv = st.text_input("Serviços (separados por |)", "|".join(d["servicos"]), key=f"e_sv_{sel}")
            b1, b2, _ = st.columns([1, 1, 4])
            pid = db.um("SELECT id FROM postos WHERE codigo=?", (sel,))["id"]
            if b1.button("💾 Guardar alterações", type="primary", key=f"e_g_{sel}"):
                erro_op(ops.atualizar_posto, pid, dict(nome=nome, estado=estado, motivo=motivo, produtos=prods, servicos=serv), UTIL, ok="Posto atualizado.")
            if b2.button("🗑 Eliminar posto", key=f"e_d_{sel}"):
                st.session_state[f"conf_{sel}"] = True
            if st.session_state.get(f"conf_{sel}"):
                st.warning("Elimina o posto, os seus reservatórios, bombas e movimentos. Confirmar?")
                if st.button("Sim, eliminar definitivamente", key=f"e_dd_{sel}"):
                    erro_op(ops.eliminar_posto, pid, UTIL, ok="Posto eliminado.")
                    st.session_state.pop(f"conf_{sel}")
                    st.rerun()
            st.markdown("**Disponibilidade atual**")
            st.dataframe(pd.DataFrame(d["disponibilidade"]), hide_index=True, width="stretch")
    with t2:
        with st.form("novo_posto"):
            a, b = st.columns(2)
            nome = a.text_input("Nome do posto")
            empresas = q.listar_empresas({})[0]
            emp = b.selectbox("Empresa", [e["uid"] for e in empresas], format_func=lambda u: next(e["nome"] for e in empresas if e["uid"] == u))
            prov = a.selectbox("Província", q.provincias(), key="np_prov")
            mun = b.selectbox("Município", [m["nome"] for m in q.listar_municipios(dict(provincia=prov, page_size=1000))[0]], key="np_mun")
            lat, lon = a.number_input("Latitude", value=0.0, format="%.5f"), b.number_input("Longitude", value=0.0, format="%.5f")
            tipo = a.selectbox("Tipo", TIPOS_POSTO)
            prods = b.multiselect("Produtos", NOMES_PRODUTOS, default=["Gasolina", "Gasóleo"])
            serv = st.text_input("Serviços (separados por |)")
            if st.form_submit_button("Criar posto", type="primary"):
                r = erro_op(ops.criar_posto, dict(nome=nome, empresa_id=emp, provincia=prov, municipio=mun, lat=lat or None, lon=lon or None, tipo=tipo,
                                                  produtos=prods, servicos=serv), UTIL, ok="Posto criado. Adicione agora os reservatórios e bombas.")
    with t3:
        cod = st.text_input("Código do posto", "SD-LDA-0001", key="r_cod")
        d = q.obter_posto(cod) if cod else None
        if not d:
            st.info("Indique o código de um posto existente (ex.: SD-LDA-0001).")
        else:
            pid = db.um("SELECT id FROM postos WHERE codigo=?", (cod,))["id"]
            st.markdown(f"**{d['nome']}** · {d['estado']}")
            res = pd.DataFrame(d["reservatorios"])
            st.dataframe(res[["reservatorio_id", "produto", "capacidade_l", "litros", "ocupacao_pct", "minimo_operacional_l", "estado"]], hide_index=True, width="stretch")
            if not res.empty:
                a, b, c_ = st.columns(3)
                rsel = a.selectbox("Reservatório", list(res["uid"]), format_func=lambda u: res.loc[res.uid == u, "reservatorio_id"].iloc[0] + " · " + res.loc[res.uid == u, "produto"].iloc[0], key="r_sel")
                tipo_mov = b.selectbox("Operação", ["Receção", "Venda", "Definir stock (ajuste)"], key="r_tipo")
                qtd = c_.number_input("Quantidade (L)", min_value=0.0, step=500.0, key="r_qtd")
                if st.button("Aplicar", type="primary", key="r_ap"):
                    def f_():
                        with db.tx() as cx:
                            if tipo_mov.startswith("Definir"):
                                ops.definir_stock(cx, rsel, qtd, "Ajuste manual (painel)", UTIL)
                            else:
                                ops.aplicar_movimento(cx, rsel, tipo_mov, qtd, obs="Registo manual (painel)")
                    erro_op(f_, ok="Movimento registado.")
                a, b, c_ = st.columns(3)
                novo_est = a.selectbox("Estado do reservatório", ESTADOS_RESERVATORIO, key="r_nest")
                if b.button("Atualizar estado", key="r_ue"):
                    erro_op(ops.atualizar_reservatorio, rsel, None, None, novo_est, UTIL)
                if c_.button("🗑 Eliminar reservatório (vazio)", key="r_del"):
                    erro_op(ops.eliminar_reservatorio, rsel, UTIL, ok="Reservatório eliminado.")
            with st.expander("➕ Novo reservatório"):
                a, b, c_ = st.columns(3)
                pr = a.selectbox("Produto", d["produtos"] or NOMES_PRODUTOS, key="nr_pr")
                cap = b.number_input("Capacidade (L)", min_value=1000.0, value=30000.0, step=1000.0, key="nr_cap")
                q0 = c_.number_input("Quantidade inicial (L)", min_value=0.0, value=0.0, step=500.0, key="nr_q")
                if st.button("Criar reservatório", key="nr_b"):
                    erro_op(ops.criar_reservatorio, pid, None, pr, cap, q0, None, None, UTIL, ok="Reservatório criado.")
            st.markdown("**Bombas**")
            bo = pd.DataFrame(d["bombas"])
            st.dataframe(bo[["bomba_id", "produto", "estado", "atualizado_em"]], hide_index=True, width="stretch")
            if not bo.empty:
                a, b, c_ = st.columns(3)
                bsel = a.selectbox("Bomba", list(bo["uid"]), format_func=lambda u: bo.loc[bo.uid == u, "bomba_id"].iloc[0], key="b_sel")
                be = b.selectbox("Novo estado", ESTADOS_BOMBA, key="b_est")
                if c_.button("Atualizar bomba", key="b_ap"):
                    erro_op(ops.estado_bomba, bsel, be, UTIL)
            with st.expander("➕ Nova bomba"):
                pr = st.selectbox("Produto", d["produtos"] or NOMES_PRODUTOS, key="nb_pr")
                if st.button("Criar bomba", key="nb_b"):
                    erro_op(ops.criar_bomba, pid, pr, "Operacional", UTIL, ok="Bomba criada.")

# ----------------------------------------------------------------- instalações e entregas
elif PAG.startswith("🏭"):
    st.title("Instalações e distribuição")
    t1, t2 = st.tabs(["🏭 Instalações", "🚚 Entregas"])
    with t1:
        tp = st.selectbox("Tipo", ["(todos)", "Refinaria", "Terminal de armazenamento", "Base logística", "Centro de distribuição"])
        rows = q.listar_instalacoes(dict(page_size=500, **({} if tp == "(todos)" else dict(tipo=tp))))[0]
        st.dataframe(pd.DataFrame(rows)[["id", "nome", "tipo", "empresa", "provincia", "estado", "capacidade_l", "stock_l", "ocupacao_pct"]], hide_index=True, width="stretch")
        sel = st.selectbox("Ver reservatórios de", [r["id"] for r in rows], format_func=lambda i: next(r["nome"] for r in rows if r["id"] == i))
        rs = q.listar_reservatorios(dict(instalacao=sel))[0]
        st.dataframe(pd.DataFrame(rs)[["reservatorio_id", "produto", "capacidade_l", "litros", "ocupacao_pct", "estado"]], hide_index=True, width="stretch")
    with t2:
        c = st.columns(3)
        est = c[0].selectbox("Estado", ["(todos)"] + ESTADOS_ENTREGA, index=2)
        pr = c[1].selectbox("Produto", ["(todos)"] + NOMES_PRODUTOS, key="en_pr")
        f = dict(page_size=300)
        if est != "(todos)":
            f["estado"] = est
        if pr != "(todos)":
            f["produto"] = pr
        rows, meta = q.listar_entregas(f)
        st.caption(f"{meta['total']} entrega(s) · a mostrar {len(rows)}")
        dfe = pd.DataFrame(rows)
        if not dfe.empty:
            st.dataframe(dfe[["id", "produto", "quantidade_l", "origem", "destino", "veiculo", "estado", "data_saida", "data_prevista_chegada", "data_chegada"]], hide_index=True, width="stretch", height=320)
            abertas = [r for r in rows if r["estado"] in ("Planeada", "Em trânsito")]
            if abertas:
                a, b, c_ = st.columns(3)
                e_sel = a.selectbox("Entrega aberta", [r["uid"] for r in abertas], format_func=lambda u: next(r["id"] + " · " + r["estado"] for r in abertas if r["uid"] == u))
                novo = b.selectbox("Passar a", ["Em trânsito", "Entregue", "Cancelada"])
                if c_.button("Aplicar", type="primary", key="en_ap"):
                    erro_op(ops.avancar_entrega, e_sel, novo, UTIL, ok="Entrega atualizada (stock ajustado).")
        with st.expander("➕ Nova entrega"):
            insts = q.listar_instalacoes(dict(tipo="Centro de distribuição", page_size=100))[0]
            a, b = st.columns(2)
            o = a.selectbox("Origem (centro de distribuição)", [i["uid"] for i in insts], format_func=lambda u: next(i["nome"] for i in insts if i["uid"] == u))
            dest = b.text_input("Reservatório de destino (ex.: SD-LDA-0001/R01)")
            qtd = st.number_input("Quantidade (L)", min_value=1000.0, value=10000.0, step=1000.0)
            if st.button("Criar entrega", key="en_new"):
                r_ = db.um("SELECT r.id FROM reservatorios r JOIN postos p ON p.id=r.posto_id WHERE p.codigo || '/' || r.codigo=?", (dest.strip(),))
                if not r_:
                    st.error("Reservatório de destino inexistente.")
                else:
                    erro_op(ops.criar_entrega, o, r_["id"], qtd, None, 6.0, "", UTIL, ok="Entrega criada (Planeada).")

# ----------------------------------------------------------------- painel de APIs
elif PAG.startswith("🔌"):
    st.title("Painel de APIs")
    base = f"http://{API_HOST}:{API_PORTA}"
    try:
        import urllib.request
        with urllib.request.urlopen(f"{base}/api/v1/health", timeout=2) as r_:
            st.success(f"API a correr em {base} · documentação: {base}/docs")
    except Exception:
        st.warning(f"A API não está a responder em {base}. Arranque-a com:  `python run_api.py`  (o painel funciona na mesma; só o teste por HTTP precisa dela).")
    t1, t2, t3, t4 = st.tabs(["🔑 Chaves de acesso", "🧪 Testar a API", "📘 Endpoints", "🔗 Ligar ao SIG-CAD"])
    with t1:
        st.caption("A chave é mostrada uma única vez, ao ser criada; na base de dados fica só o seu hash.")
        a, b = st.columns([3, 1])
        nome = a.text_input("Nome da chave", "SIG-CAD — teste", key="k_nome")
        if b.button("➕ Gerar nova chave", type="primary"):
            try:
                st.session_state["chave_nova"] = auth.criar_chave(nome)
            except ValueError as e:
                st.error(str(e))
        if st.session_state.get("chave_nova"):
            st.success("Copie a chave agora — não voltará a ser mostrada:")
            st.code(st.session_state["chave_nova"], language=None)
        ch = pd.DataFrame(auth.listar_chaves())
        if not ch.empty:
            st.dataframe(ch, hide_index=True, width="stretch")
            a, b, c_ = st.columns(3)
            cid = a.selectbox("Chave", list(ch["id"]), format_func=lambda i: ch.loc[ch.id == i, "nome"].iloc[0] + " (" + ch.loc[ch.id == i, "prefixo"].iloc[0] + "…)")
            if b.button("⏯ Ativar / desativar"):
                auth.definir_ativa(cid, not bool(ch.loc[ch.id == cid, "ativa"].iloc[0]))
                st.rerun()
            if c_.button("🗑 Eliminar chave"):
                auth.eliminar_chave(cid)
                st.rerun()
    with t2:
        from sonangol import api as api_mod
        chave = st.text_input("Chave de API", type="password", key="t_chave")
        caminho = st.text_input("Caminho + parâmetros", "/api/v1/postos?provincia=Luanda&page_size=3", key="t_cam")
        if st.button("▶ Executar pedido"):
            cl = api_mod.app.test_client()
            t0 = time.time()
            r_ = cl.get(caminho, headers={"X-API-Key": chave})
            st.caption(f"HTTP {r_.status_code} · {int((time.time() - t0) * 1000)} ms")
            st.json(r_.get_json() if r_.is_json else r_.data[:500].decode("utf-8", "replace"))
        st.caption(f"Equivalente em curl:  `curl -H \"X-API-Key: SUA_CHAVE\" \"{base}{caminho}\"`")
        lg = pd.DataFrame(db.consultar("SELECT data_hora, metodo, caminho, estado, ms, chave_id FROM api_log ORDER BY id DESC LIMIT 50"))
        st.markdown("**Últimos pedidos à API**")
        st.dataframe(lg, hide_index=True, width="stretch")
    with t3:
        from sonangol import api as api_mod
        rows = [dict(endpoint="GET /api/v1" + e["caminho"], descricao=e["resumo"], parametros=", ".join(p for p, _ in e["params"]) or "—") for e in api_mod.ENDPOINTS]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.markdown(f"Documentação completa: [{base}/docs]({base}/docs) · OpenAPI: [{base}/openapi.json]({base}/openapi.json)")
    with t4:
        st.markdown(f"""**Procedimento (API):**
1. Aqui, em «Chaves de acesso», gere uma chave e copie-a.
2. Abra o SIG-CAD (variável de ambiente `SIGCAD_INTEGRACOES_PERMITIR_LOCAL=1` para aceitar `http://localhost`) → **🔌 Integrações API → ➕ Adicionar / editar**.
3. Nome: `Sonangol` · Base URL: `{base}/api/v1` · Credencial: **API Key**, cabeçalho `X-API-Key`, cole a chave.
4. Em «Endpoints», ative Postos (`/stations`), Disponibilidade (`/availability`), Reservatórios (`/tanks`), Bombas (`/pumps`) e Preços (`/prices`) — o mapeamento já vem correto.
5. Guardar → **Testar ligação** → **Sincronizar agora** → ver os dados em «🏠 Visão Operacional» e na vertente Pública.

**Procedimento (Excel):** separador «📗 Excel» → exportar «Pacote SIG-CAD» → no SIG-CAD: **🔌 Integrações API → 📄 Importar Excel / CSV**.""")

# ----------------------------------------------------------------- Excel
elif PAG.startswith("📗"):
    st.title("Exportação e importação Excel")
    t1, t2 = st.tabs(["⬇ Exportar", "⬆ Importar"])
    with t1:
        c = st.columns(4)
        cat = c[0].selectbox("Categoria", ["sigcad", "completo", "postos", "disponibilidade", "reservatorios", "bombas", "precos", "instalacoes", "entregas", "movimentos", "indicadores"],
                             format_func=lambda x: {"sigcad": "Pacote SIG-CAD (5 folhas)", "completo": "Base de dados completa"}.get(x, x.capitalize()))
        prov = c[1].selectbox("Província", ["(todas)"] + q.provincias(), key="x_prov")
        prod = c[2].selectbox("Produto", ["(todos)"] + NOMES_PRODUTOS, key="x_prod")
        f = {}
        if prov != "(todas)":
            f["provincia"] = prov
        if prod != "(todos)":
            f["produto"] = prod
        if st.button("Preparar ficheiro", type="primary"):
            try:
                with st.spinner("A gerar o Excel…"):
                    st.session_state["xlsx"] = (cat, excel.exportar(cat, f))
            except RuntimeError as e:
                st.error(str(e))
        if st.session_state.get("xlsx"):
            cat_, dados = st.session_state["xlsx"]
            st.download_button(f"⬇ Descarregar sonangol_{cat_}.xlsx ({len(dados) // 1024} KB)", dados, file_name=f"sonangol_{cat_}_{agora():%Y%m%d_%H%M}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.caption("Dica: «Exportar postos por província» = categoria Postos + filtro de província; «stocks por produto» = Reservatórios/Disponibilidade + filtro de produto.")
    with t2:
        if not excel.OPENPYXL_OK:
            st.error("Falta o pacote «openpyxl». Instale com:  py -m pip install openpyxl")
            st.stop()
        st.download_button("⬇ Descarregar modelo de importação", excel.modelo_importacao(), file_name="sonangol_modelo_importacao.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        up = st.file_uploader("Ficheiro .xlsx atualizado", type=["xlsx"])
        if up:
            a, b = st.columns(2)
            for aplicar, rot, col in ((False, "🔎 Só validar", a), (True, "⬆ Importar e aplicar", b)):
                if col.button(rot, key=f"imp_{aplicar}", type="primary" if aplicar else "secondary"):
                    try:
                        rel = excel.importar(up.getvalue(), UTIL, aplicar=aplicar)
                    except Exception as e:  # noqa: BLE001
                        st.error(str(e))
                    else:
                        st.dataframe(pd.DataFrame([dict(folha=k, inseridos=v["inseridos"], atualizados=v["atualizados"], rejeitados=v["rejeitados"]) for k, v in rel.items()]),
                                     hide_index=True)
                        for k, v in rel.items():
                            for e in v["erros"]:
                                st.write(f"• **{k}** — {e}")
                        st.success("Aplicado." if aplicar else "Validação concluída (nada gravado).")

# ----------------------------------------------------------------- simulador
elif PAG.startswith("🧪"):
    st.title("Simulador de alterações")
    st.caption("Gera alterações realistas de stock, abastecimentos, entregas e indisponibilidade — todas respeitam as regras (sem stock negativo, sem exceder capacidade, razão de movimentos).")
    a, b = st.columns(2)
    with a:
        st.subheader("⏱ Avançar o tempo")
        h = st.slider("Horas a simular", 1, 72, 24)
        if st.button("▶ Avançar simulação", type="primary"):
            r = erro_op(ops.simular_passo, h, ok="Simulação avançada.")
            if r:
                st.json(r)
        st.subheader("🔄 Renovar leituras")
        st.caption("Marca todas as leituras como «agora». O SIG-CAD considera dados com mais de 6 h como «Sem confirmação atualizada». O modo vivo (run_api.py) faz isto sozinho a cada 60 s.")
        try:
            from sonangol import vivo as _vivo
            st.caption("Modo vivo: " + str(_vivo.estado()))
        except Exception:
            pass
        if st.button("Renovar leituras agora"):
            r = erro_op(ops.renovar_leituras, ok="Leituras renovadas.")
            if r:
                st.json(r)
        st.subheader("🔍 Verificar coerência")
        if st.button("Verificar regras operacionais"):
            er = ops.verificar_coerencia()
            st.success("Tudo coerente: stocks dentro dos limites e iguais à soma dos movimentos.") if not er else st.error("\n".join(er[:20]))
    with b:
        st.subheader("🛑 Ruptura / indisponibilidade")
        cod = st.text_input("Código do posto", "SD-LDA-0001", key="s_cod")
        pr = st.selectbox("Produto", NOMES_PRODUTOS, key="s_pr")
        p_ = db.um("SELECT id FROM postos WHERE codigo=?", (cod,))
        if not p_:
            st.info("Código de posto inexistente.")
        else:
            c1, c2, c3 = st.columns(3)
            if c1.button("Esgotar produto"):
                erro_op(ops.simular_ruptura, p_["id"], pr, ok="Produto esgotado no posto.")
            if c2.button("Posto inoperacional"):
                erro_op(ops.simular_indisponibilidade, p_["id"], "Inoperacional", ok="Posto marcado inoperacional.")
            if c3.button("Restaurar posto"):
                erro_op(ops.restaurar_posto, p_["id"], ok="Posto restaurado.")
    st.divider()
    st.subheader("♻️ Recriar a base de dados de demonstração")
    a, b, c_ = st.columns(3)
    npostos = a.number_input("Nº de postos", 50, 2000, 500, 50)
    dias = b.number_input("Dias de histórico", 7, 90, 30)
    sem = c_.number_input("Semente", 1, 10**6, 2025)
    if st.checkbox("Confirmo que quero substituir todos os dados (as chaves de API são mantidas)"):
        if st.button("Recriar dados simulados", type="primary"):
            with st.spinner("A gerar…"):
                st.json(seed.gerar(int(npostos), int(dias), int(sem)))

# ----------------------------------------------------------------- auditoria
else:
    st.title("Auditoria")
    st.dataframe(pd.DataFrame(db.consultar("SELECT data_hora, utilizador, entidade, entidade_id, acao, detalhe FROM auditoria ORDER BY id DESC LIMIT 500")), hide_index=True, width="stretch")
