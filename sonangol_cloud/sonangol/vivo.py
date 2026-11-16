"""Modo «vivo» da SONANGOL simulada: mantém os dados sempre atuais (os postos «reportam» periodicamente) e faz evoluir stocks,
entregas e algumas indisponibilidades temporárias. Corre numa thread dentro do processo da API."""
import logging
import os
import random
import threading
import time
from datetime import datetime

from . import db, operacoes as ops
from .config import agora

log = logging.getLogger("sonangol.vivo")
_PARAR = threading.Event()
_ESTADO = dict(ativo=False, intervalo_s=60, passo_min=10, ultima_renovacao=None, ultimo_passo=None, postos_com_falha=0)
_FALHAS: dict = {}          # posto_id -> instante (time.time()) em que foi marcado inoperacional


def estado() -> dict:
    return dict(_ESTADO, postos_com_falha=len(_FALHAS))


def _recuperar_atraso():
    """Se a API esteve parada, simula o tempo decorrido (até 48 h) para os stocks/entregas não ficarem «congelados»."""
    ult = db.cfg_get("ultima_atualizacao")
    if not ult:
        return
    try:
        d = datetime.strptime(str(ult)[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return
    horas = (agora() - d).total_seconds() / 3600
    if horas > 1:
        r = ops.simular_passo(horas=min(horas, 48))
        log.info("Recuperação de %.1f h sem atividade: %s", horas, r)


def _passo(passo_min: int):
    ops.simular_passo(horas=passo_min / 60)
    agora_t = time.time()
    for pid, t0 in list(_FALHAS.items()):                  # restaurar postos após 30–90 min
        if agora_t - t0 > random.uniform(1800, 5400):
            try:
                ops.restaurar_posto(pid)
            except Exception:
                pass
            _FALHAS.pop(pid, None)
    if len(_FALHAS) < 8 and random.random() < 0.4:         # de vez em quando um posto fica inoperacional (falha simulada)
        p = db.um("SELECT id FROM postos WHERE estado='Operacional' ORDER BY RANDOM() LIMIT 1")
        if p:
            try:
                ops.simular_indisponibilidade(p["id"], "Inoperacional")
                _FALHAS[p["id"]] = agora_t
            except Exception:
                pass


def _ciclo(intervalo_s: int, passo_min: int):
    ultimo_passo = time.time()
    while not _PARAR.is_set():
        try:
            ops.renovar_leituras()
            _ESTADO["ultima_renovacao"] = agora().strftime("%Y-%m-%d %H:%M:%S")
            if time.time() - ultimo_passo >= passo_min * 60:
                _passo(passo_min)
                ops.renovar_leituras()
                ultimo_passo = time.time()
                _ESTADO["ultimo_passo"] = _ESTADO["ultima_renovacao"]
        except Exception as e:  # noqa: BLE001
            log.warning("Modo vivo: %s", e)
        _PARAR.wait(intervalo_s)


def iniciar(intervalo_s: int | None = None, passo_min: int | None = None) -> bool:
    """Arranca a thread (idempotente). Desligar com SONANGOL_VIVO=0."""
    if os.environ.get("SONANGOL_VIVO", "1") == "0" or _ESTADO["ativo"]:
        return False
    intervalo_s = intervalo_s or int(os.environ.get("SONANGOL_VIVO_INTERVALO_S", "60"))
    passo_min = passo_min or int(os.environ.get("SONANGOL_VIVO_PASSO_MIN", "10"))
    try:
        _recuperar_atraso()
        ops.renovar_leituras()
    except Exception as e:  # noqa: BLE001
        log.warning("Arranque do modo vivo: %s", e)
    _ESTADO.update(ativo=True, intervalo_s=intervalo_s, passo_min=passo_min, ultima_renovacao=agora().strftime("%Y-%m-%d %H:%M:%S"))
    threading.Thread(target=_ciclo, args=(intervalo_s, passo_min), daemon=True, name="sonangol-vivo").start()
    return True
