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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
