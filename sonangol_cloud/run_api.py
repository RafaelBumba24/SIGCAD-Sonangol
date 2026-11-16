"""Arranca a API REST da SONANGOL (http://127.0.0.1:8000). Se a base de dados estiver vazia, gera os dados simulados."""
import sys

for _f in (sys.stdout, sys.stderr):   # consolas Windows (cp1252/cp850) não aceitam todos os símbolos
    try:
        _f.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from sonangol import api, auth, db, seed, vivo
from sonangol.config import API_HOST, API_PORTA


def preparar():
    db.iniciar()
    if not db.um("SELECT 1 FROM sqlite_master WHERE name='postos'") or not db.um("SELECT 1 FROM postos LIMIT 1"):
        print("Base de dados vazia: a gerar 500 postos simulados…")
        print(seed.gerar())
    if not auth.listar_chaves():
        k = auth.criar_chave("SIG-CAD — chave inicial")
        print("\n" + "=" * 70 + f"\n  CHAVE DE API (copie agora; não volta a ser mostrada):\n  {k}\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    preparar()
    if vivo.iniciar():
        print("Modo vivo ativo: os postos reportam de 60 em 60 s e stocks/entregas evoluem (desligar: SONANGOL_VIVO=0).")
    print(f"SONANGOL API em http://{API_HOST}:{API_PORTA}  ·  documentação: http://{API_HOST}:{API_PORTA}/docs")
    api.app.run(host=API_HOST, port=API_PORTA, threaded=True)
