#!/bin/bash
# Gera (ou regenera) o certificado autoassinado usado pelo servidor TLS 1.3
# do ryu_nac_controller.py (porta 9999).
#
# O certificado (nac_controller.crt) é público e deve ser distribuído aos
# hosts (via app.py -> /download_cert) para que o script.sh consiga validar
# a identidade do controlador. A chave privada (nac_controller.key) NUNCA
# deve sair desta máquina - por isso está no .gitignore.
#
# Uso:
#   ./certs/generate_cert.sh [IP_DO_GATEWAY]
#
# Se IP_DO_GATEWAY não for informado, usa 10.0.0.4 (padrão do nó NAT criado
# por my_topology2.py, conforme documentado no README).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY_IP="${1:-10.0.0.4}"

openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$SCRIPT_DIR/nac_controller.key" \
    -out "$SCRIPT_DIR/nac_controller.crt" \
    -days 3650 \
    -subj "/CN=nac-controller" \
    -addext "subjectAltName=DNS:nac-controller,IP:${GATEWAY_IP},IP:127.0.0.1"

chmod 600 "$SCRIPT_DIR/nac_controller.key"

echo "Certificado gerado em: $SCRIPT_DIR/nac_controller.crt"
echo "Chave privada gerada em: $SCRIPT_DIR/nac_controller.key (mantenha em segredo)"
