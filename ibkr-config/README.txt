Configurazione Client Portal Gateway IBKR
=========================================

1. Scarica il Client Portal Gateway da Interactive Brokers:
   https://www.interactivebrokers.com/en/trading/ib-api.php

2. Copia il file di configurazione richiesto dall'immagine Docker che usi
   (es. conf.yaml / root) in questa cartella come conf.yaml montato nel container.

3. Se l'immagine ghcr.io/unusualmachine/ibkr-client-portal-gateway non è adatta,
   usa il gateway ufficiale IBKR in locale e lascia il backend puntare a
   https://localhost:5000/v1/api (variabile IBKR_GATEWAY_URL).

4. Il gateway usa certificato TLS self-signed: il backend disabilita verify SSL
   in sviluppo (solo verso il gateway locale).
