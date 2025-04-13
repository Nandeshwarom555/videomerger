from flask import Flask

app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health_check():
    return "OK", 200  # Return a success response for health check

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8000)
