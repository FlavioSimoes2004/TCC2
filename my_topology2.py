from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.nodelib import NAT
from mininet.cli import CLI
from mininet.log import setLogLevel, info

class StarTopo(Topo):
    """Star topology with one central switch e n hosts."""

    def build(self, n=3):
        # Add the central switch (OpenFlow 1.3 obrigatório pro Ryu)
        switch = self.addSwitch('s1', cls=OVSSwitch, protocols='OpenFlow13')

        # Add n hosts and connect them to the switch
        for i in range(1, n + 1):
            host_name = f'h{i}'
            host = self.addHost(host_name)
            self.addLink(host, switch)

def run():
    "Cria topologia SDN"
    setLogLevel('info')

    info("*** Creating network\n")
    topo = StarTopo(n=3)
    
    # O controlador agora é remoto (o script ryu_nac_controller.py vai escutar na 6653)
    net = Mininet(topo=topo, switch=OVSSwitch, controller=RemoteController)

    info("*** Adicionando NAT node para acesso à internet\n")
    # Adiciona o nó NAT.
    # Se você quis dizer apenas NAC (Network Access Control), você pode comentar a linha abaixo.
    net.addNAT().configDefault()

    info("*** Starting network\n")
    net.start()
    
    info("*** Aguardando a conexão com o controlador Ryu...\n")

    info("*** Running CLI\n")
    CLI(net)

    info("*** Stopping network\n")
    net.stop()

if __name__ == '__main__':
    run()
