# TCC2
# INSTALAÇÕES e SETUP
- DEPENDÊNCIAS:
```bash
sudo dnf update -y
sudo dnf install -y git openvswitch net-tools python3 python3-setuptools telnet xterm
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