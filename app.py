from flask import Flask, render_template, send_file
import os

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/download_script')
def download_script():
    file_path = './script.sh'
    return send_file(file_path, as_attachment=True)

@app.route('/download_cert')
def download_cert():
    """Disponibiliza o certificado público (TLS 1.3) do controlador Ryu,
    usado pelo script.sh para validar a identidade do controlador ao
    reportar o status de segurança do host na porta 9999."""
    file_path = './certs/nac_controller.crt'
    return send_file(file_path, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
