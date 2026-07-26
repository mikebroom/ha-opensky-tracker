import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_LATITUDE, CONF_LONGITUDE
from .const import DOMAIN, CONF_RADIUS, CONF_SHEET_NAME, CONF_SERVICE_ACCOUNT

class OpenSkyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenSky Tracker."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="Local Airspace Tracker", data=user_input)

        # Default to the Home Assistant instance's configured coordinates
        default_lat = self.hass.config.latitude
        default_lon = self.hass.config.longitude

        schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_LATITUDE, default=default_lat): float,
            vol.Required(CONF_LONGITUDE, default=default_lon): float,
            vol.Required(CONF_RADIUS, default=15.0): float,
            vol.Required(CONF_SHEET_NAME, default="Airspace Log"): str,
            vol.Required(CONF_SERVICE_ACCOUNT, default="/config/service_account.json"): str,
        })

        return self.async_show_form(step_id="user", data_schema=schema)