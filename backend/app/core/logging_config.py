"""
MVP logging: ensure application loggers emit INFO to stdout (visible in ``docker logs``).

Uvicorn configures its own loggers; we align root + ``app.*`` + ``apscheduler`` to INFO
and attach a stdout handler to the root logger when none exists (typical in containers).
"""

from __future__ import annotations

import logging
import sys


class _IBKRUnknownContractFilter(logging.Filter):
    """
    Sopprime Error 200 'Nessuna descrizione di titoli' da ib_insync.wrapper per simboli LSE.

    Il paper account IBKR può contenere posizioni UK residue con exchange='SMART', currency='USD'
    (parametri errati per LSE). ib_insync tenta di qualificare questi contratti ad ogni sync
    del portfolio generando Error 200 ripetuti che non indicano nessun problema funzionale
    del nostro sistema — sono rumore puro. Il filtro abbassa questi messaggi a DEBUG.

    Simboli con '.' nel nome (BP., RR., BT.A, BA.) sono SEMPRE tickers LSE IBKR.
    I simboli senza '.' vengono confrontati contro il set FTSE noto.
    """

    # Top 30 FTSE 100 noti + simboli con punto (marker LSE) — mantenuto in sync con uk_universe.py
    _UK_SYMBOLS: frozenset[str] = frozenset({
        "HSBA", "BARC", "LLOY", "NWG", "STAN",
        "SHEL", "BP.",
        "RIO", "AAL", "GLEN", "ANTO",
        "ULVR", "DGE", "RKT", "TSCO", "SBRY", "NXT",
        "VOD", "BT.A", "REL",
        "BA.", "RR.", "CRH",
        "BLND", "LAND",
        "EXPN", "BATS", "PRU",
        "AZN", "GSK",
    })

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno != logging.ERROR:
            return True
        msg = record.getMessage()
        if "Error 200" not in msg or "descrizione di titoli" not in msg:
            return True
        # Simboli LSE con punto nel ticker (BP., RR., BT.A, BA.) — sempre UK
        if "symbol='" in msg:
            start = msg.find("symbol='") + 8
            end = msg.find("'", start)
            sym = msg[start:end] if end > start else ""
            if "." in sym or sym in self._UK_SYMBOLS:
                record.levelno = logging.DEBUG
                record.levelname = "DEBUG"
                return False  # sopprimi completamente
        return True


def configure_application_logging() -> None:
    """Idempotent: safe to call from lifespan on every startup."""
    log_format = "%(levelname)s [%(name)s] %(message)s"
    formatter = logging.Formatter(log_format)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    else:
        for h in root.handlers:
            if h.level > logging.INFO:
                h.setLevel(logging.INFO)

    # Application code and in-process scheduler
    logging.getLogger("app").setLevel(logging.INFO)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("apscheduler.scheduler").setLevel(logging.INFO)

    # Keep uvicorn access/error visible at INFO alongside app logs
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

    # peewee usato internamente da alcune dipendenze — non rilevante per noi
    logging.getLogger("peewee").setLevel(logging.WARNING)

    # Sopprimi Error 200 da ib_insync per simboli LSE residui nel paper account.
    # Questi contratti vengono qualificati con exchange='SMART'/currency='USD' (errato per LSE)
    # e generano spam ogni volta che ib_insync sincronizza il portfolio — non bloccanti.
    ib_wrapper_logger = logging.getLogger("ib_insync.wrapper")
    ib_wrapper_logger.addFilter(_IBKRUnknownContractFilter())
