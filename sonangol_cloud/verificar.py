"""Diagnóstico: python verificar.py"""
import sys, importlib, socket
print("Python", sys.version.split()[0], sys.platform)
for m in ("flask", "streamlit", "pandas", "openpyxl"):
    try:
        importlib.import_module(m); print("OK  ", m)
    except Exception as e:
        print("FALTA", m, "-> pip install -r requirements.txt")
for p in (8000, 8502):
    s = socket.socket(); r = s.connect_ex(("127.0.0.1", p)); s.close()
    print(f"porta {p}:", "ocupada/em uso" if r == 0 else "livre")
try:
    from sonangol import db; db.iniciar(); print("OK   base de dados")
except Exception as e:
    print("ERRO ao importar sonangol:", repr(e), "(execute este ficheiro dentro da pasta do projeto)")
