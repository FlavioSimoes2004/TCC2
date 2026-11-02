#!/bin/bash
# Roda em sequência toda a bateria de experimentos do TCC, sempre com 30
# repetições e métricas do host h1. Para cada número de hosts (2, 4, 8, 16, 32
# e 64), a ordem é: sem arquitetura, depois com arquitetura (sha1, sha256, sha512).
#
# Resultados em experimentos/resultados/:
#   sem arquitetura/<execução>/
#   com arquitetura/<sha1|sha256|sha512>/<execução>/
#
# Uma execução que falha é registrada e a bateria continua; o resumo final
# lista as falhas. A saída completa fica em resultados/bateria_<data>.log.
#
# Uso (precisa de root por causa do Mininet):
#   sudo bash experimentos/rodar_experimentos.sh
# O interpretador pode ser trocado: sudo PYTHON=venv/bin/python bash ...

HOSTS=(2 4 8 16 32 64)
HASHES=(sha1 sha256 sha512)
REPETICOES=30
HOST_FOCO=h1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RESULTADOS="$SCRIPT_DIR/resultados"
PYTHON="${PYTHON:-python}"

if [ "$(id -u)" -ne 0 ]; then
    echo "Precisa de root (Mininet). Use: sudo bash experimentos/rodar_experimentos.sh" >&2
    exit 1
fi

# O Fedora bloqueia assinaturas SHA-1 na política DEFAULT. Melhor parar agora do
# que descobrir no meio da bateria. A política do sistema não é alterada aqui.
if ! openssl req -x509 -newkey rsa:2048 -nodes -keyout /dev/null -out /dev/null \
        -subj "/CN=teste" -sha1 > /dev/null 2>&1; then
    echo "O OpenSSL recusou assinar com SHA-1. Libere antes de rodar a bateria:" >&2
    echo "  sudo update-crypto-policies --set DEFAULT:SHA1" >&2
    exit 1
fi

mkdir -p "$RESULTADOS/sem arquitetura"
for hash in "${HASHES[@]}"; do
    mkdir -p "$RESULTADOS/com arquitetura/$hash"
done

LOG="$RESULTADOS/bateria_$(date +%Y%m%d_%H%M%S).log"
TOTAL=$(( ${#HOSTS[@]} * (1 + ${#HASHES[@]}) ))
ATUAL=0
FALHAS=()

devolver_ao_usuario() {
    if [ -n "$SUDO_UID" ] && [ -n "$SUDO_GID" ]; then
        chown -R "$SUDO_UID:$SUDO_GID" "$RESULTADOS"
    fi
}

interromper() {
    echo "Bateria interrompida. Log: $LOG" >&2
    mn -c > /dev/null 2>&1
    devolver_ao_usuario
    exit 130
}
trap interromper INT TERM

# rodar <descrição> <pasta de saída> <argumentos do experimento...>
rodar() {
    local descricao="$1" saida="$2"
    shift 2
    ATUAL=$((ATUAL + 1))
    echo "=== [$ATUAL/$TOTAL] $(date +%H:%M:%S) $descricao" | tee -a "$LOG"
    "$PYTHON" "$SCRIPT_DIR/experimento.py" "$@" --saida "$saida" \
        --repeticoes "$REPETICOES" --host "$HOST_FOCO" 2>&1 | tee -a "$LOG"
    if [ "${PIPESTATUS[0]}" -ne 0 ]; then
        FALHAS+=("$descricao")
        echo "=== FALHOU: $descricao" | tee -a "$LOG"
        # Deixa o ambiente limpo para a próxima execução
        mn -c > /dev/null 2>&1
    fi
}

cd "$PROJECT_DIR" || exit 1

for n in "${HOSTS[@]}"; do
    rodar "$n hosts, sem arquitetura" "$RESULTADOS/sem arquitetura" \
        --hosts "$n" --arquitetura sem
    for hash in "${HASHES[@]}"; do
        rodar "$n hosts, com arquitetura, $hash" "$RESULTADOS/com arquitetura/$hash" \
            --hosts "$n" --arquitetura com --hash "$hash"
    done
done

devolver_ao_usuario

echo "=== Bateria concluída: $((TOTAL - ${#FALHAS[@]}))/$TOTAL execuções com sucesso. Log: $LOG" | tee -a "$LOG"
if [ "${#FALHAS[@]}" -gt 0 ]; then
    printf '  falhou: %s\n' "${FALHAS[@]}" | tee -a "$LOG"
    exit 1
fi
