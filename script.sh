#!/bin/bash

seguro=true;

# Verifica se o serviço de firewall (firewalld) está ativo
if ! systemctl is-active --quiet firewalld; then
    seguro=false;
    echo "false - firewall not active"
fi

# Verifica se há atualizações do sistema disponíveis.
# 'dnf check-update' retorna 0 se não há pacotes para atualizar e 100 se existem atualizações.
dnf check-update --quiet > /dev/null 2>&1
update_status=$?

# Se o status for 0, o sistema está atualizado. Caso contrário, não está.
if [ "$seguro" = true ] && [ $update_status -eq 0 ]; then
    echo "true - seguro e atualizado"
else
    seguro=false
    echo "false - update available ou firewall inativo"
fi

# Descobre o IP do gateway padrão (que no Mininet com NAT leva ao namespace do Ryu)
GATEWAY=$(ip route | awk '/default/ {print $3}')

# Diretório onde este script está (é onde também esperamos encontrar o
# certificado público do controlador, baixado junto via /download_cert)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_FILE="$SCRIPT_DIR/nac_controller.crt"

# Envia o status (0 ou 1) para o controlador via TLS 1.3.
# A validação do dispositivo passa a trafegar cifrada (e autenticada pelo
# certificado do controlador, quando ele está disponível), em vez de texto
# plano como na versão anterior baseada em 'nc'.
enviar_status_tls() {
    local status="$1"

    if [ ! -x "$(command -v openssl)" ]; then
        echo "Erro: 'openssl' não encontrado. Não é possível reportar o status via TLS." >&2
        return 1
    fi

    if [ -f "$CERT_FILE" ]; then
        # Caminho seguro: valida a cadeia do certificado contra o certificado
        # do controlador (pinning), e aborta se a validação falhar.
        echo "$status" | timeout 5 openssl s_client \
            -connect "$GATEWAY:9999" \
            -tls1_3 \
            -CAfile "$CERT_FILE" \
            -verify_return_error \
            -quiet -no_ign_eof > /dev/null 2>&1
    else
        echo "AVISO: certificado do controlador ($CERT_FILE) não encontrado;" >&2
        echo "       a conexão será cifrada em TLS 1.3, porém sem validar a identidade do controlador." >&2
        echo "       Baixe-o com: curl -OJ http://$GATEWAY:5000/download_cert" >&2
        echo "$status" | timeout 5 openssl s_client \
            -connect "$GATEWAY:9999" \
            -tls1_3 \
            -verify 0 \
            -quiet -no_ign_eof > /dev/null 2>&1
    fi
}

if [ -n "$GATEWAY" ]; then
    if [ "$seguro" = true ]; then
        echo "Enviando status SEGURO (1) para o controlador em $GATEWAY:9999 (TLS 1.3)"
        if enviar_status_tls "1"; then
            echo "Status enviado com sucesso."
        else
            echo "Erro: falha ao enviar status via TLS 1.3 (handshake, certificado ou timeout)." >&2
        fi
    else
        echo "Enviando status INSEGURO (0) para o controlador em $GATEWAY:9999 (TLS 1.3)"
        if enviar_status_tls "0"; then
            echo "Status enviado com sucesso."
        else
            echo "Erro: falha ao enviar status via TLS 1.3 (handshake, certificado ou timeout)." >&2
        fi
    fi
else
    echo "Erro: Não foi possível encontrar o gateway padrão para contatar o Ryu."
fi
