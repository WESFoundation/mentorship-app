// Shared Location Cascade Utility
// Handles Country > State > City cascading dropdowns across all profile forms
// Robust across local and production environments

class LocationCascade {
    constructor(options = {}) {
        this.countrySelect = document.getElementById(options.countryId || 'country_select');
        this.stateSelect = document.getElementById(options.stateId || 'state_select');
        this.citySelect = document.getElementById(options.cityId || 'city_select');
        this.stateLabel = document.getElementById(options.stateLabelId || 'state_label');
        this.cityLabel = document.getElementById(options.cityLabelId || 'city_label');
        
        this.currentCountry = (options.currentCountry || '').trim();
        this.currentState = (options.currentState || '').trim();
        this.currentCity = (options.currentCity || '').trim();

        // Flag to only restore initial state/city once on initial country match
        this.isInitialLoad = true;
        
        this.locationData = {};
        this.allCountriesData = [];
        this.globalStatesData = {};
        
        // Aliases mapping country names in various forms to LOCATION_DATA keys
        this.LOCATION_DATA_MAP = {
            'United States': 'USA',
            'United States of America': 'USA',
            'USA': 'USA',
            'United Kingdom': 'UK',
            'UK': 'UK',
            'Great Britain': 'UK',
            'United Arab Emirates': 'UAE',
            'UAE': 'UAE',
            'South Korea': 'South Korea',
            'Korea, Republic of': 'South Korea',
            'Korea': 'South Korea',
            'South Africa': 'South Africa',
            'Russian Federation': 'Russia'
        };

        // Aliases mapping to global_states.json keys
        this.GLOBAL_STATES_MAP = {
            'USA': 'United States',
            'United States of America': 'United States',
            'UK': 'United Kingdom',
            'UAE': 'United Arab Emirates',
            'The Bahamas': 'Bahamas',
            'Bahamas': 'The Bahamas',
            'The Gambia': 'Gambia',
            'Gambia': 'The Gambia',
            'Hong Kong': 'Hong Kong S.A.R.',
            'Macau': 'Macau S.A.R.',
            'Palestine': 'Palestinian Territory Occupied',
            'Saint Barthelemy': 'Saint-Barthelemy',
            'Saint Martin': 'Saint-Martin (French part)',
            'Sint Maarten': 'Sint Maarten (Dutch part)',
            'US Virgin Islands': 'Virgin Islands (US)',
            'Vatican City': 'Vatican City State (Holy See)',
            'Fiji': 'Fiji Islands',
            'DR Congo': 'Democratic Republic of the Congo',
            'Congo': 'Congo',
            'Wallis and Futuna': 'Wallis and Futuna Islands'
        };
        
        this.onCountryChangeCallback = options.onCountryChange || null;
        this.onStateChangeCallback = options.onStateChange || null;
        
        this.init();
    }
    
    async init() {
        // Prevent custom searchable select from lagging DOM with 250+ country options and dynamic cascade
        if (this.countrySelect) {
            this.countrySelect.setAttribute('data-no-search', 'true');
        }
        if (this.stateSelect) {
            this.stateSelect.setAttribute('data-no-search', 'true');
        }
        if (this.citySelect) {
            this.citySelect.setAttribute('data-no-search', 'true');
        }

        // Fetch location data sources concurrently with graceful fallback
        const [locData, gStates] = await Promise.allSettled([
            fetch('/api/location_data').then(r => r.json()).catch(() => ({})),
            fetch('/static/data/global_states.json').then(r => r.json()).catch(() => ({}))
        ]);
        
        this.locationData = locData.status === 'fulfilled' && locData.value ? locData.value : {};
        this.globalStatesData = gStates.status === 'fulfilled' && gStates.value ? gStates.value : {};
        
        this.populateCountries();
        
        if (this.currentCountry) {
            // Find option matching currentCountry (case-insensitive)
            if (this.countrySelect) {
                const matchOpt = Array.from(this.countrySelect.options).find(
                    o => o.value.toLowerCase() === this.currentCountry.toLowerCase()
                );
                if (matchOpt) {
                    this.countrySelect.value = matchOpt.value;
                } else {
                    // If not in list, add as an option
                    const opt = document.createElement('option');
                    opt.value = this.currentCountry;
                    opt.textContent = this.currentCountry;
                    this.countrySelect.appendChild(opt);
                    this.countrySelect.value = this.currentCountry;
                }
            }
            this.onCountryChange(true);
        } else {
            // No country chosen: ensure state/city are cleanly reset
            this.onCountryChange(false);
        }
        
        // After initial setup is completed, clear initial load flag
        this.isInitialLoad = false;
    }
    
