"""Continent -> country grouping used by the supervisor dashboard's global geographic filter."""

CONTINENT_COUNTRIES = {
    "Africa": [
        "Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi", "Cabo Verde", "Cameroon",
        "Central African Republic", "Chad", "Comoros", "Congo", "Democratic Republic of the Congo",
        "Djibouti", "Egypt", "Equatorial Guinea", "Eritrea", "Eswatini", "Ethiopia", "Gabon", "Gambia",
        "Ghana", "Guinea", "Guinea-Bissau", "Ivory Coast", "Kenya", "Lesotho", "Liberia", "Libya",
        "Madagascar", "Malawi", "Mali", "Mauritania", "Mauritius", "Morocco", "Mozambique", "Namibia",
        "Niger", "Nigeria", "Rwanda", "Sao Tome and Principe", "Senegal", "Seychelles", "Sierra Leone",
        "Somalia", "South Africa", "South Sudan", "Sudan", "Tanzania", "Togo", "Tunisia", "Uganda",
        "Zambia", "Zimbabwe",
    ],
    "Asia": [
        "Afghanistan", "Armenia", "Azerbaijan", "Bahrain", "Bangladesh", "Bhutan", "Brunei", "Cambodia",
        "China", "Cyprus", "Georgia", "Hong Kong", "India", "Indonesia", "Iran", "Iraq", "Israel", "Japan",
        "Jordan", "Kazakhstan", "Kuwait", "Kyrgyzstan", "Laos", "Lebanon", "Macau", "Malaysia", "Maldives",
        "Mongolia", "Myanmar", "Nepal", "North Korea", "Oman", "Pakistan", "Palestine", "Philippines",
        "Qatar", "Saudi Arabia", "Singapore", "South Korea", "Sri Lanka", "Syria", "Taiwan", "Tajikistan",
        "Thailand", "Timor-Leste", "Turkey", "Turkmenistan", "United Arab Emirates", "Uzbekistan",
        "Vietnam", "Yemen",
    ],
    "Europe": [
        "Albania", "Andorra", "Austria", "Belarus", "Belgium", "Bosnia and Herzegovina", "Bulgaria",
        "Croatia", "Czech Republic", "Denmark", "Estonia", "Finland", "France", "Germany", "Greece",
        "Hungary", "Iceland", "Ireland", "Italy", "Kosovo", "Latvia", "Liechtenstein", "Lithuania",
        "Luxembourg", "Malta", "Moldova", "Monaco", "Montenegro", "Netherlands", "North Macedonia",
        "Norway", "Poland", "Portugal", "Romania", "Russia", "San Marino", "Serbia", "Slovakia",
        "Slovenia", "Spain", "Sweden", "Switzerland", "Ukraine", "United Kingdom", "Vatican City",
    ],
    "North America": [
        "Antigua and Barbuda", "Bahamas", "Barbados", "Belize", "Canada", "Costa Rica", "Cuba", "Dominica",
        "Dominican Republic", "El Salvador", "Grenada", "Guatemala", "Haiti", "Honduras", "Jamaica",
        "Mexico", "Nicaragua", "Panama", "Puerto Rico", "Saint Kitts and Nevis", "Saint Lucia",
        "Saint Vincent and the Grenadines", "Trinidad and Tobago", "United States",
    ],
    "Oceania": [
        "Australia", "Fiji", "Kiribati", "Marshall Islands", "Micronesia", "Nauru", "New Zealand", "Palau",
        "Papua New Guinea", "Samoa", "Solomon Islands", "Tonga", "Tuvalu", "Vanuatu",
    ],
    "South America": [
        "Argentina", "Bolivia", "Brazil", "Chile", "Colombia", "Ecuador", "Guyana", "Paraguay", "Peru",
        "Suriname", "Uruguay", "Venezuela",
    ],
}

# Common alternative spellings -> the canonical name used above.
_ALIASES = {
    "usa": "United States", "u.s.a.": "United States", "us": "United States", "u.s.": "United States",
    "united states of america": "United States", "america": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "great britain": "United Kingdom",
    "britain": "United Kingdom", "england": "United Kingdom", "scotland": "United Kingdom",
    "wales": "United Kingdom", "northern ireland": "United Kingdom",
    "uae": "United Arab Emirates", "u.a.e.": "United Arab Emirates", "emirates": "United Arab Emirates",
    "korea": "South Korea", "republic of korea": "South Korea", "korea, south": "South Korea",
    "russian federation": "Russia", "czechia": "Czech Republic", "turkiye": "Turkey", "türkiye": "Turkey",
    "viet nam": "Vietnam", "burma": "Myanmar", "cote d'ivoire": "Ivory Coast", "côte d'ivoire": "Ivory Coast",
    "drc": "Democratic Republic of the Congo", "dr congo": "Democratic Republic of the Congo",
    "congo (kinshasa)": "Democratic Republic of the Congo", "congo (brazzaville)": "Congo",
    "swaziland": "Eswatini", "cape verde": "Cabo Verde", "east timor": "Timor-Leste",
    "macedonia": "North Macedonia", "holland": "Netherlands", "the netherlands": "Netherlands",
    "the bahamas": "Bahamas", "the gambia": "Gambia", "palestinian territories": "Palestine",
    "bharat": "India", "republic of india": "India", "people's republic of china": "China", "prc": "China",
    "hongkong": "Hong Kong", "lao": "Laos", "brunei darussalam": "Brunei",
}

OTHER_GROUP = "Other / Unassigned"

_CANON = {c.lower(): c for countries in CONTINENT_COUNTRIES.values() for c in countries}
_CONTINENT_OF = {c: cont for cont, countries in CONTINENT_COUNTRIES.items() for c in countries}


def canonical_country(name):
    """Canonical spelling of a free-text country, or the cleaned text if unknown ('' if blank)."""
    raw = (name or "").strip()
    if not raw:
        return ""
    key = " ".join(raw.lower().split())
    if key in _CANON:
        return _CANON[key]
    if key in _ALIASES:
        return _ALIASES[key]
    return raw


def continent_of(name):
    return _CONTINENT_OF.get(canonical_country(name), OTHER_GROUP)


def geo_options(present_countries=None):
    """Alphabetical [{continent, countries:[{name, present}]}] for the dropdown.

    Every known country is listed; countries seen in the data but missing from
    the map go under 'Other / Unassigned'. `present` flags countries with users.
    """
    present = {canonical_country(c) for c in (present_countries or []) if (c or "").strip()}
    groups = {cont: set(countries) for cont, countries in CONTINENT_COUNTRIES.items()}
    other = {c for c in present if c not in _CONTINENT_OF}
    out = []
    for cont in sorted(groups):
        out.append({
            "continent": cont,
            "countries": [{"name": c, "present": c in present} for c in sorted(groups[cont])],
        })
    if other:
        out.append({"continent": OTHER_GROUP,
                    "countries": [{"name": c, "present": True} for c in sorted(other)]})
    return out
