# SONANGOL — plataforma empresarial **simulada** (fonte de dados para o SIG-CAD)

> ⚠️ **TODOS OS DADOS SÃO SIMULADOS.** Não são informação oficial nem real da Sonangol nem de qualquer outra empresa.
> Existem apenas para testar a integração com o SIG-CAD. A API devolve `"simulado": true` e o cabeçalho `X-Dados-Simulados: true`.

Projeto **independente** do SIG-CAD (nenhum ficheiro do SIG-CAD é usado ou alterado por ele).

## Conteúdo
| Ficheiro | Função |
|---|---|
| `run_api.py` | Prepara a BD (gera 500 postos se estiver vazia), cria uma chave inicial e arranca a API em `http://127.0.0.1:8000` |
| `painel.py` | Painel de administração (Streamlit): dashboard, CRUD, entregas, chaves de API, Excel, simulador, auditoria |
| `sonangol/` | Núcleo: base SQLite, dados simulados, operações (razão de movimentos), consultas, API Flask, Excel |
| `run_all.sh` | Arranca API + painel |

## Executar localmente
```bash
pip install -r requirements.txt
python run_api.py                      # terminal 1 -> API  (imprime a chave inicial na 1.ª execução)
streamlit run painel.py --server.port 8502   # terminal 2 -> painel (palavra-passe: sonangol-demo)
```
Variáveis opcionais: `SONANGOL_DADOS` (pasta da BD), `SONANGOL_ADMIN_SENHA` (palavra-passe do painel).
Documentação interativa da API: <http://127.0.0.1:8000/docs> · OpenAPI: `/openapi.json`.

Executar o SIG-CAD ao lado (outro terminal, na pasta do SIG-CAD):
```bash
pip install openpyxl                   # necessário para a importação Excel
SIGCAD_INTEGRACOES_PERMITIR_LOCAL=1 streamlit run app.py --server.port 8501
```
(`SIGCAD_INTEGRACOES_PERMITIR_LOCAL=1` permite ligar a `http://localhost`; por omissão o SIG-CAD só aceita HTTPS público.)

## Modo vivo (importante)
`run_api.py` arranca um processo em segundo plano que, a cada 60 s, renova as leituras (`atualizado_em`) e, a cada 10 min, simula movimento (vendas, abastecimentos, falhas e restauros). Sem isto o SIG-CAD marcaria tudo como «Sem confirmação atualizada» após 6 h. Ao arrancar, recupera até 48 h de atraso. Desligar: `SONANGOL_VIVO=0`. Ajustar: `SONANGOL_VIVO_INTERVALO_S`, `SONANGOL_VIVO_PASSO_MIN`. `/api/v1/health` mostra o estado (`modo_vivo`). Deixe a janela da API aberta enquanto usa o SIG-CAD.

## Procedimento 1 — API
1. SONANGOL → **🔌 Painel de APIs → Chaves de acesso → Gerar nova chave** (mostrada uma só vez; na BD fica só o hash). Copie-a.
2. SIG-CAD → **🔌 Integrações API → Adicionar / editar**: Base URL `http://127.0.0.1:8000/api/v1`; credencial **API Key**, cabeçalho `X-API-Key`.
3. Ative os endpoints: Postos `/stations`, Disponibilidade `/availability`, Reservatórios `/tanks`, Bombas `/pumps`, Preços `/prices`.
4. **Testar ligação → Sincronizar agora** → os 500 postos aparecem na Visão Operacional e na vertente Pública.

## Procedimento 2 — Excel
1. SONANGOL → **📗 Excel → Exportar → «Pacote SIG-CAD (5 folhas)»**.
2. SIG-CAD → **🔌 Integrações API → 📄 Importar Excel / CSV** → carregar o `.xlsx` → validar → importar.
(Também é possível exportar por província/produto, descarregar o modelo de importação e reimportar no SONANGOL.)

