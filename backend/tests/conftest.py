"""
Configurazione pytest condivisa per tutti i test.
"""
import pytest


# Rende asyncio_mode="auto" per tutti i test async del package,
# senza dover aggiungere @pytest.mark.asyncio a ogni test.
# Richiede pytest-asyncio >= 0.21.
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as asyncio coroutine"
    )
