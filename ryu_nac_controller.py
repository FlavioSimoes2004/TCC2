import pymysql
import socket
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib.packet import ipv4, arp
from ryu.lib import hub

class NacSwitch(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(NacSwitch, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.known_devices = set()
        # Inicia a thread de monitoramento do banco (Network Access Control)
        self.db_thread = hub.spawn(self.db_polling_loop)
        # Inicia a thread do Servidor TCP para receber status do script.sh
        self.tcp_thread = hub.spawn(self.tcp_server_loop)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, CONFIG_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.logger.info('Switch conectado: %016x', datapath.id)
                self.datapaths[datapath.id] = datapath
        elif ev.state == CONFIG_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.info('Switch desconectado: %016x', datapath.id)
                del self.datapaths[datapath.id]

    def _register_device_db(self, mac, ip):
        """Insere o dispositivo no banco caso não exista."""
        try:
            connection = pymysql.connect(
                host='localhost', 
                user='root', 
                password='root', 
                database='tcc2'
            )
            with connection.cursor() as cursor:
                sql = "INSERT IGNORE INTO dispositivos (mac_address, ip_address, status) VALUES (%s, %s, NULL)"
                cursor.execute(sql, (mac, ip))
                if cursor.rowcount > 0:
                    self.logger.info("Novo dispositivo registrado no banco: MAC=%s, IP=%s", mac, ip)
            connection.commit()
        except Exception as e:
            self.logger.error("Erro ao registrar dispositivo %s (%s): %s", mac, ip, e)
        finally:
            if 'connection' in locals() and connection.open:
                connection.close()

    def tcp_server_loop(self):
        """Servidor TCP escutando na porta 9999 para receber o status (1 ou 0) dos hosts."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', 9999))
        server.listen(5)
        self.logger.info("Servidor TCP do Controlador Ryu escutando na porta 9999")
        while True:
            new_sock, address = server.accept()
            hub.spawn(self.handle_tcp_client, new_sock, address)

    def handle_tcp_client(self, sock, address):
        """Processa a mensagem recebida de um host via TCP."""
        client_ip = address[0]
        try:
            data = sock.recv(1024).decode('utf-8').strip()
            if data in ('0', '1'):
                status = int(data)
                self.logger.info("Recebido status %d do host com IP %s", status, client_ip)
                self._update_device_status_db(client_ip, status)
            else:
                self.logger.info("Dado inválido recebido do IP %s: %s", client_ip, data)
        except Exception as e:
            self.logger.error("Erro na comunicação TCP com %s: %s", client_ip, e)
        finally:
            sock.close()

    def _update_device_status_db(self, ip, status):
        """Atualiza a coluna status do dispositivo no banco."""
        try:
            connection = pymysql.connect(
                host='localhost', 
                user='root', 
                password='root', 
                database='tcc2'
            )
            with connection.cursor() as cursor:
                sql = "UPDATE dispositivos SET status = %s WHERE ip_address = %s"
                cursor.execute(sql, (status, ip))
                if cursor.rowcount > 0:
                    self.logger.info("Banco atualizado: IP=%s agora tem status=%d", ip, status)
                else:
                    self.logger.warning("Nenhum registro atualizado para o IP=%s. Talvez ele ainda não esteja cadastrado.", ip)
            connection.commit()
        except Exception as e:
            self.logger.error("Erro ao atualizar status do dispositivo %s: %s", ip, e)
        finally:
            if 'connection' in locals() and connection.open:
                connection.close()

    def db_polling_loop(self):
        """Verifica o banco a cada 5 segundos e atualiza regras."""
        while True:
            try:
                # ATENÇÃO: Verifique a senha do root, se aplicável.
                connection = pymysql.connect(
                    host='localhost', 
                    user='root', 
                    password='root', 
                    database='tcc2'
                )
                with connection.cursor() as cursor:
                    cursor.execute("SELECT ip_address FROM dispositivos WHERE status = 0")
                    rejeitados = [row[0] for row in cursor.fetchall()]
                    
                    for dp_id, datapath in self.datapaths.items():
                        ofproto = datapath.ofproto
                        parser = datapath.ofproto_parser
                        
                        # Remove bloqueios antigos (IP filters with Priority 100)
                        match_clear = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP)
                        mod_clear = parser.OFPFlowMod(
                            datapath=datapath,
                            command=ofproto.OFPFC_DELETE,
                            out_port=ofproto.OFPP_ANY,
                            out_group=ofproto.OFPG_ANY,
                            priority=100,
                            match=match_clear
                        )
                        datapath.send_msg(mod_clear)

                        # Instala novos bloqueios
                        for ip in rejeitados:
                            # Bloqueia destino
                            match_dst = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ipv4_dst=ip)
                            inst = [parser.OFPInstructionActions(ofproto.OFPIT_CLEAR_ACTIONS, [])]
                            mod_dst = parser.OFPFlowMod(
                                datapath=datapath, priority=100, match=match_dst, instructions=inst
                            )
                            datapath.send_msg(mod_dst)

                            # Bloqueia origem
                            match_src = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ipv4_src=ip)
                            mod_src = parser.OFPFlowMod(
                                datapath=datapath, priority=100, match=match_src, instructions=inst
                            )
                            datapath.send_msg(mod_src)
                            
            except Exception as e:
                self.logger.error("Erro ao acessar banco de dados: %s", e)
            finally:
                if 'connection' in locals() and connection.open:
                    connection.close()
            
            hub.sleep(5)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Instala regra "Miss" (priority 0) para enviar pacotes nao-aprendidos pro Controlador
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src
        
        # --- REGISTRO AUTOMÁTICO DE DISPOSITIVOS ---
        ip_addr = None
        if eth.ethertype == ether_types.ETH_TYPE_IP:
            ip_pkt = pkt.get_protocol(ipv4.ipv4)
            if ip_pkt:
                ip_addr = ip_pkt.src
        elif eth.ethertype == ether_types.ETH_TYPE_ARP:
            arp_pkt = pkt.get_protocol(arp.arp)
            if arp_pkt:
                ip_addr = arp_pkt.src_ip

        if ip_addr and (src, ip_addr) not in self.known_devices:
            self.known_devices.add((src, ip_addr))
            hub.spawn(self._register_device_db, src, ip_addr)
        # -------------------------------------------

        dpid = datapath.id

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
                return
            else:
                self.add_flow(datapath, 1, match, actions)

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
