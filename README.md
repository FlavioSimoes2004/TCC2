# TCC2
# INSTALAÇÕES e SETUP
- DEPENDÊNCIAS:
```bash
sudo dnf update -y
sudo dnf install -y git openvswitch net-tools python3 python3-setuptools telnet xterm
sudo dnf install -y python3-PyMySQL
```

- INSTALAÇÃO e SETUP:
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
    git clone https://github.com/faucetsdn/ryu
    ```

# FUNCIONAMENTO

1. CRIAÇÃO DO BANCO:
    ```bash
    sudo python3 setup_database.py
    ```

1. EXECUÇÃO CONTROLADOR:
    ```bash
    source venv/bin/activate
    sudo python ryu/ryu_nac_controller.py
    ```

1. EXECUÇÃO TOPOLOGIA:
    ```bash
    sudo python3 my_topology2.py
    ```

1. EXECUÇÃO DA INTERFACE:
    ```bash
    xterm h1
    venv/bin/python app.py
    ```

1. TESTE DE BLOQUEIO: