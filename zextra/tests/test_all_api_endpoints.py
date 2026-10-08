import requests

BASE_URL = "https://mentorship.weslux.lu/api"
EMAIL = "vishnu.barman@wazireducationsociety.org"
headers = {"Authorization": f"Bearer {EMAIL}"}

endpoints = [
    ("/auth/login", "POST", {"email": EMAIL, "password": "dummy"}),
    (f"/mentee/profile?email={EMAIL}", "GET", None),
    ("/mentee/tasks", "GET", None),
    ("/mentee/stats", "GET", None),
    ("/mentee/mentors", "GET", None),
    ("/mentee/connected_mentors", "GET", None),
    (f"/mentor/profile?email=skyadari@microsoft.com", "GET", None),
    ("/mentor/requests", "GET", None),
    ("/institution/stats", "GET", None),
    ("/admin/metrics", "GET", None),
    ("/notifications", "GET", None),
    ("/resource_notes", "GET", None),
]

print("=== TESTING FLASK REST API ENDPOINTS ===")
for ep, method, payload in endpoints:
    url = f"{BASE_URL}{ep}"
    try:
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=5)
        else:
            r = requests.post(url, json=payload, headers=headers, timeout=5)
        print(f"{method} {ep} => Status: {r.status_code}")
        print("  Data:", r.text[:150])
    except Exception as e:
        print(f"{method} {ep} => Error: {e}")
