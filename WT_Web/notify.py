import requests

# URL of your Flask app's update endpoint
FLASK_UPDATE_URL = "http://127.0.0.1:2176/notify_update"

# Secret token for security (must match what you set in app.py)
SECRET_TOKEN = "gigamalaise123"


def send_update():
    headers = {"Authorization": f"Bearer {SECRET_TOKEN}"}
    try:
        response = requests.post(FLASK_UPDATE_URL, headers=headers)
        if response.status_code == 200:
            print("Update notification sent successfully!")
        else:
            print(f"Failed to send update. Status code: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Error sending update: {e}")


if __name__ == "__main__":
    send_update()
