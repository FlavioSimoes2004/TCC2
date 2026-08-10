from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import OVSBridge, OVSSwitch, Controller, RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel, info
import threading
import time
import pymysql

class StarTopo(Topo):
    """Star topology with one central switch and n hosts."""

    def build(self, n=4):
        """Build the topology.
        n: number of hosts
        """
        # Add the central switch (com failMode standalone como fallback)
        switch = self.addSwitch('s1', failMode='standalone')

        # Add n hosts and connect them to the switch
        for i in range(1, n + 1):
            host_name = f'h{i}'
            host = self.addHost(host_name)
            # Add link between host and switch
            self.addLink(host, switch)

def apply_db_rules(switch):
    """Verifica o banco de dados e adiciona regras de bloqueio no switch."""
    try:
        # ATENÇÃO: Ajuste o user e password do banco conforme necessário
        connection = pymysql.connect(host='localhost', user='root', password='root', database='tcc2')
        cursor = connection.cursor()
        cursor.execute("SELECT ip_address FROM dispositivos WHERE status = 0")
        rejeitados = cursor.fetchall()
        
        # Limpa APENAS as regras de bloqueio anteriores usando cookie (0x1)
        # Se utilizarmos apenas del-flows sem strict, ele deleta os fluxos essenciais do controlador SDN, quebrando a rede.
        switch.cmd('ovs-ofctl del-flows s1 "cookie=0x1/-1"')
        
        # Adiciona regras de bloqueio para IPs rejeitados com cookie=0x1
        for row in rejeitados:
            ip = row[0]
            # Descarta pacotes com destino ao IP bloqueado
            switch.cmd(f'ovs-ofctl add-flow s1 "cookie=0x1,ip,nw_dst={ip},priority=100,actions=drop"')
            # Opcional: descarta pacotes vindos do IP bloqueado
            switch.cmd(f'ovs-ofctl add-flow s1 "cookie=0x1,ip,nw_src={ip},priority=100,actions=drop"')
            
    except Exception as e:
        print(f"\n[Aviso] Falha ao verificar banco de dados: {e}")
    finally:
        if 'connection' in locals() and connection.open:
            connection.close()

def db_polling_loop(switch, stop_event):
    """Loop em background para verificar o banco periodicamente."""
    while not stop_event.is_set():
        apply_db_rules(switch)
        time.sleep(5)  # Verifica a cada 5 segundos

def run():
    "Create and test a simple star network"
    setLogLevel('info')

    info("*** Creating network\n")
    topo = StarTopo(n=3)
    
    # Switch OVSSwitch para atuar como switch SDN (com Controlador)
    # O failMode='standalone' foi movido para a classe StarTopo no momento de criar o switch
    net = Mininet(topo=topo, switch=OVSSwitch, controller=Controller)

    # Adiciona NAT (Network Address Translation) à topologia
    # Nota: O acrônimo para Network Access Control seria NAC, mas o Mininet possui a função addNAT() para Network Address Translation.
    # O seu script já implementa um controle de acesso (NAC) na função apply_db_rules.
    net.addNAT()

    info("*** Starting network\n")
    net.start()
    
    switch = net.get('s1')
    info("*** Iniciando verificação com o Banco de Dados (tcc2)...\n")
    
    # Inicia a thread que verifica o banco de dados em background
    stop_event = threading.Event()
    db_thread = threading.Thread(target=db_polling_loop, args=(switch, stop_event))
    db_thread.daemon = True
    db_thread.start()

    info("*** Running CLI\n")
    CLI(net)

    info("*** Stopping network\n")
    stop_event.set() # Para a thread do banco
    net.stop()

if __name__ == '__main__':
    run()
