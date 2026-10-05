#!/usr/bin/env python3
"""Automação de experimentos do TCC (NAC sobre SDN).

Sobe uma topologia estrela com N hosts, em um de dois cenários:

  - "com" arquitetura: Mininet + switch OVS (OpenFlow 1.3) + controlador Ryu
    (ryu_nac_controller.py) + banco MySQL (tcc2) + NAC (script.sh reportando
    a postura via TLS 1.3 na porta 9999). O nó NAT (nat0) é o gateway dos
    hosts e é por ele que o host alcança o autenticador (servidor TLS do Ryu).
  - "sem" arquitetura: somente Mininet com os hosts e um switch em modo
    standalone (OVSBridge). Sem controlador, sem banco e sem NAC.

Métricas coletadas (por host e por repetição):

  - delta_tc (tempo de autenticação): do início da autenticação no host
    (execução do script.sh) até a decisão (status 0/1) ficar gravada no banco.
  - latência host <-> autenticador: RTT (ping) do host até o gateway nat0,
    onde o servidor TLS do controlador (porta 9999) é alcançado.
  - latência: RTT (ping) entre hosts (cada host pinga o próximo, em anel).
  - throughput dos hosts já aprovados: iperf TCP de cada host aprovado para
    o próximo aprovado (em anel, um par por vez).

No cenário "sem", todos os hosts são considerados aprovados e as métricas de
autenticação (delta_tc e latência até o autenticador) não se aplicam (N/A).

Uso (precisa de root por causa do Mininet):
    sudo venv/bin/python experimentos/experimento.py
    sudo venv/bin/python experimentos/experimento.py --hosts 5 --arquitetura com
"""
import argparse
import csv
import json
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import time
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

import pymysql
from mininet.net import Mininet
from mininet.node import OVSBridge, OVSSwitch, RemoteController
from mininet.topo import Topo
from mininet.log import setLogLevel

from my_topology2 import StarTopo

# Mesmas credenciais usadas pelo ryu_nac_controller.py
DB_CONFIG = dict(host='localhost', user='root', password='root', database='tcc2')

OPENFLOW_PORT = 6653
TLS_STATUS_PORT = 9999
IPERF_PORT = 5001
# db_polling_loop do controlador roda a cada 5s; espera 1 ciclo + folga para
# que os bloqueios dos hosts rejeitados já estejam instalados no switch.
NAC_POLLING_ESPERA_S = 6

CERT_FILE = os.path.join(PROJECT_DIR, 'certs', 'nac_controller.crt')
KEY_FILE = os.path.join(PROJECT_DIR, 'certs', 'nac_controller.key')


class StarTopoSemArquitetura(Topo):
    """Estrela com um switch standalone (aprendiz L2 do próprio OVS) e n hosts."""

    def build(self, n=3):
        switch = self.addSwitch('s1', cls=OVSBridge)
        for i in range(1, n + 1):
            host = self.addHost(f'h{i}')
            self.addLink(host, switch)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- parâmetros

def parse_args():
    parser = argparse.ArgumentParser(description='Automação de experimentos (NAC sobre SDN).')
    parser.add_argument('--hosts', type=int, help='quantidade de hosts da topologia')
    parser.add_argument('--arquitetura', choices=['com', 'sem'],
                        help='"com" = Ryu + MySQL + NAC; "sem" = somente Mininet (hosts + switch)')
    parser.add_argument('--repeticoes', type=int, default=1,
                        help='quantas vezes repetir o experimento (ambiente recriado a cada vez)')
    parser.add_argument('--ping-count', type=int, default=10, help='pacotes ICMP por medição de latência')
    parser.add_argument('--iperf-tempo', type=int, default=10, help='duração (s) de cada medição de throughput')
    parser.add_argument('--postura', choices=['real', 'aprovado'], default='real',
                        help='"real" executa o script.sh (firewalld + dnf check-update); '
                             '"aprovado" envia direto o status 1 pelo mesmo canal TLS 1.3, '
                             'isolando o tempo do protocolo de autenticação')
    parser.add_argument('--modo-auth', choices=['sequencial', 'simultaneo'], default='sequencial',
                        help='hosts se autenticam um por vez ou todos ao mesmo tempo')
    parser.add_argument('--timeout-auth', type=float, default=120,
                        help='tempo máximo (s) para aguardar a decisão de autenticação de um host')
    parser.add_argument('--ryu-manager', help='caminho do ryu-manager (padrão: venv/bin/ryu-manager)')
    parser.add_argument('--saida', default=os.path.join(PROJECT_DIR, 'experimentos', 'resultados'),
                        help='diretório onde os resultados são gravados')
    return parser.parse_args()