    populateCountries() {
        if (!this.countrySelect) return;
        
        this.countrySelect.innerHTML = '<option value="">Select Country</option>';
        
        const regions = {
            'Asia': ['Afghanistan', 'Armenia', 'Azerbaijan', 'Bahrain', 'Bangladesh', 'Bhutan', 'Brunei', 'Cambodia', 'China', 'Cyprus', 'Georgia', 'Hong Kong', 'India', 'Indonesia', 'Iran', 'Iraq', 'Israel', 'Japan', 'Jordan', 'Kazakhstan', 'Kuwait', 'Kyrgyzstan', 'Laos', 'Lebanon', 'Macau', 'Malaysia', 'Maldives', 'Mongolia', 'Myanmar', 'Nepal', 'North Korea', 'Oman', 'Pakistan', 'Palestine', 'Philippines', 'Qatar', 'Saudi Arabia', 'Singapore', 'South Korea', 'Sri Lanka', 'Syria', 'Taiwan', 'Tajikistan', 'Thailand', 'Timor-Leste', 'Turkey', 'Turkmenistan', 'United Arab Emirates', 'Uzbekistan', 'Vietnam', 'Yemen'],
            'Europe': ['Albania', 'Andorra', 'Austria', 'Belarus', 'Belgium', 'Bosnia and Herzegovina', 'Bulgaria', 'Croatia', 'Czech Republic', 'Denmark', 'Estonia', 'Finland', 'France', 'Germany', 'Greece', 'Hungary', 'Iceland', 'Ireland', 'Italy', 'Latvia', 'Liechtenstein', 'Lithuania', 'Luxembourg', 'Malta', 'Moldova', 'Monaco', 'Montenegro', 'Netherlands', 'North Macedonia', 'Norway', 'Poland', 'Portugal', 'Romania', 'Russia', 'San Marino', 'Serbia', 'Slovakia', 'Slovenia', 'Spain', 'Sweden', 'Switzerland', 'Ukraine', 'United Kingdom', 'Vatican City'],
            'Americas': ['Antigua and Barbuda', 'Argentina', 'Bahamas', 'Barbados', 'Belize', 'Bolivia', 'Brazil', 'Canada', 'Chile', 'Colombia', 'Costa Rica', 'Cuba', 'Dominica', 'Dominican Republic', 'Ecuador', 'El Salvador', 'Grenada', 'Guatemala', 'Guyana', 'Haiti', 'Honduras', 'Jamaica', 'Mexico', 'Nicaragua', 'Panama', 'Paraguay', 'Peru', 'Saint Kitts and Nevis', 'Saint Lucia', 'Saint Vincent and the Grenadines', 'Suriname', 'Trinidad and Tobago', 'United States', 'Uruguay', 'Venezuela'],
            'Africa': ['Algeria', 'Angola', 'Benin', 'Botswana', 'Burkina Faso', 'Burundi', 'Cameroon', 'Cape Verde', 'Central African Republic', 'Chad', 'Comoros', 'Congo', 'DR Congo', "Cote d'Ivoire", 'Djibouti', 'Egypt', 'Equatorial Guinea', 'Eritrea', 'Eswatini', 'Ethiopia', 'Gabon', 'Gambia', 'Ghana', 'Guinea', 'Guinea-Bissau', 'Kenya', 'Lesotho', 'Liberia', 'Libya', 'Madagascar', 'Malawi', 'Mali', 'Mauritania', 'Mauritius', 'Morocco', 'Mozambique', 'Namibia', 'Niger', 'Nigeria', 'Rwanda', 'Sao Tome and Principe', 'Senegal', 'Seychelles', 'Sierra Leone', 'Somalia', 'South Africa', 'South Sudan', 'Sudan', 'Tanzania', 'Togo', 'Tunisia', 'Uganda', 'Zambia', 'Zimbabwe'],
            'Oceania': ['Australia', 'Fiji', 'Kiribati', 'Marshall Islands', 'Micronesia', 'Nauru', 'New Zealand', 'Palau', 'Papua New Guinea', 'Samoa', 'Solomon Islands', 'Tonga', 'Tuvalu', 'Vanuatu']
        for (const [region, countries] of Object.entries(regions)) {
            const group = document.createElement('optgroup');
            group.label = region;
            for (const c of countries.sort()) {
                const opt = document.createElement('option');
                opt.value = c;
                opt.textContent = c;
                group.appendChild(opt);
            }
            this.countrySelect.appendChild(group);
        }
        
        // Add event listener for country changes
        this.countrySelect.addEventListener('change', () => {
            // When user changes country dropdown interactively, clear previous saved state/city
            this.currentState = '';
            this.currentCity = '';
            this.isInitialLoad = false;
            this.onCountryChange(false);
        });

        // Add event listener for state changes
        if (this.stateSelect) {
            this.stateSelect.addEventListener('change', () => {
                // When user changes state dropdown interactively, clear previous saved city
                this.currentCity = '';
                this.onStateChange(false);
            });
        }
    }

    getStatesForCountry(country) {
        if (!country) return [];

        // 1. Check direct match or alias in locationData (app.py)
        const locKey = this.LOCATION_DATA_MAP[country] || country;
        if (this.locationData[locKey] && this.locationData[locKey].states) {
            return Object.keys(this.locationData[locKey].states);
        }
        if (this.locationData[country] && this.locationData[country].states) {
            return Object.keys(this.locationData[country].states);
        }

        // 2. Check direct match or alias in globalStatesData (global_states.json)
        if (this.globalStatesData[country] && this.globalStatesData[country].length > 0) {
            return this.globalStatesData[country];
        }
        const gsKey = this.GLOBAL_STATES_MAP[country];
        if (gsKey && this.globalStatesData[gsKey] && this.globalStatesData[gsKey].length > 0) {
            return this.globalStatesData[gsKey];
        }

        // 3. Case-insensitive lookup in globalStatesData
        const countryLower = country.toLowerCase().trim();
        for (const [k, v] of Object.entries(this.globalStatesData)) {
            if (k.toLowerCase() === countryLower && Array.isArray(v) && v.length > 0) {
                return v;
            }
        }

        return [];
    }

    getCitiesForState(country, state) {
        if (!country || !state) return [];

        const locKey = this.LOCATION_DATA_MAP[country] || country;
        const cData = this.locationData[locKey] || this.locationData[country];

        if (cData && cData.states) {
            // Check direct state match
            if (cData.states[state] && Array.isArray(cData.states[state])) {
                return cData.states[state];
            }
            // Check case-insensitive state match
            const stateLower = state.toLowerCase().trim();
            for (const [sName, cityList] of Object.entries(cData.states)) {
                if (sName.toLowerCase() === stateLower && Array.isArray(cityList)) {
                    return cityList;
                }
            }
        }

        return [];
    }
    
    onCountryChange(isInitial = false) {
        const country = this.countrySelect ? this.countrySelect.value : '';
        
        // Reset state and city selects completely
        if (this.stateSelect) {
            this.stateSelect.innerHTML = '<option value="">Select State</option>';
        }
        if (this.citySelect) {
            this.citySelect.innerHTML = '<option value="">Select District / City</option>';
        }
        
        // If no country selected, reset labels and return immediately
        if (!country) {
            if (this.stateLabel && this.cityLabel) {
                this.stateLabel.textContent = 'State / Province *';
                this.cityLabel.textContent = 'District / City *';
            }
            if (this.onCountryChangeCallback) {
                this.onCountryChangeCallback('');
            }
            return;
        }
        
        // Update phone code if function exists
        if (typeof autoUpdatePhoneCode === 'function') {
            autoUpdatePhoneCode(country);
        }
        if (typeof updateIndiaSpecificFields === 'function') {
            updateIndiaSpecificFields();
        }
        if (typeof checkAge === 'function') {
            checkAge();
        }
        
        // Update labels based on whether country is India
        const isIndia = (country === 'India');
        if (this.stateLabel && this.cityLabel) {
            if (isIndia) {
                this.stateLabel.textContent = 'State *';
                this.cityLabel.textContent = 'District *';
            } else {
                this.stateLabel.textContent = 'State / Province *';
                this.cityLabel.textContent = 'District / City *';
            }
        }
        
        // Retrieve states strictly for the selected country
        const statesList = this.getStatesForCountry(country);
        
        if (this.stateSelect) {
            if (statesList.length > 0) {
                statesList.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s;
                    opt.textContent = s;
                    this.stateSelect.appendChild(opt);
                });
            } else {
                const opt = document.createElement('option');
                opt.value = country;
                opt.textContent = country + ' (National / Region)';
                this.stateSelect.appendChild(opt);
            }
            
            // Only restore currentState on initial load if currentState actually belongs to this country
            if (isInitial && this.currentState) {
                const foundOpt = Array.from(this.stateSelect.options).find(
                    o => o.value.toLowerCase() === this.currentState.toLowerCase()
                );
                if (foundOpt) {
                    this.stateSelect.value = foundOpt.value;
                } else if (!isIndia && statesList.length === 0) {
                    // Only for small nations with no state list, allow custom state
                    const savedOpt = document.createElement('option');
                    savedOpt.value = this.currentState;
                    savedOpt.textContent = this.currentState;
                    this.stateSelect.appendChild(savedOpt);
                    this.stateSelect.value = this.currentState;
                } else {
                    // State does not belong to the selected country - clear it
                    this.currentState = '';
                    this.currentCity = '';
                }
            }
        }
        
