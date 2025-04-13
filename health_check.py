import requests

def check_health():
    url = "http://127.0.0.1:8000"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            print("Health check passed.")
        else:
            print(f"Health check failed with status code {response.status_code}.")
    except Exception as e:
        print(f"Health check failed with error: {e}")

if __name__ == "__main__":
    check_health()