def perguntar_parametros(args):
    """Pede interativamente o que não foi informado por linha de comando."""
    while args.hosts is None or args.hosts < 1:
        try:
            args.hosts = int(input('Quantidade de hosts: ').strip())
        except ValueError:
            args.hosts = None
    while args.arquitetura is None:
        resp = input('Ambiente com a arquitetura proposta (Ryu + MySQL + NAC)? [s/n]: ').strip().lower()
        if resp in ('s', 'sim', 'com'):
            args.arquitetura = 'com'
        elif resp in ('n', 'nao', 'não', 'sem'):
            args.arquitetura = 'sem'
    if args.hosts < 2:
        log('AVISO: com menos de 2 hosts não é possível medir latência/throughput entre hosts.')


# ---------------------------------------------------------- infraestrutura

def porta_em_uso(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def esperar_porta(port, timeout, proc=None):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if proc is not None and proc.poll() is not None:
            return False
        if porta_em_uso(port):
            return True
        time.sleep(0.2)
    return False


def preparar_banco():
    """Cria o schema (Banco.sql) somente se o banco/tabela ainda não existirem."""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'dispositivos'")
            existe = cursor.fetchone() is not None
        conn.close()
    except pymysql.MySQLError:
        existe = False
    if not existe:
        log('Banco tcc2 não encontrado - criando a partir de Banco.sql')
        from setup_db import setup_database
        setup_database(os.path.join(PROJECT_DIR, 'Banco.sql'))


def garantir_certificado(gateway_ip):
    if os.path.isfile(CERT_FILE) and os.path.isfile(KEY_FILE):
        return
    log('Certificado TLS do controlador não encontrado - gerando com certs/generate_cert.sh')
    subprocess.run(['bash', os.path.join(PROJECT_DIR, 'certs', 'generate_cert.sh'), gateway_ip], check=True)
    devolver_ao_usuario(os.path.join(PROJECT_DIR, 'certs'))


def resolver_ryu_manager(args):
    if args.ryu_manager:
        return args.ryu_manager
    local = os.path.join(PROJECT_DIR, 'venv', 'bin', 'ryu-manager')
    return local if os.path.isfile(local) else shutil.which('ryu-manager')


def iniciar_controlador(ryu_manager, log_path):
    for porta in (OPENFLOW_PORT, TLS_STATUS_PORT):
        if porta_em_uso(porta):
            raise RuntimeError(f'Porta {porta} já está em uso - encerre o controlador Ryu que estiver rodando.')
    log_file = open(log_path, 'w')
    proc = subprocess.Popen([ryu_manager, 'ryu_nac_controller.py'], cwd=PROJECT_DIR,
                            stdout=log_file, stderr=subprocess.STDOUT)
    proc.log_file = log_file
    if not (esperar_porta(OPENFLOW_PORT, 30, proc) and esperar_porta(TLS_STATUS_PORT, 30, proc)):
        parar_controlador(proc)
        raise RuntimeError(f'Controlador Ryu não subiu (veja {log_path}).')
    return proc


def parar_controlador(proc):
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    proc.log_file.close()


def devolver_ao_usuario(path):
    """Arquivos criados via sudo voltam a pertencer ao usuário que chamou o sudo."""
    uid, gid = os.environ.get('SUDO_UID'), os.environ.get('SUDO_GID')
    if uid is None or gid is None:
        return
    uid, gid = int(uid), int(gid)
    os.chown(path, uid, gid)
    for raiz, dirs, arquivos in os.walk(path):
        for nome in dirs + arquivos:
            os.chown(os.path.join(raiz, nome), uid, gid)


# ----------------------------------------------------------------- medições

PING_PERDA_RE = re.compile(r'(\d+) packets transmitted, (\d+) received.*?([\d.]+)% packet loss')
PING_RTT_RE = re.compile(r'= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms')


def medir_ping(host, destino_ip, count):
    saida = host.cmd(f'ping -c {count} -i 0.2 -W 1 {destino_ip}')
    resultado = {'perda_pct': 100.0, 'rtt_min_ms': None, 'rtt_avg_ms': None,
                 'rtt_max_ms': None, 'rtt_mdev_ms': None}
    m = PING_PERDA_RE.search(saida)
    if m:
        resultado['perda_pct'] = float(m.group(3))
    m = PING_RTT_RE.search(saida)
    if m:
        resultado.update(rtt_min_ms=float(m.group(1)), rtt_avg_ms=float(m.group(2)),
                         rtt_max_ms=float(m.group(3)), rtt_mdev_ms=float(m.group(4)))
    return resultado


def consultar_status(conn):
    """{ip: status} da tabela dispositivos (status None = pendente)."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT ip_address, CAST(status AS UNSIGNED) FROM dispositivos")
        return {ip: (None if st is None else int(st)) for ip, st in cursor.fetchall()}


def esperar_registro(conn, ips, timeout=10):
    """Aguarda o controlador cadastrar (via packet_in) os IPs na tabela dispositivos."""
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        faltando = set(ips) - set(consultar_status(conn))
        if not faltando:
            return set()
        time.sleep(0.1)
    return faltando


def comando_autenticacao(postura, gateway_ip, arquivos_host):
    if postura == 'real':
        return ['bash', os.path.join(arquivos_host, 'script.sh')]
    cert = os.path.join(arquivos_host, 'nac_controller.crt')
    return ['bash', '-c',
            f'echo 1 | timeout 5 openssl s_client -connect {gateway_ip}:{TLS_STATUS_PORT} '
            f'-tls1_3 -CAfile {cert} -verify_return_error -quiet -no_ign_eof > /dev/null 2>&1']


def aguardar_decisoes(conn, em_andamento, timeout):
    """em_andamento: {ip: (t0, proc)}. Retorna {ip: (delta_tc_s, status)}.

    A decisão é considerada concluída quando o status do IP deixa de ser NULL
    no banco. Se o processo do host terminar e a decisão não aparecer em 2s
    (ex.: falha no handshake TLS), o host é marcado como sem decisão.
    """
    decisoes = {}
    fim_processo = {}
    while len(decisoes) < len(em_andamento):
        agora = time.monotonic()
        status = consultar_status(conn)
        for ip, (t0, proc) in em_andamento.items():
            if ip in decisoes:
                continue
            if status.get(ip) is not None:
                decisoes[ip] = (agora - t0, status[ip])
            elif proc.poll() is not None and agora - fim_processo.setdefault(ip, agora) > 2:
                decisoes[ip] = (None, None)
            elif agora - t0 > timeout:
                decisoes[ip] = (None, None)
        time.sleep(0.05)
    return decisoes


def autenticar_hosts(hosts, gateway_ip, arquivos_host, args, conn, logs_dir, rep):
    cmd = comando_autenticacao(args.postura, gateway_ip, arquivos_host)
    lotes = [[h] for h in hosts] if args.modo_auth == 'sequencial' else [hosts]
    resultados = {}
    for lote in lotes:
        em_andamento = {}
        for host in lote:
            t0 = time.monotonic()
            proc = host.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            em_andamento[host.IP()] = (t0, proc)
        decisoes = aguardar_decisoes(conn, em_andamento, args.timeout_auth)
        for host in lote:
            _, proc = em_andamento[host.IP()]
            try:
                saida, _ = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                saida, _ = proc.communicate()
            with open(os.path.join(logs_dir, f'auth_{host.name}_rep{rep}.log'), 'wb') as f:
                f.write(saida or b'')
            resultados[host.name] = decisoes[host.IP()]
    return resultados


def medir_throughput(hosts, duracao):
    """iperf TCP de cada host para o próximo (anel), um par por vez. {host: (destino, Mbps)}"""
    if len(hosts) < 2:
        return {}
    servidores = [h.popen(['iperf', '-s', '-p', str(IPERF_PORT)]) for h in hosts]
    time.sleep(1)
    resultados = {}
    try:
        for i, cliente in enumerate(hosts):
            servidor = hosts[(i + 1) % len(hosts)]
            saida = cliente.cmd(f'iperf -c {servidor.IP()} -p {IPERF_PORT} -t {duracao} -y C')
            linhas = [l for l in saida.strip().splitlines() if l.count(',') >= 8]
            mbps = float(linhas[-1].split(',')[-1]) / 1e6 if linhas else None
            resultados[cliente.name] = (servidor.name, mbps)
    finally:
        for s in servidores:
            s.terminate()
            s.wait()
    return resultados


# --------------------------------------------------------------- repetição

def executar_repeticao(rep, args, dir_saida):
    com_arquitetura = args.arquitetura == 'com'
    logs_dir = os.path.join(dir_saida, 'logs')
    ryu = net = conn = None
    linhas = {}
    try:
        if com_arquitetura:
            log(f'[rep {rep}] Iniciando controlador Ryu (NAC)')
            ryu = iniciar_controlador(resolver_ryu_manager(args), os.path.join(logs_dir, f'ryu_rep{rep}.log'))
            net = Mininet(topo=StarTopo(n=args.hosts), switch=OVSSwitch, controller=RemoteController)
            nat = net.addNAT()
            nat.configDefault()
        else:
            net = Mininet(topo=StarTopoSemArquitetura(n=args.hosts), switch=OVSBridge, controller=None)

        log(f'[rep {rep}] Iniciando rede com {args.hosts} hosts ({args.arquitetura} arquitetura)')
        net.start()
        if not net.waitConnected(timeout=30):
            raise RuntimeError('Switch não conectou ao controlador em 30s.')
        hosts = [h for h in net.hosts if h.name.startswith('h')]
        for h in hosts:
            linhas[h.name] = {'repeticao': rep, 'host': h.name, 'ip': h.IP(),
                              'arquitetura': args.arquitetura, 'n_hosts': args.hosts}

        aprovados = hosts
        if com_arquitetura:
            gateway_ip = nat.IP()
            conn = pymysql.connect(autocommit=True, **DB_CONFIG)

            # 1) Latência host <-> autenticador (também gera o packet_in que
            #    cadastra o host no banco antes da autenticação)
            log(f'[rep {rep}] Medindo latência host <-> autenticador ({gateway_ip})')
            for h in hosts:
                for k, v in medir_ping(h, gateway_ip, args.ping_count).items():
                    linhas[h.name][f'lat_autenticador_{k}'] = v
            faltando = esperar_registro(conn, [h.IP() for h in hosts])
            if faltando:
                log(f'[rep {rep}] AVISO: hosts não cadastrados no banco: {sorted(faltando)}')

            # 2) Delta Tc - arquivos que o host baixaria do captive portal
            arquivos_host = os.path.join(dir_saida, 'arquivos_host')
            os.makedirs(arquivos_host, exist_ok=True)
            shutil.copy(os.path.join(PROJECT_DIR, 'script.sh'), arquivos_host)
            shutil.copy(CERT_FILE, arquivos_host)
            log(f'[rep {rep}] Autenticando hosts (postura={args.postura}, modo={args.modo_auth})')
            auth = autenticar_hosts(hosts, gateway_ip, arquivos_host, args, conn, logs_dir, rep)
            for h in hosts:
                delta, status = auth[h.name]
                linhas[h.name].update(delta_tc_s=delta, status_nac=status, aprovado=(status == 1))
            aprovados = [h for h in hosts if auth[h.name][1] == 1]
            log(f'[rep {rep}] {len(aprovados)}/{len(hosts)} hosts aprovados')
            time.sleep(NAC_POLLING_ESPERA_S)
        else:
            for h in hosts:
                linhas[h.name].update(aprovado=True)

        # 3) Latência entre hosts aprovados (anel)
        if len(aprovados) >= 2:
            log(f'[rep {rep}] Medindo latência entre hosts aprovados')
            for i, h in enumerate(aprovados):
                destino = aprovados[(i + 1) % len(aprovados)]
                linhas[h.name]['lat_destino'] = destino.name
                for k, v in medir_ping(h, destino.IP(), args.ping_count).items():
                    linhas[h.name][f'lat_{k}'] = v

        # 4) Throughput dos hosts aprovados
        if len(aprovados) >= 2:
            if shutil.which('iperf'):
                log(f'[rep {rep}] Medindo throughput dos hosts aprovados ({args.iperf_tempo}s por par)')
                for nome, (destino, mbps) in medir_throughput(aprovados, args.iperf_tempo).items():
                    linhas[nome].update(throughput_destino=destino, throughput_mbps=mbps)
            else:
                log('AVISO: iperf não encontrado - throughput não medido (sudo dnf install iperf).')
    finally:
        if conn is not None:
            conn.close()
        if net is not None:
            net.stop()
        parar_controlador(ryu)
    return list(linhas.values())


# ------------------------------------------------------------------ saída

COLUNAS = ['repeticao', 'arquitetura', 'n_hosts', 'host', 'ip', 'aprovado', 'status_nac', 'delta_tc_s',
           'lat_autenticador_rtt_avg_ms', 'lat_autenticador_rtt_min_ms', 'lat_autenticador_rtt_max_ms',
           'lat_autenticador_rtt_mdev_ms', 'lat_autenticador_perda_pct',
           'lat_destino', 'lat_rtt_avg_ms', 'lat_rtt_min_ms', 'lat_rtt_max_ms', 'lat_rtt_mdev_ms',
           'lat_perda_pct', 'throughput_destino', 'throughput_mbps']

METRICAS_RESUMO = {
    'delta_tc_s': 'Delta Tc - tempo de autenticação (s)',
    'lat_autenticador_rtt_avg_ms': 'Latência host <-> autenticador (ms)',
    'lat_rtt_avg_ms': 'Latência entre hosts (ms)',
    'throughput_mbps': 'Throughput dos hosts aprovados (Mbps)',
}


def estatisticas(valores):
    valores = [v for v in valores if v is not None]
    if not valores:
        return None
    return {'amostras': len(valores), 'media': statistics.mean(valores),
            'desvio_padrao': statistics.stdev(valores) if len(valores) > 1 else 0.0,
            'min': min(valores), 'max': max(valores)}


def gravar_resultados(linhas, args, dir_saida):
    with open(os.path.join(dir_saida, 'metricas_hosts.csv'), 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(linhas)

    resumo = {
        'parametros': {k: v for k, v in vars(args).items() if k not in ('saida', 'ryu_manager')},
        'hosts_aprovados': sum(1 for l in linhas if l.get('aprovado')),
        'hosts_total': len(linhas),
        'metricas': {chave: estatisticas([l.get(chave) for l in linhas]) for chave in METRICAS_RESUMO},
    }
    with open(os.path.join(dir_saida, 'resumo.json'), 'w') as f:
        json.dump(resumo, f, indent=2, ensure_ascii=False)
    return resumo


def imprimir_resumo(resumo):
    print()
    print(f"{'Métrica':<42}{'média':>10}{'desvio':>10}{'min':>10}{'max':>10}{'n':>5}")
    for chave, nome in METRICAS_RESUMO.items():
        est = resumo['metricas'][chave]
        if est is None:
            print(f'{nome:<42}{"N/A":>10}')
        else:
            print(f"{nome:<42}{est['media']:>10.3f}{est['desvio_padrao']:>10.3f}"
                  f"{est['min']:>10.3f}{est['max']:>10.3f}{est['amostras']:>5}")
    print(f"\nHosts aprovados: {resumo['hosts_aprovados']}/{resumo['hosts_total']} (somando as repetições)")


def main():
    if os.geteuid() != 0:
        sys.exit('Este experimento precisa de root (Mininet). Use: sudo venv/bin/python experimentos/experimento.py')
    args = parse_args()
    perguntar_parametros(args)
    setLogLevel('warning')

    nome = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{args.arquitetura}_{args.hosts}h"
    dir_saida = os.path.join(args.saida, nome)
    os.makedirs(os.path.join(dir_saida, 'logs'), exist_ok=True)

    if args.arquitetura == 'com':
        if not resolver_ryu_manager(args):
            sys.exit('ryu-manager não encontrado (informe com --ryu-manager).')
        preparar_banco()
        garantir_certificado(f'10.0.0.{args.hosts + 1}')

    linhas = []
    try:
        for rep in range(1, args.repeticoes + 1):
            linhas += executar_repeticao(rep, args, dir_saida)
    finally:
        resumo = gravar_resultados(linhas, args, dir_saida)
        devolver_ao_usuario(args.saida)
    imprimir_resumo(resumo)
    log(f'Resultados em: {dir_saida}')


if __name__ == '__main__':
    main()