## API REST (`/api/v1`)
**Autenticação** (qualquer uma): `X-API-Key: snl_…` · `Authorization: Bearer <chave ou token>` · `Authorization: ApiKey <chave>` · `?api_key=`.
`POST /auth/token` (com chave) devolve um token `snt.…` válido 1 h.

**Resposta:** `{"data": [...], "meta": {page, page_size, total, total_paginas, tem_proxima, ultima_atualizacao, gerado_em, simulado, aviso}}`.
**Erros:** `{"erro": {"codigo", "mensagem", "campo"}}` (400, 401, 404, 405, 500). Datas ISO 8601 (+01:00). Paginação `page`, `page_size` (por omissão 5000, máx. 10000).

| Endpoint | Descrição | Filtros |
|---|---|---|
| `GET /health` | estado do serviço (sem chave) | — |
| `GET /meta` | metadados e contagens | — |
| `GET /provincias`, `/municipios` | 21 províncias e municípios | `provincia` |
| `GET /empresas`, `/produtos`, `/instalacoes` | empresas, produtos, refinarias/terminais/bases/centros | `tipo`, `provincia` |
| `GET /postos`, `/postos/<codigo>` | postos (alias `/stations`) | `provincia`, `municipio`, `empresa`, `estado`, `produto`, `atualizado_desde` |
| `GET /disponibilidade` | por posto e produto (alias `/availability`) | idem + `disponivel` |
| `GET /reservatorios` | tanques: capacidade, litros, ocupação % (alias `/tanks`) | `posto`, `instalacao`, `produto`, `estado` |
| `GET /bombas` | bombas (alias `/pumps`) | `posto`, `produto`, `estado` |
| `GET /precos` | preços regulados (alias `/prices`) | `produto` |
| `GET /movimentos`, `/entregas` | razão de movimentos e entregas | `desde`, `tipo`, `estado`, `produto` |
| `GET /indicadores`, `/indicadores/provincias`, `/indicadores/evolucao-stocks` | indicadores agregados | `provincia`, `empresa`, `desde` |
| `GET /export/xlsx` | Excel (`categoria=sigcad\|completo\|postos…`) | filtros comuns |

Campos principais — **postos**: `id, nome, empresa, provincia, municipio, lat, lon, tipo, servicos[], produtos[], estado, situacao, motivo, atualizado_em` ·
**disponibilidade**: `posto_id, produto, comercializado, disponivel, estado, stock_l, capacidade_l, ocupacao_pct, bombas_operacionais, atualizado_em` ·
**reservatórios**: `reservatorio_id, posto_id, instalacao_id, produto, capacidade_l, litros, ocupacao_pct, minimo_operacional_l, estado, atualizado_em` ·
**bombas**: `posto_id, bomba_id, produto, estado, atualizado_em` · **preços**: `produto, preco, unidade, atualizado_em` · **entregas**: `id, produto, quantidade_l, origem, destino, veiculo, estado, data_saida, data_prevista_chegada, data_chegada`.
Os aliases `/stations`, `/availability`, `/tanks`, `/pumps`, `/prices` devolvem o subconjunto de campos no padrão do SIG-CAD.
A lista completa de campos de cada endpoint está em `/docs`.

## Regras de coerência (garantidas e verificáveis em «🧪 Simulador → Verificar»)
- 0 ≤ stock ≤ capacidade; ocupação % = litros / capacidade.
- Stock do tanque = soma dos seus movimentos (receções, vendas, entregas, ajustes).
- Entrega: Planeada → Em trânsito (debita origem) → Entregue (credita destino); Cancelada devolve a carga.
- `disponivel` = posto operacional **e** bomba operacional do produto **e** stock acima do mínimo operacional; produto não vendido ⇒ disponibilidade 0.
- Dados semente: 500 postos, 21 províncias, 5 produtos, 3 refinarias, 7 terminais, 21 centros, 8 bases, 30 dias de histórico, ~7 % de rupturas localizadas. Recriáveis com semente fixa.
