# TCC2
# INSTALAÇÕES e SETUP
- DEPENDÊNCIAS:
```bash
sudo dnf update -y
sudo dnf install -y git openvswitch net-tools python3 python3-setuptools telnet xterm iperf
sudo dnf install -y python3-PyMySQL
```

- INSTALAÇÃO e SETUP:
1. VENV
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    ```

1. MININET
    ```bash
    git clone https://github.com/mininet/mininet
    ./mininet/util/install.sh -fnpv

    sudo python3 setup.py install
    sudo ln -s /usr/local/bin/mn venv/bin/

    sudo make mnexec
    sudo cp mnexec venv/bin/
    ```

1. RYU CONTROLADOR (FEDORA)
    ```bash
    sudo mkdir /etc/network
    sudo touch /etc/network/interface
    git clone https://github.com/faucetsdn/ryu
    cd ryu
    # alterar funções do script ryu/hook.py para somente "pass"
    venv/bin/python setup.py install
    sudo ln -s /bin/ryu-manager venv/bin/
    ```

# FUNCIONAMENTO

1. CRIAÇÃO DO BANCO:
    ```bash
    sudo python3 setup_database.py
    ```

1. CERTIFICADO TLS DO CONTROLADOR (necessário apenas na primeira vez, ou para regenerar):
    ```bash
    # gera certs/nac_controller.crt (público) e certs/nac_controller.key (privado, NUNCA distribuir)
    ./certs/generate_cert.sh
    ```
    O servidor de status do controlador (porta 9999) agora exige TLS 1.3; sem esse
    certificado o `ryu_nac_controller.py` não sobe.

1. EXECUÇÃO CONTROLADOR:
    ```bash
    # executar em um terminal separado
    venv/bin/ryu-manager ryu/ryu_nac_controller.py
    ```

1. EXECUÇÃO TOPOLOGIA:
    ```bash
    # executar em outro terminal
    sudo venv/bin/python my_topology2.py
    ```

1. EXECUÇÃO DO CAPTIVE PORTAL:
    ```bash
    xterm nat0
    venv/bin/python app.py
    ```

1. DOWNLOAD DO SCRIPT EM OUTRO HOST:
    ```bash
    xterm h1 # pode ser outro host tambem
    curl -OJ http://10.0.0.4:5000/download_script
    curl -OJ http://10.0.0.4:5000/download_cert   # certificado usado para validar o controlador via TLS 1.3
    chmod +x script.sh
    ./script.sh
    ```

# AUTOMAÇÃO DE EXPERIMENTOS

Script `experimentos/experimento.py`: pergunta a quantidade de hosts e se o ambiente
terá ou não a arquitetura proposta, sobe tudo sozinho e coleta as métricas
(delta Tc, latência host ↔ autenticador, latência entre hosts e throughput dos
hosts aprovados). Não é preciso subir controlador/topologia manualmente antes.

```bash
# modo interativo (pergunta hosts e com/sem arquitetura)
sudo venv/bin/python experimentos/experimento.py

# ou passando tudo por parâmetro
sudo venv/bin/python experimentos/experimento.py --hosts 5 --arquitetura com --repeticoes 10
sudo venv/bin/python experimentos/experimento.py --hosts 5 --arquitetura sem --repeticoes 10
```

- `com`: Mininet + Ryu (`ryu_nac_controller.py`) + MySQL + NAC (`script.sh` via TLS 1.3).
- `sem`: somente Mininet com os hosts e um switch standalone (sem controlador, banco e NAC).
- Resultados em `experimentos/resultados/<data>_<com|sem>_<N>h/` (`metricas_hosts.csv`, `resumo.json`, `logs/`).
- Opções e detalhes das métricas: seção "4. `experimentos/experimento.py`" do `DOCUMENTACAO_SCRIPTS.md`.
