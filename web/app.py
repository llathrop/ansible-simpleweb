from flask import Flask

app = Flask(__name__)

@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Ansible Web Interface</title>
    </head>
    <body>
        <h1>Ansible Web Interface</h1>
        <p>Docker container is running successfully!</p>
        <p>Flask web server is operational on port 3001.</p>
    </body>
    </html>
    '''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3001, debug=True)
