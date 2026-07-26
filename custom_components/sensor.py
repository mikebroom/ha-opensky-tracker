import logging
import math
import requests
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_LATITUDE, CONF_LONGITUDE
from .const import DOMAIN, CONF_RADIUS, CONF_SHEET_NAME, CONF_SERVICE_ACCOUNT

_LOGGER = logging.getLogger(__name__)

# Update every 30 seconds to respect API limits
SCAN_INTERVAL = datetime.timedelta(seconds=30) 

def calculate_bounding_box(lat, lon, radius_km):
    """Calculates min/max lat and lon for the OpenSky API."""
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))
    return {
        "lamin": lat - lat_delta,
        "lamax": lat + lat_delta,
        "lomin": lon - lon_delta,
        "lomax": lon + lon_delta
    }

class OpenSkyGoogleSheetsLogger:
    """Handles appending/updating Google Sheets without blocking HA."""
    def __init__(self, service_account_path, sheet_name):
        self.scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        self.creds = ServiceAccountCredentials.from_json_keyfile_name(service_account_path, self.scope)
        self.client = gspread.authorize(self.creds)
        self.sheet_name = sheet_name

    def log_aircraft(self, aircraft_data):
        """Upserts aircraft data to Google Sheets."""
        try:
            sheet = self.client.open(self.sheet_name).sheet1
            records = sheet.get_all_records()
            icao = aircraft_data['icao24']
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            row_to_update = None
            for idx, row in enumerate(records):
                if str(row.get('ICAO24', '')) == icao:
                    row_to_update = idx + 2 # +2 because index is 0-based and row 1 is headers
                    break

            if row_to_update:
                current_visits = int(sheet.cell(row_to_update, 5).value or 0)
                sheet.update_cell(row_to_update, 5, current_visits + 1) # Update Visits
                sheet.update_cell(row_to_update, 7, now_str) # Update Last Visit
            else:
                # [Company/Route, Type, Reg, ICAO24, Visits, First Visit, Last Visit]
                row_data = [
                    aircraft_data['callsign'], 
                    "Unknown Type", # Placeholder for DB lookup
                    "Unknown Reg",  # Placeholder for DB lookup
                    icao, 
                    1, 
                    now_str, 
                    now_str
                ]
                sheet.append_row(row_data)
        except Exception as e:
            _LOGGER.error(f"Google Sheets error: {e}")

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the sensor platform."""
    sensor = OpenSkyAirspaceSensor(hass, entry)
    async_add_entities([sensor], update_before_add=True)

class OpenSkyAirspaceSensor(SensorEntity):
    def __init__(self, hass, entry):
        self.hass = hass
        self._attr_name = "Local Airspace"
        self._attr_unique_id = f"{entry.entry_id}_airspace"
        
        self.username = entry.data[CONF_USERNAME]
        self.password = entry.data[CONF_PASSWORD]
        self.bbox = calculate_bounding_box(
            entry.data[CONF_LATITUDE], 
            entry.data[CONF_LONGITUDE], 
            entry.data[CONF_RADIUS]
        )
        
        self.logger = OpenSkyGoogleSheetsLogger(
            entry.data[CONF_SERVICE_ACCOUNT], 
            entry.data[CONF_SHEET_NAME]
        )
        
        self._state = 0
        self._aircraft_list = []
        self._seen_today = set()

    @property
    def state(self):
        return self._state

    @property
    def extra_state_attributes(self):
        """Returns the list of aircraft for dashboard UI cards."""
        return {"aircraft": self._aircraft_list}

    async def async_update(self):
        """Fetch live data from OpenSky."""
        url = (
            f"https://opensky-network.org/api/states/all?"
            f"lamin={self.bbox['lamin']}&lomin={self.bbox['lomin']}&"
            f"lamax={self.bbox['lamax']}&lomax={self.bbox['lomax']}"
        )
        
        try:
            # Run blocking requests in HA's executor
            response = await self.hass.async_add_executor_job(
                lambda: requests.get(url, auth=(self.username, self.password), timeout=10)
            )
            data = response.json()
            
            self._aircraft_list = []
            states = data.get("states") or []
            
            for state in states:
                icao24 = state[0].strip()
                callsign = state[1].strip() if state[1] else "Unknown"
                
                plane_data = {
                    "icao24": icao24,
                    "callsign": callsign,
                    "type": "TBD", 
                    "reg": "TBD" 
                }
                self._aircraft_list.append(plane_data)

                # Log to sheets if it's a new plane for this session
                if icao24 not in self._seen_today:
                    self._seen_today.add(icao24)
                    await self.hass.async_add_executor_job(
                        self.logger.log_aircraft, plane_data
                    )
            
            self._state = len(self._aircraft_list)
            
        except Exception as e:
            _LOGGER.error(f"Error fetching OpenSky data: {e}")