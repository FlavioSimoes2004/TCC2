# Documentação técnica: `ryu_nac_controller.py` e `my_topology2.py`

Este documento descreve o funcionamento dos dois scripts centrais do projeto: a topologia de rede simulada no Mininet (`my_topology2.py`) e o controlador SDN com controle de acesso à rede - NAC (`ryu_nac_controller.py`). O objetivo dos dois, em conjunto, é permitir que hosts "inseguros" (sem firewall ativo ou com atualizações pendentes) sejam automaticamente bloqueados na camada 2 da rede, reduzindo a superfície de propagação de vírus e worms.

## Visão geral da arquitetura

```
                          ┌────────────────────────────┐
                          │   ryu_nac_controller.py     │
                          │   (Controlador Ryu, :6653)  │
                          │                              │
                          │  - Aprendizado L2 (switch)   │
                          │  - NAC: bloqueio por MAC     │
                          │  - Servidor TCP (:9999)      │
                          └───────────┬─────────────────┘
                                      │ OpenFlow 1.3
                                      │
                          ┌───────────▼─────────────────┐
      my_topology2.py --> │   Switch s1 (OVS, OF1.3)     │
      (cria a topologia)  └───────────┬─────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
                 ┌──▼──┐           ┌──▼──┐           ┌──▼──┐
                 │ h1  │           │ h2  │           │ h3  │   (+ nó NAT)
                 └─────┘           └─────┘           └─────┘
                 roda script.sh -> envia status "0"/"1" para o controlador (porta 9999)

                          ┌────────────────────────────┐
                          │      Banco MySQL "tcc2"     │
                          │  tabela dispositivos:       │
                          │  mac_address, ip_address,   │
                          │  status (0/1/NULL)          │
                          └────────────────────────────┘
```

O `my_topology2.py` monta a rede simulada (switch + hosts + NAT) e aponta o switch para o controlador remoto. O `ryu_nac_controller.py` é esse controlador: além de agir como switch aprendiz (L2 learning switch) básico, ele mantém um cadastro de dispositivos em um banco MySQL e, periodicamente, instala regras OpenFlow para bloquear na origem e no destino qualquer MAC marcado como "rejeitado" (`status = 0`).

---

## 1. `my_topology2.py`

### Objetivo

Criar, via Mininet, uma topologia de rede em estrela (*star topology*) com um switch central controlado remotamente pelo Ryu, alguns hosts e um nó NAT para acesso à internet, e abrir o CLI do Mininet para interação manual.

### Dependências

- `mininet.topo.Topo`, `mininet.net.Mininet`
- `mininet.node.OVSSwitch`, `mininet.node.RemoteController`
- `mininet.nodelib.NAT`
- `mininet.cli.CLI`
- `mininet.log`

### Estrutura

#### Classe `StarTopo(Topo)`

```python
class StarTopo(Topo):
    def build(self, n=3):
        switch = self.addSwitch('s1', cls=OVSSwitch, protocols='OpenFlow13')
        for i in range(1, n + 1):
            host_name = f'h{i}'
            host = self.addHost(host_name)
            self.addLink(host, switch)
```

- Define uma topologia customizada estendendo `Topo`, o mecanismo padrão do Mininet para descrever redes.
- `build(n=3)` é chamado automaticamente pelo Mininet ao instanciar `StarTopo(n=3)`, e é onde a topologia é efetivamente montada:
  1. Cria o switch central `s1` como `OVSSwitch` (Open vSwitch), forçando o protocolo `OpenFlow13`. Isso é obrigatório porque o `ryu_nac_controller.py` só declara suporte à versão 1.3 do OpenFlow (`OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]`) - se o switch tentasse falar OpenFlow 1.0, o controlador rejeitaria a conexão.
  2. Cria `n` hosts (`h1`, `h2`, `h3`, ...) e liga cada um diretamente ao switch `s1`, formando a topologia em estrela (todo tráfego entre hosts passa pelo switch central).

#### Função `run()`

```python
def run():
    setLogLevel('info')
    topo = StarTopo(n=3)
    net = Mininet(topo=topo, switch=OVSSwitch, controller=RemoteController)
    net.addNAT().configDefault()
    net.start()
    CLI(net)
    net.stop()
```

Passo a passo:

1. `setLogLevel('info')` - ativa logs informativos do Mininet no terminal.
2. `topo = StarTopo(n=3)` - instancia a topologia com 3 hosts (`h1`, `h2`, `h3`).
3. `net = Mininet(topo=topo, switch=OVSSwitch, controller=RemoteController)` - monta a rede virtual a partir da topologia, usando `RemoteController` como classe de controlador. Isso significa que o Mininet **não** sobe um controlador embutido: ele espera que um controlador externo (o `ryu_nac_controller.py`, rodando via `ryu-manager`) já esteja escutando na porta padrão `6653` do OpenFlow. É por isso que, na prática, o controlador Ryu precisa ser iniciado **antes** deste script.
4. `net.addNAT().configDefault()` - adiciona um nó NAT à topologia e configura rotas/NAT padrão, dando aos hosts acesso à internet (e servindo como "gateway" - é o IP desse nó que o `script.sh` descobre via `ip route` e usa para falar com o controlador na porta 9999, já que o namespace de rede do Ryu fica acessível através dele).
5. `net.start()` - efetivamente inicia os switches, hosts e links virtuais, e conecta o switch ao controlador remoto.
6. `CLI(net)` - abre o console interativo do Mininet (`mininet>`), permitindo comandos como `h1 ping h2`, `h1 xterm`, `pingall`, etc. O script fica bloqueado aqui até o usuário digitar `exit`.
7. `net.stop()` - ao sair do CLI, desliga e limpa toda a topologia virtual (interfaces, namespaces, processos).

### Como executar

```bash
sudo venv/bin/python my_topology2.py
```

Precisa ser executado como root (o Mininet manipula interfaces de rede e namespaces) e **depois** de o controlador Ryu já estar rodando (`venv/bin/ryu-manager ryu_nac_controller.py`), caso contrário o switch `s1` não encontrará um controlador para se conectar e ficará sem regras de encaminhamento.

---

## 2. `ryu_nac_controller.py`

### Objetivo

Implementar, sobre o framework Ryu, um controlador SDN que faz duas coisas ao mesmo tempo:

1. **Switch aprendiz de camada 2** - encaminha tráfego normalmente entre os hosts, aprendendo em qual porta cada MAC está.
2. **NAC (Network Access Control)** - cadastra automaticamente cada dispositivo novo que aparece na rede, recebe relatórios de "postura de segurança" desses dispositivos (via TCP na porta 9999, alimentados pelo `script.sh` de cada host) e, a cada 5 segundos, bloqueia no próprio switch (via regras OpenFlow) qualquer dispositivo marcado como inseguro - por **endereço MAC**, tanto como origem quanto como destino do tráfego.

### Dependências

- `pymysql` - acesso ao banco MySQL.
- `socket` - servidor TCP simples para receber status dos hosts.
- `ryu.base.app_manager`, `ryu.controller.*`, `ryu.ofproto.ofproto_v1_3`, `ryu.lib.packet.*`, `ryu.lib.hub` - framework Ryu e parsing de pacotes (Ethernet, IPv4, ARP).

### Banco de dados

O controlador depende da tabela `dispositivos` (definida em `Banco.sql`, banco `tcc2`):

| Coluna        | Tipo          | Significado                                              |
|---------------|---------------|-----------------------------------------------------------|
| `id`          | int, PK       | identificador interno                                     |
| `mac_address` | varchar, único| MAC do dispositivo                                         |
| `ip_address`  | varchar, único| último IP observado para esse dispositivo                  |
| `status`      | bit(1) / NULL | `1` = aprovado, `0` = rejeitado (bloqueado), `NULL` = pendente |
| `last_checked`| timestamp     | atualizado automaticamente a cada `UPDATE`                 |

### Estrutura geral - classe `NacSwitch(app_manager.RyuApp)`

```python
class NacSwitch(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
```

