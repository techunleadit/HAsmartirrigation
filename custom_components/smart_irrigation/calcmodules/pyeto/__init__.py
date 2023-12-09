"""The PyETO module for Smart Irrigation Integration."""
import datetime
import logging
from statistics import mean
from ..calcmodule import SmartIrrigationCalculationModule
from .pyeto import (sunset_hour_angle, sol_dec, cs_rad, daylight_hours, et_rad,deg2rad,
                    inv_rel_dist_earth_sun, sol_rad_from_t,sol_rad_from_sun_hours,
                    net_in_sol_rad, avp_from_tdew, net_out_lw_rad, net_rad, convert,
                    fao56_penman_monteith, svp_from_t, delta_svp, psy_const)
from enum import Enum
import voluptuous as vol
from homeassistant.const import (
    CONF_LATITUDE,
    CONF_ELEVATION,
)
from ..localize import localize
#v1 only, no longer used in v2
#from ...const import CONF_MAXIMUM_ET, DEFAULT_MAXIMUM_ET
_LOGGER = logging.getLogger(__name__)


class SOLRAD_behavior(Enum):

    EstimateFromTemp="1"
    EstimateFromSunHours="2"
    DontEstimate="3"

CONF_COASTAL = "coastal"
CONF_SOLRAD_BEHAVIOR = "solrad_behavior"
CONF_FORECAST_DAYS="forecast_days"

DEFAULT_COASTAL = False
DEFAULT_SOLRAD_BEHAVIOR = SOLRAD_behavior.EstimateFromTemp
DEFAULT_FORECAST_DAYS = 0

MAPPING_DEWPOINT = "Dewpoint"
MAPPING_EVAPOTRANSPIRATION = "Evapotranspiration"
MAPPING_HUMIDITY = "Humidity"
MAPPING_MAX_TEMP = "Maximum Temperature"
MAPPING_MIN_TEMP = "Minimum Temperature"
MAPPING_PRECIPITATION = "Precipitation"
MAPPING_PRESSURE = "Pressure"
MAPPING_SOLRAD = "Solar Radiation"
MAPPING_TEMPERATURE = "Temperature"
MAPPING_WINDSPEED = "Windspeed"

SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_COASTAL, default=DEFAULT_COASTAL): vol.Coerce(bool), #is really required, but otherwise the UI shows a * near the checkbox
        vol.Required(CONF_SOLRAD_BEHAVIOR, default=DEFAULT_SOLRAD_BEHAVIOR): vol.Coerce(SOLRAD_behavior),
        vol.Required(CONF_FORECAST_DAYS, default=DEFAULT_FORECAST_DAYS): vol.Coerce(int),
    }
)

class PyETO(SmartIrrigationCalculationModule):
    def __init__(self, hass, config: {}) -> None:
        super().__init__(name="PyETO", description=localize("calcmodules.pyeto.description",hass.config.language)+".", schema=SCHEMA, config=config)
        self._hass = hass
        self._latitude = hass.config.as_dict().get(CONF_LATITUDE)
        self._elevation = hass.config.as_dict().get(CONF_ELEVATION)
        self._coastal = DEFAULT_COASTAL
        self._forecast_days = DEFAULT_FORECAST_DAYS
        self._solrad_behavior = DEFAULT_SOLRAD_BEHAVIOR
        if config:
            self._coastal = config.get(CONF_COASTAL,DEFAULT_COASTAL)
            self._solrad_behavior = config.get(CONF_SOLRAD_BEHAVIOR,DEFAULT_SOLRAD_BEHAVIOR)
            self._forecast_days = int(config.get(CONF_FORECAST_DAYS,DEFAULT_FORECAST_DAYS))



    def calculate(self,weather_data, forecast_data):
        delta = 0
        deltas = []
        if weather_data:
            deltas.append(self.calculate_et_for_day(weather_data))
            #loop over the forecast days
            for x in range(self._forecast_days):
                if len(forecast_data)-1 >= x:
                    deltas.append(self.calculate_et_for_day(forecast_data[x]))
        #return average of the collected deltas
        delta = mean(deltas)
        return delta

    def calculate_et_for_day(self,weather_data):
        if weather_data:
            tdew = weather_data.get(MAPPING_DEWPOINT)
            temp_c_min = weather_data.get(MAPPING_MIN_TEMP)
            temp_c_max = weather_data.get(MAPPING_MAX_TEMP)
            wind_m_s = weather_data.get(MAPPING_WINDSPEED)
            atmos_pres = weather_data.get(MAPPING_PRESSURE)
            sol_rad = weather_data.get(MAPPING_SOLRAD)
            precip = weather_data.get(MAPPING_PRECIPITATION)
            if tdew is not None and temp_c_min is not None and temp_c_max is not None and wind_m_s is not None and atmos_pres is not None:
                day_of_year = datetime.datetime.now().timetuple().tm_yday

                sha = sunset_hour_angle(deg2rad(self._latitude), sol_dec(day_of_year))
                daylight_hoursvar = daylight_hours(sha)

                ird = inv_rel_dist_earth_sun(day_of_year)
                et_radvar = et_rad(deg2rad(self._latitude), sol_dec(day_of_year), sha, ird)

                cs_radvar = cs_rad(self._elevation, et_radvar)

                # if we need to calculate solar_radiation we need to override the value passed in.
                if self._solrad_behavior is SOLRAD_behavior.EstimateFromSunHours or self._solrad_behavior is SOLRAD_behavior.EstimateFromTemp or sol_rad is None:
                    if self._solrad_behavior is SOLRAD_behavior.EstimateFromTemp:
                        sol_rad = sol_rad_from_t(
                            et_radvar, cs_radvar, temp_c_min, temp_c_max, self._coastal
                        )
                    else:
                        # this is the default behavior for version < 0.0.50
                        sol_rad = sol_rad_from_sun_hours(
                            daylight_hoursvar, 0.8 * daylight_hoursvar, et_radvar
                        )
                net_in_sol_radvar = net_in_sol_rad(sol_rad=sol_rad, albedo=0.23)
                avp = avp_from_tdew(tdew)
                net_out_lw_radvar = net_out_lw_rad(
                    convert.celsius2kelvin(temp_c_min),
                    convert.celsius2kelvin(temp_c_max),
                    sol_rad,
                    cs_radvar,
                    avp,
                )
                net_radvar = net_rad(net_in_sol_radvar, net_out_lw_radvar)

                # experiment in v0.0.71: do not pass in day temperature (temp_c) but instead the average of temp_max and temp_min
                # see https://github.com/jeroenterheerdt/HAsmartirrigation/issues/70
                temp_c = (temp_c_min + temp_c_max) / 2.0

                eto = fao56_penman_monteith(
                    net_rad=net_radvar,
                    t=convert.celsius2kelvin(temp_c),
                    ws=wind_m_s,
                    svp=svp_from_t(temp_c),
                    avp=avp,
                    delta_svp=delta_svp(temp_c),
                    psy=psy_const(
                        atmos_pres / 10
                    ),  # value stored is in hPa, but needs to be provided in kPa
                )

                #beta25: temporarily removing all rounds to see if we can find the math issue reported in #186
                #delta = round(precip-eto,1)
                delta = precip-eto
                return delta
        return 0