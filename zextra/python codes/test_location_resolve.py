"""Location canonicalisation tests - pure functions, NO database access.

The location block is extracted from app.py and executed in isolation, so this
test can never touch a real database.
"""
import ast
import os
import re
import sys

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SRC = open(os.path.join(APP_ROOT, "app.py"), encoding="utf-8").read()

start = SRC.find("LOCATION_DATA = {")
depth = 0
for k in range(start, len(SRC)):
    if SRC[k] == "{":
        depth += 1
    elif SRC[k] == "}":
        depth -= 1
        if depth == 0:
            end = k + 1
            break
LOCATION = ast.literal_eval(SRC[start + len("LOCATION_DATA = "):end])

tail = SRC.find("# Background Supabase Cloud Backup Sync")
assert tail > start, "could not find the end of the location block"
block = SRC[start:tail]
compile(block, "locblock", "exec")

ns = {"re": re, "os": os, "json": __import__("json")}


class _FakeApp:
    static_folder = os.path.join(APP_ROOT, "static")

    class logger:
        @staticmethod
        def warning(*a, **k):
            pass

    def __getattr__(self, name):
        def _deco(*a, **k):
            return lambda f: f
        return _deco


ns["app"] = _FakeApp()
exec(compile(block, "locblock", "exec"), ns)

resolve_location = ns["resolve_location"]
canonical_country = ns["canonical_country"]
country_states = ns["country_states"]
find_state_for_city = ns["find_state_for_city"]
_find_city_owner = ns["_find_city_owner"]

failures = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        failures.append(label)


def r(country, state, city, legacy=None):
    out = resolve_location(country=country, state=state, city=city, legacy_location=legacy)
    return [out["country"], out["state"], out["city"]]


print("=" * 84)
print("1. legacy single-string locations (the messy data in the mentor table)")
print("=" * 84)
LEGACY = [
    ("Hyderabad, India", ["India", "Telangana", "Hyderabad"]),
    ("Bangalore, India", ["India", "Karnataka", "Bengaluru Urban"]),
    ("BENGALURU URBAN, India", ["India", "Karnataka", "Bengaluru Urban"]),
    ("Bengaluru , India", ["India", "Karnataka", "Bengaluru Urban"]),
    ("bhopal, India", ["India", "Madhya Pradesh", "Bhopal"]),
    ("NAVI MUMBAI, India", ["India", "Maharashtra", "Mumbai Suburban"]),
    ("ZIRAKPUR, India", ["India", "Punjab", "Zirakpur"]),
    ("India", ["India", "", ""]),
    ("India, India", ["India", "", ""]),
    ("Luxembourg, Luxembourg", ["Luxembourg", "Luxembourg", "Luxembourg"]),
    ("Luxembourg", ["Luxembourg", "", ""]),
    ("Luxembourg, Pakistan", ["Luxembourg", "Luxembourg", "Luxembourg"]),
    ("Amsterdam, Other", ["Netherlands", "North Holland", "Amsterdam"]),
    ("Delhi, India", ["India", "Delhi", "New Delhi"]),
    ("Noida, India", ["India", "Uttar Pradesh", "Gautam Buddha Nagar"]),
    ("Dhanpuri, India", ["India", "Madhya Pradesh", "Dhanpuri"]),
    ("Dehradun, India", ["India", "Uttarakhand", "Dehradun"]),
    ("Ghaziabad, India", ["India", "Uttar Pradesh", "Ghaziabad"]),
    ("Pune, India", ["India", "Maharashtra", "Pune"]),
    ("NA", ["", "", ""]),
    ("null", ["", "", ""]),
    ("", ["", "", ""]),
    ("Somewhere, Neverland", ["", "", ""]),
]
for legacy, want in LEGACY:
    got = r(None, None, None, legacy)
    check(f"{legacy!r:<32} -> {got}", got == want, f"expected {want}")

print()
print("=" * 84)
print("2. no two mentors share a city name under different countries")
print("=" * 84)
resolved = {legacy: resolve_location(country=None, state=None, city=None, legacy_location=legacy)
            for legacy, _ in LEGACY}
by_city = {}
for legacy, out in resolved.items():
    if out["city"]:
        by_city.setdefault(out["city"].lower(), {}).setdefault(out["country"], []).append(legacy)
clashes = {c: v for c, v in by_city.items() if len(v) > 1}
check("no cross-country city clashes", not clashes, clashes)

print()
print("  every produced city belongs to its country:")
for legacy, out in resolved.items():
    if not out["city"] or not out["country"]:
        continue
    exact = bool(find_state_for_city(out["country"], out["city"]))
    elsewhere = _find_city_owner(out["city"]) - {out["country"]}
    ok = exact or not elsewhere
    check(f"    {out['city']!r} in {out['country']!r} / {out['state']!r}",
          ok, "exists under " + str(elsewhere) if not ok else "")

