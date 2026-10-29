from __future__ import annotations

import logging
import os

from kubernetes import client
from kubernetes import config as kube_config
from prometheus_client import start_http_server

from .config import Config
from .controller import NodeHealer


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = Config.from_env()
    try:
        kube_config.load_incluster_config()
    except kube_config.ConfigException:
        kube_config.load_kube_config()  # local development against kind
    start_http_server(cfg.metrics_port)
    NodeHealer(client.CoreV1Api(), cfg).run_forever()


if __name__ == "__main__":
    main()
