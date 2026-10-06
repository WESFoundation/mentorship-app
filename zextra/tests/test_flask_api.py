import requests

urls = [
    "https://mentorship.weslux.lu/api/mentee/profile?email=vishnu.barman@wazireducationsociety.org",
    "https://mentorship.weslux.lu/api/mentee/mentors",
    "http://127.0.0.1:5000/api/mentee/mentors",
]

for url in urls:
    try:
        r = requests.get(url, timeout=5)
        print(f"URL: {url} => Status: {r.status_code}")
        print("   Response:", r.text[:200])
    except Exception as e:
        print(f"URL: {url} => Error: {e}")
