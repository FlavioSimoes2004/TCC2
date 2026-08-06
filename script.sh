#!/bin/bash

# Verifica se o serviço de firewall (firewalld) está ativo
if ! systemctl is-active --quiet firewalld; then
    echo "false - firewall not active"
    exit 0
fi

# Verifica se há atualizações do sistema disponíveis.
# 'dnf check-update' retorna 0 se não há pacotes para atualizar e 100 se existem atualizações.
dnf check-update --quiet > /dev/null 2>&1
update_status=$?

# Se o status for 0, o sistema está atualizado. Caso contrário, não está.
if [ $update_status -eq 0 ]; then
    echo "true"
else
    echo "false - update available"
fi