print()
print("=" * 84)
print("3. structured input is canonicalised and idempotent")
print("=" * 84)
STRUCTURED = [
    (("United States", "California", "San Francisco", None), ["United States", "California", "San Francisco"]),
    (("USA", None, "New York", None), ["United States", "", "New York"]),
    (("UK", "England", "London", None), ["United Kingdom", "England", "London"]),
    (("india", "karnataka", "bengaluru urban", None), ["India", "Karnataka", "Bengaluru Urban"]),
    (("India", "Madhya Pradesh", "Bhopal", None), ["India", "Madhya Pradesh", "Bhopal"]),
    (("India", "Madhya Pradesh", "Nowhereville", None), ["India", "Madhya Pradesh", "Nowhereville"]),
    (("Germany", "Nowhere State", "Trier", None), ["Germany", "Rhineland-Palatinate", "Trier"]),
]
for args, want in STRUCTURED:
    got = r(*args)
    check(f"{args[:3]} -> {got}", got == want, f"expected {want}")

print()
print("  idempotency (resolving a resolved value must not change it):")
unstable = []
for legacy, out in resolved.items():
    first = (out["country"], out["state"], out["city"], out["location"])
    again = resolve_location(country=out["country"], state=out["state"],
                             city=out["city"], legacy_location=out["location"])
    second = (again["country"], again["state"], again["city"], again["location"])
    if first != second:
        unstable.append((legacy, first, second))
for legacy, a, b in unstable:
    check(f"    stable {legacy!r}", False, f"{a} -> {b}")
check("    all resolved values are stable", not unstable, len(unstable))

print()
print("=" * 84)
print("4. country matcher must not confuse near-miss countries")
print("=" * 84)
COUNTRIES = [
    ("Indonesia", "Indonesia"), ("India", "India"), ("Ireland", "Ireland"),
    ("Iran", "Iran"), ("Chad", "Chad"), ("China", "China"), ("Canada", "Canada"),
    ("Cambodia", "Cambodia"), ("Niger", "Niger"), ("Nigeria", "Nigeria"),
    ("Georgia", "Georgia"), ("Germany", "Germany"), ("Malta", "Malta"),
    ("Malawi", "Malawi"), ("Cyprus", "Cyprus"), ("Cuba", "Cuba"),
    ("Jamaica", "Jamaica"), ("Japan", "Japan"), ("Togo", "Togo"),
    ("  India  ", "India"), ("iNdIa", "India"), ("germany", "Germany"),
    ("united states", "United States"), ("United States of America", "United States"),
    ("UAE", "United Arab Emirates"), ("Russia", "Russia"),
    ("USA", "United States"), ("UK", "United Kingdom"),
    # typos must NOT snap onto a different country
    ("Indoneisa", ""), ("Nigerland", ""), ("Chnda", ""), ("Aremnia", ""),
    # non-countries
    ("Other", ""), ("NA", ""), ("", ""), ("Atlantis", ""), ("Holland", ""),
]
for raw, want in COUNTRIES:
    got = canonical_country(raw)
    check(f"canonical_country({raw!r}) = {got!r}", got == want, f"expected {want!r}")

print()
print("=" * 84)
print("5. filter picklists are deduplicated and cascade correctly")
print("=" * 84)
mentors = [{"location": l} for l in (
    "Bangalore, India", "BENGALURU URBAN, India", "Bengaluru , India",
    "Hyderabad, India", "Delhi, India", "Pune, India",
    "Luxembourg, Luxembourg", "Luxembourg, Pakistan",
    "Amsterdam, Other", "India", "",
)]
countries, states, cities = ns["mentor_location_filter_options"](mentors)
print("  countries:", countries)
print("  states   :", states)
print("  cities   :", cities)
check("countries deduplicated", len(countries) == len(set(countries)))
check("cities deduplicated", len(cities) == len(set(cities)))
check("no duplicate-looking city entries",
      len(cities) == len(set(c.replace(" ", "").lower() for c in cities)), cities)
check("Karnataka in the state list", "Karnataka" in states)
check("Telangana in the state list", "Telangana" in states)
check("no duplicate-looking states",
      len(states) == len(set(s.replace(" ", "").lower() for s in states)), states)

c2, s2, ci2 = ns["mentor_location_filter_options"](mentors, country="India", state="Karnataka")
print("  India+Karnataka -> states:", s2, "cities:", ci2)
check("city list narrows to the selected state", ci2 == ["Bengaluru Urban"], ci2)

print()
print("=" * 84)
print("FAILURES:", failures or "none")
print("=" * 84)
sys.exit(1 if failures else 0)