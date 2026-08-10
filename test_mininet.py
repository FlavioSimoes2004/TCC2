from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import OVSSwitch, Controller
from mininet.cli import CLI
from mininet.log import setLogLevel, info

class StarTopo(Topo):
    def build(self, n=3):
        switch = self.addSwitch('s1')
        for i in range(1, n + 1):
            host = self.addHost(f'h{i}')
            self.addLink(host, switch)

setLogLevel('info')
topo = StarTopo(n=3)
net = Mininet(topo=topo, switch=OVSSwitch, controller=Controller)
net.addNAT()
net.start()
net.pingAll()
net.stop()
