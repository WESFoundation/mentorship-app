// Shared Location Cascade Utility
// Handles Country > State > City cascading dropdowns across all profile forms

class LocationCascade {
    constructor(options = {}) {
        this.countrySelect = document.getElementById(options.countryId || 'country_select');
        this.stateSelect = document.getElementById(options.stateId || 'state_select');
        this.citySelect = document.getElementById(options.cityId || 'city_select');
        this.stateLabel = document.getElementById(options.stateLabelId || 'state_label');
        this.cityLabel = document.getElementById(options.cityLabelId || 'city_label');
        
        this.currentCountry = options.currentCountry || '';
        this.currentState = options.currentState || '';
        this.currentCity = options.currentCity || '';
        
        this.locationData = {};
        this.allCountriesData = [];
        this.globalStatesData = {};
        
        this.COUNTRY_KEY_MAP = {
            'United States': 'USA',
            'United States of America': 'USA'
        };
        
        this.onCountryChangeCallback = options.onCountryChange || null;
        this.onStateChangeCallback = options.onStateChange || null;
        
        this.init();
    }
    
    getCountryDataKey(name) {
        return this.COUNTRY_KEY_MAP[name] || name;
    }
    
    async init() {
        // Start loading data immediately
        const [locData, countryData, gStates] = await Promise.allSettled([
            fetch('/api/location_data').then(r => r.json()).catch(() => ({})),
            fetch('/api/all_countries').then(r => r.json()).catch(() => ({ success: false, countries: [] })),
            fetch('/static/data/global_states.json').then(r => r.json()).catch(() => ({}))
        ]);
        
        this.locationData = locData.status === 'fulfilled' ? (locData.value || {}) : {};
        this.allCountriesData = (countryData.status === 'fulfilled' && countryData.value && countryData.value.countries) 
            ? countryData.value.countries : [];
        this.globalStatesData = gStates.status === 'fulfilled' ? (gStates.value || {}) : {};
        
        this.populateCountries();
        
        if (this.currentCountry) {
            this.countrySelect.value = this.currentCountry;
            this.onCountryChange();
        }
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
        };
        
        const allNames = new Set(this.allCountriesData.map(c => c.name));
        
        for (const [region, countries] of Object.entries(regions)) {
            const available = countries.filter(c => allNames.has(c));
            if (available.length > 0) {
                const group = document.createElement('optgroup');
                group.label = region;
                for (const c of available.sort()) {
                    const opt = document.createElement('option');
                    opt.value = c;
                    opt.textContent = c;
                    group.appendChild(opt);
                }
                this.countrySelect.appendChild(group);
            }
        }
        
        const inRegions = new Set(Object.values(regions).flat());
        const remaining = this.allCountriesData.filter(c => !inRegions.has(c.name));
        if (remaining.length > 0) {
            const group = document.createElement('optgroup');
            group.label = 'Other Countries';
            for (const c of remaining.sort((a,b) => a.name.localeCompare(b.name))) {
                const opt = document.createElement('option');
                opt.value = c.name;
                opt.textContent = c.name;
                group.appendChild(opt);
            }
            this.countrySelect.appendChild(group);
        }
        
        // Add event listener for country changes
        this.countrySelect.addEventListener('change', () => this.onCountryChange());
    }
    
    onCountryChange() {
        const country = this.countrySelect.value;
        
        // Reset state and city
        if (this.stateSelect) {
            this.stateSelect.innerHTML = '<option value="">Select State</option>';
        }
        if (this.citySelect) {
            this.citySelect.innerHTML = '<option value="">Select District / City</option>';
        }
        
        if (!country) return;
        
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
        
        // Update labels
        if (this.stateLabel && this.cityLabel) {
            if (country === 'India') {
                this.stateLabel.textContent = 'State *';
                this.cityLabel.textContent = 'District *';
            } else {
                this.stateLabel.textContent = 'State / Province *';
                this.cityLabel.textContent = 'District / City *';
            }
        }
        
        // Populate states
        const cData = this.locationData[this.getCountryDataKey(country)];
        let statesList = [];
        
        if (cData && cData.states) {
            statesList = Object.keys(cData.states);
        } else if (this.globalStatesData[country] && this.globalStatesData[country].length > 0) {
            statesList = this.globalStatesData[country];
        }
        
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
            
            // Restore current state if it exists
            if (this.currentState) {
                const found = Array.from(this.stateSelect.options).some(
                    o => o.value.toLowerCase() === this.currentState.toLowerCase()
                );
                if (found) {
                    this.stateSelect.value = this.currentState;
                } else {
                    const savedOpt = document.createElement('option');
                    savedOpt.value = this.currentState;
                    savedOpt.textContent = this.currentState;
                    this.stateSelect.appendChild(savedOpt);
                    this.stateSelect.value = this.currentState;
                }
            }
        }
        
        // Trigger state change to populate cities
        this.onStateChange();
        
        // Call external callback if provided
        if (this.onCountryChangeCallback) {
            this.onCountryChangeCallback(country);
        }
    }
    
    onStateChange() {
        const country = this.countrySelect.value;
        const state = this.stateSelect ? this.stateSelect.value : '';
        
        if (this.citySelect) {
            this.citySelect.innerHTML = '<option value="">Select District / City</option>';
        }
        
        if (!country || !state) return;
        
        const cData = this.locationData[this.getCountryDataKey(country)];
        let cities = [];
        
        if (cData && cData.states && cData.states[state]) {
            cities = cData.states[state];
        }
        
        if (this.citySelect) {
            if (cities.length > 0) {
                cities.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c;
                    opt.textContent = c;
                    this.citySelect.appendChild(opt);
                });
            } else {
                // If detailed city data is not available, provide the state as city option
                const opt = document.createElement('option');
                opt.value = state;
                opt.textContent = state + ' (Main District)';
                this.citySelect.appendChild(opt);
            }
            
            // Restore current city if it exists
            if (this.currentCity) {
                const found = Array.from(this.citySelect.options).some(
                    o => o.value.toLowerCase() === this.currentCity.toLowerCase()
                );
                if (found) {
                    this.citySelect.value = this.currentCity;
                } else {
                    const savedOpt = document.createElement('option');
                    savedOpt.value = this.currentCity;
                    savedOpt.textContent = this.currentCity;
                    this.citySelect.appendChild(savedOpt);
                    this.citySelect.value = this.currentCity;
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
            this.onCountryChange();
        }
    }
    
    // Public method to set a state programmatically
    setState(state) {
        if (this.stateSelect) {
            this.stateSelect.value = state;
            this.onStateChange();
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