        // Populate cities for current state
        this.onStateChange(isInitial);
        
        // Call external callback if provided
        if (this.onCountryChangeCallback) {
            this.onCountryChangeCallback(country);
        }
    }
    
    onStateChange(isInitial = false) {
        const country = this.countrySelect ? this.countrySelect.value : '';
        const state = this.stateSelect ? this.stateSelect.value : '';
        
        if (this.citySelect) {
            this.citySelect.innerHTML = '<option value="">Select District / City</option>';
        }
        
        if (!country || !state) {
            if (this.onStateChangeCallback) {
                this.onStateChangeCallback('');
            }
            return;
        }
        
        const isIndia = (country === 'India');
        const cities = this.getCitiesForState(country, state);
        
        if (this.citySelect) {
            if (cities.length > 0) {
                cities.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c;
                    opt.textContent = c;
                    this.citySelect.appendChild(opt);
                });
            } else if (!isIndia) {
                // If detailed city data is not available for a non-India region, provide state/region option
                const opt = document.createElement('option');
                opt.value = state;
                opt.textContent = state + ' (Main District / City)';
                this.citySelect.appendChild(opt);
            }
            
            // Restore current city only on initial load if it belongs to current options
            if (isInitial && this.currentCity) {
                const foundOpt = Array.from(this.citySelect.options).find(
                    o => o.value.toLowerCase() === this.currentCity.toLowerCase()
                );
                if (foundOpt) {
                    this.citySelect.value = foundOpt.value;
                } else if (!isIndia) {
                    const savedOpt = document.createElement('option');
                    savedOpt.value = this.currentCity;
                    savedOpt.textContent = this.currentCity;
                    this.citySelect.appendChild(savedOpt);
                    this.citySelect.value = this.currentCity;
                } else {
                    this.currentCity = '';
                }
            }
        }
        
        // Call external callback if provided
        if (this.onStateChangeCallback) {
            this.onStateChangeCallback(state);
        }
    }
    
    // Public method to set a country programmatically
    setCountry(country) {
        if (this.countrySelect) {
            this.countrySelect.value = country;
            this.currentState = '';
            this.currentCity = '';
            this.onCountryChange(false);
        }
    }
    
    // Public method to set a state programmatically
    setState(state) {
        if (this.stateSelect) {
            this.stateSelect.value = state;
            this.currentCity = '';
            this.onStateChange(false);
        }
    }
    
    // Public method to get current values
    getValues() {
        return {
            country: this.countrySelect ? this.countrySelect.value : '',
            state: this.stateSelect ? this.stateSelect.value : '',
            city: this.citySelect ? this.citySelect.value : ''
        };
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = LocationCascade;
}