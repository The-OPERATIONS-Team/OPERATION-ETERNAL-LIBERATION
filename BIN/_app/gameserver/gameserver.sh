#!/usr/bin/env bash

cd $(dirname "$0")

BIND_IP="${1:-"0.0.0.0"}"

/usr/bin/env python3 opeternal_listener.py --bind-ip "${BIND_IP}"