Declara que este é um app Ryu que fala exclusivamente OpenFlow 1.3.

#### `__init__`

```python
def __init__(self, *args, **kwargs):
    super(NacSwitch, self).__init__(*args, **kwargs)
    self.mac_to_port = {}
    self.datapaths = {}
    self.known_devices = set()
    self.db_thread = hub.spawn(self.db_polling_loop)
    self.tcp_thread = hub.spawn(self.tcp_server_loop)
```

Ao iniciar o app, além de preparar as estruturas em memória:
- `mac_to_port`: tabela de encaminhamento L2 aprendida, por switch (`{dpid: {mac: porta}}`).
- `datapaths`: switches atualmente conectados (`{dpid: datapath}`).
- `known_devices`: conjunto de pares `(mac, ip)` já registrados no banco nesta execução, para evitar registrar o mesmo dispositivo repetidamente.

...ele dispara **duas green threads** (via `ryu.lib.hub`, que usa eventlet) que rodam em paralelo durante toda a vida do controlador:
- `db_polling_loop` - o "motor" do NAC, que reaplica os bloqueios a cada 5s.
- `tcp_server_loop` - o servidor que recebe os relatórios de status dos hosts.

#### `_state_change_handler`

Escuta eventos de mudança de estado da conexão OpenFlow (`EventOFPStateChange`). Quando um switch entra em `MAIN_DISPATCHER` (conexão estabelecida e pronta), ele é adicionado a `self.datapaths`; quando cai para `CONFIG_DISPATCHER` (ou desconecta), é removido. Isso mantém `self.datapaths` sempre com a lista de switches ativos, usada pelo `db_polling_loop` para saber em quais switches instalar/remover regras.

#### `_register_device_db(mac, ip)`

Insere um novo dispositivo na tabela `dispositivos` com `status = NULL` (pendente), usando `INSERT IGNORE` - ou seja, se o MAC já existir (`uq_mac` é `UNIQUE`), a inserção é silenciosamente ignorada em vez de gerar erro. É chamada de forma assíncrona (`hub.spawn`) pelo `_packet_in_handler` sempre que um par `(mac, ip)` inédito é observado.

#### `tcp_server_loop` / `handle_tcp_client`

Sobe um servidor TCP simples na porta `9999`, escutando em todas as interfaces (`0.0.0.0`). Para cada conexão recebida, delega o atendimento a uma nova green thread (`handle_tcp_client`), que:

1. Lê até 1024 bytes e decodifica como texto.
2. Se o conteúdo for exatamente `"0"` ou `"1"`, interpreta como o status de segurança daquele host (enviado pelo `script.sh`: `1` = seguro/atualizado e com firewall ativo, `0` = inseguro) e chama `_update_device_status_db(ip_do_cliente, status)`.
3. Qualquer outro conteúdo é descartado e logado como inválido.
4. Fecha o socket ao final (`finally`).

É esse mecanismo que conecta o `script.sh` rodando em cada host ao controlador: o host descobre o gateway (nó NAT criado pelo `my_topology2.py`) e manda `"1"` ou `"0"` para `<gateway>:9999`.

#### `_update_device_status_db(ip, status)`

Executa `UPDATE dispositivos SET status = %s WHERE ip_address = %s`. Note que essa atualização ainda é feita **por IP** (é o identificador que o `script.sh` tem disponível ao se conectar via TCP), não por MAC - só o bloqueio propriamente dito no switch é que passou a ser por MAC.

#### `BLOCK_COOKIE` e `db_polling_loop` - o núcleo do NAC

```python
BLOCK_COOKIE = 0x4E4143  # "NAC" em hexadecimal, apenas como identificador

def db_polling_loop(self):
    while True:
        try:
            connection = pymysql.connect(...)
            with connection.cursor() as cursor:
                cursor.execute("SELECT mac_address FROM dispositivos WHERE status = 0")
                rejeitados = [row[0] for row in cursor.fetchall()]

                for dp_id, datapath in self.datapaths.items():
                    # 1) remove os bloqueios instalados no ciclo anterior
                    # 2) instala um bloqueio novo para cada MAC rejeitado
        finally:
            ...
        hub.sleep(5)
```

