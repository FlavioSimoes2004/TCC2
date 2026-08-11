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
if [ $seguro == true ] && [ $update_status -eq 0 ]; then
    pass
else
    seguro=false;
    echo "false - update available"
fi

echo "$seguro"