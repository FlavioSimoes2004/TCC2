from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import Controller
from mininet.cli import CLI
from mininet.log import setLogLevel, info

class StarTopo(Topo):
    """Star topology with one central switch and n hosts."""

    def build(self, n=4):
        """Build the topology.
        n: number of hosts
        """
        # Add the central switch
        switch = self.addSwitch('s1')

        # Add n hosts and connect them to the switch
        for i in range(1, n + 1):
            host_name = f'h{i}'
            host = self.addHost(host_name)
            # Add link between host and switch
            self.addLink(host, switch)

def run():
    "Create and test a simple star network"
    # Set the log level to info to see what's happening
    setLogLevel('info')

    info("*** Creating network\n")
    # Instantiate the topology with 5 hosts
    topo = StarTopo(n=3)
    
    # Create the network with the default controller
    net = Mininet(topo=topo, controller=Controller)

    info("*** Starting network\n")
    net.start()

    info("*** Running CLI\n")
    # Start the Mininet Command Line Interface
    CLI(net)

    info("*** Stopping network\n")
    net.stop()

if __name__ == '__main__':
    run()