A cada 5 segundos (`hub.sleep(5)`), em loop infinito, esse método:

1. Consulta no banco todos os `mac_address` cujo `status = 0` (rejeitados/inseguros).
2. Para **cada switch conectado** (`self.datapaths`):
   - **Remove** as regras de bloqueio instaladas no ciclo anterior. Isso é feito com um `OFPFlowMod` de comando `OFPFC_DELETE`, filtrando **pelo campo `cookie`** (`cookie=BLOCK_COOKIE`, `cookie_mask=0xFFFF...FF`) em vez de por `match`. Essa marcação é necessária porque, ao usar MAC como critério de bloqueio, não existe mais um campo de match exclusivo das regras de NAC (como havia com `eth_type=IP` na versão anterior baseada em IP); sem o cookie, um delete "coringa" (match vazio) apagaria também a regra "miss" e as regras de aprendizado L2, quebrando o switch.
   - **Instala** duas regras de prioridade 100 para cada MAC rejeitado, ambas com `instructions=[OFPInstructionActions(OFPIT_CLEAR_ACTIONS, [])]` (ou seja: nenhuma ação = descarte do pacote) e marcadas com o mesmo `cookie`:
     - `eth_dst=mac` - bloqueia qualquer pacote **destinado** àquele MAC.
     - `eth_src=mac` - bloqueia qualquer pacote **originado** daquele MAC.

   Como o bloqueio é por `eth_dst`/`eth_src` (camada 2) e não por `ipv4_dst`/`ipv4_src`, ele vale para qualquer tipo de tráfego daquele host (IP, ARP, etc.), não só tráfego IPv4.
3. Se a consulta ao banco falhar por qualquer motivo, o erro é logado (`self.logger.error`) e o loop simplesmente tenta de novo no próximo ciclo, sem derrubar o controlador.

Como esse laço roda continuamente e reaplica todas as regras a cada 5 segundos, o efeito prático é: assim que o `status` de um dispositivo muda para `0` no banco (seja porque o `script.sh` reportou inseguro, seja por alteração manual), em até 5 segundos aquele MAC passa a ser bloqueado em todos os switches; se o `status` volta para `1`, o bloqueio correspondente deixa de ser reinstalado e o dispositivo volta a se comunicar normalmente.

#### `switch_features_handler`

Disparado quando um switch termina o handshake inicial do OpenFlow (`EventOFPSwitchFeatures`). Instala a regra "miss" de prioridade `0`: qualquer pacote que não bata com nenhuma outra regra é enviado ao controlador (`OFPP_CONTROLLER`), sem buffer (`OFPCML_NO_BUFFER`), disparando o `_packet_in_handler`.

#### `add_flow(datapath, priority, match, actions, buffer_id=None)`

Função utilitária genérica para instalar uma regra de fluxo (`OFPFlowMod`) no switch, dado um `match`, uma lista de `actions` (empacotadas em uma instrução `OFPIT_APPLY_ACTIONS`) e uma prioridade. Usada tanto pela regra "miss" quanto pelas regras de encaminhamento aprendidas no `_packet_in_handler`.

#### `_packet_in_handler` - switch aprendiz + registro automático

Disparado sempre que um pacote chega ao controlador (por não bater com nenhuma regra instalada). Faz duas coisas:

