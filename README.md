# TCC2
# INSTALAÇÕES e SETUP
- DEPENDÊNCIAS:
```bash
sudo dnf update -y
sudo dnf install -y git openvswitch net-tools python3 python3-setuptools telnet xterm
sudo dnf install -y python3-PyMySQL
```

- INSTALAÇÃO e SETUP MININET:
```bash
git clone https://github.com/mininet/mininet
cd mininet
mininet/util/install.sh

sudo python3 setup.py install
sudo ln -s /usr/local/bin/mn /usr/bin/mn

sudo make mnexec
sudo cp mnexec /usr/local/bin/
```

# FUNCIONAMENTO
```bash
-- PASSO 1: CRIAÇÃO DO BANCO
sudo python3 setup_database.py

-- PASSO 2: EXECUÇÃO DA TOPOLOGIA
sudo python3 my_topology.py

-- PASSO 3: EXECUÇÃO DA INTERFACE
xterm h1
venv/bin/python app.py

-- PASSO 4: TESTE DE BLOQUEIO
```