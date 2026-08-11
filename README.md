# TCC2
# INSTALAÇÕES e SETUP
- DEPENDÊNCIAS:
```bash
sudo dnf update -y
sudo dnf install -y git openvswitch net-tools python3 python3-setuptools telnet xterm
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
    ```