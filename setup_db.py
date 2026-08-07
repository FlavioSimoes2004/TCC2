import pymysql
import os

def setup_database(sql_file):
    print(f"Lendo o arquivo {sql_file}...")
    
    if not os.path.exists(sql_file):
        print(f"Erro: O arquivo {sql_file} não foi encontrado.")
        return

    # Conecta no MySQL (sem especificar banco inicialmente, pois o script vai criar/deletar o tcc2)
    # Lembre-se de alterar a senha caso o seu usuário root precise.
    try:
        connection = pymysql.connect(host='localhost', user='root', password='')
        cursor = connection.cursor()
        
        with open(sql_file, 'r', encoding='utf-8') as f:
            sql_script = f.read()
            
        # Separa os comandos SQL por ponto e vírgula
        sql_commands = sql_script.split(';')
        
        for command in sql_commands:
            cmd = command.strip()
            # Ignora strings vazias geradas após o último ponto e vírgula
            if cmd:
                print(f"Executando comando: {cmd.split(chr(10))[0][:60]}...")
                cursor.execute(cmd)
                
        connection.commit()
        print("\nSucesso! O banco de dados e as tabelas foram criados.")
        
    except pymysql.MySQLError as e:
        print(f"\nErro no MySQL: {e}")
    except Exception as e:
        print(f"\nErro inesperado: {e}")
    finally:
        if 'connection' in locals() and connection.open:
            connection.close()

if __name__ == '__main__':
    # Caminho absoluto do seu script de banco
    arquivo_sql = '/home/flavio/Documents/TCC2/Banco.sql'
    setup_database(arquivo_sql)