1. **Registro automático de dispositivos**: extrai o IP de origem do pacote (do cabeçalho IPv4, se for tráfego IP, ou do campo `src_ip` do ARP, se for tráfego ARP) e, se o par `(mac_origem, ip)` ainda não estiver em `self.known_devices`, dispara `_register_device_db` de forma assíncrona - é assim que um dispositivo novo entra no banco (com `status = NULL`, pendente de aprovação) na primeira vez que ele fala na rede.
2. **Encaminhamento L2 (learning switch clássico)**:
   - Ignora pacotes LLDP (usados internamente por ferramentas de descoberta de topologia).
   - Aprende a porta de origem: `mac_to_port[dpid][src] = in_port`.
   - Decide a porta de saída: se o MAC de destino já é conhecido, envia só para essa porta; caso contrário, faz *flood* (`OFPP_FLOOD`) para todas as portas.
   - Se a porta de saída não for flood, instala uma regra de prioridade `1` para aquele par `(in_port, eth_dst, eth_src)`, evitando que os próximos pacotes desse fluxo precisem passar pelo controlador novamente.
   - Envia o pacote atual via `OFPPacketOut`.

   Observação importante: essa regra de encaminhamento tem prioridade `1`, e as regras de bloqueio do NAC têm prioridade `100` - ou seja, um bloqueio sempre prevalece sobre uma regra de encaminhamento aprendida para o mesmo MAC, pois o OpenFlow avalia primeiro as regras de maior prioridade.

#### `restart_table_dispositivos()` (função de módulo, fora da classe)

```python
def restart_table_dispositivos():
    ...
    sql = "truncate dispositivos"
    ...

restart_table_dispositivos()
```

Essa função é chamada **no momento em que o módulo é carregado** (ou seja, assim que o `ryu-manager` importa o script), antes mesmo de qualquer switch se conectar. Ela executa um `TRUNCATE` na tabela `dispositivos`, apagando todo o cadastro anterior. Na prática, isso significa que **toda vez que o controlador Ryu é reiniciado, o histórico de dispositivos conhecidos/aprovados/rejeitados é zerado**, e todos os dispositivos precisarão ser recadastrados (e reavaliados) do zero.

### Fluxo de execução completo

1. `ryu-manager ryu_nac_controller.py` é iniciado → `restart_table_dispositivos()` roda e limpa a tabela → o app é instanciado → duas threads sobem (`db_polling_loop`, `tcp_server_loop`).
2. O switch `s1` (criado pelo `my_topology2.py`) se conecta ao controlador na porta 6653 → `_state_change_handler` registra o datapath → `switch_features_handler` instala a regra "miss".
3. Um host manda um pacote (ex.: ARP de descoberta, ping) → cai no `_packet_in_handler` → o dispositivo é registrado no banco como pendente (`status = NULL`) → o pacote é encaminhado/floodado normalmente (dispositivos pendentes **não são bloqueados**, só os explicitamente marcados como `status = 0`).
4. Em paralelo, cada host roda `script.sh`, que verifica firewall/atualizações e envia `"1"` ou `"0"` para `<gateway>:9999` → `tcp_server_loop` recebe → `_update_device_status_db` atualiza o `status` daquele IP no banco.
5. A cada 5 segundos, `db_polling_loop` relê a tabela, busca todos os MACs com `status = 0` e reinstala, em todos os switches conhecidos, regras de descarte por `eth_dst`/`eth_src` para esses MACs - efetivamente isolando esses hosts da rede em poucos segundos após serem marcados como inseguros.

### Como executar

```bash
# 1) criar/recriar o schema do banco
python3 setup_db.py   # (ou executar Banco.sql diretamente)

# 2) subir o controlador (antes da topologia)
venv/bin/ryu-manager ryu_nac_controller.py

# 3) em outro terminal, subir a topologia Mininet
sudo venv/bin/python my_topology2.py
```

### Observações e limitações

- As credenciais do MySQL (`user='root'`, `password='root'`) estão hardcoded no script em quatro lugares diferentes - adequado para o ambiente de testes do TCC, mas não para produção.
- `db_polling_loop` reinstala **todas** as regras de bloqueio a cada 5 segundos, mesmo que nada tenha mudado no banco; funciona bem na escala de uma topologia de teste, mas não é otimizado para redes grandes.
- A janela de até 5 segundos entre um host ser marcado como inseguro e o bloqueio efetivamente entrar em vigor é o intervalo do `hub.sleep(5)` - pode ser ajustado conforme a necessidade de resposta do NAC.
- `restart_table_dispositivos()` zera o cadastro a cada reinício do controlador; se for necessário manter o histórico entre execuções, essa chamada precisa ser removida ou condicionada.
