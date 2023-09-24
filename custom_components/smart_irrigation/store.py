import datetime
import logging
import attr
from collections import OrderedDict
from typing import MutableMapping, cast
from homeassistant.loader import bind_hass
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util.unit_system import METRIC_SYSTEM

from .const import (
    ATTR_NEW_BUCKET_VALUE,
    CONF_AUTO_CALC_ENABLED,
    CONF_AUTO_CLEAR_ENABLED,
    CONF_AUTO_UPDATE_DELAY,
    CONF_AUTO_UPDATE_ENABLED,
    CONF_AUTO_UPDATE_INTERVAL,
    CONF_AUTO_UPDATE_SCHEDULE,
    CONF_CALC_TIME,
    CONF_CLEAR_TIME,
    CONF_DEFAULT_AUTO_CALC_ENABLED,
    CONF_DEFAULT_AUTO_CLEAR_ENABLED,
    CONF_DEFAULT_AUTO_UPDATE_DELAY,
    CONF_DEFAULT_AUTO_UPDATE_INTERVAL,
    CONF_DEFAULT_AUTO_UPDATE_SCHEDULE,
    CONF_DEFAULT_AUTO_UPDATED_ENABLED,
    CONF_DEFAULT_CALC_TIME,
    CONF_DEFAULT_CLEAR_TIME,
    CONF_DEFAULT_MAXIMUM_BUCKET,
    CONF_DEFAULT_MAXIMUM_DURATION,
    CONF_DEFAULT_USE_OWM,
    CONF_IMPERIAL,
    CONF_METRIC,
    CONF_UNITS,
    CONF_USE_OWM,
    DOMAIN,
    ZONE_LAST_CALCULATED,
    MAPPING_DATA_LAST_UPDATED,
    MAPPING_CONF_SENSOR,
    MAPPING_CONF_SOURCE,
    MAPPING_CONF_SOURCE_NONE,
    MAPPING_CONF_SOURCE_OWM,
    MAPPING_CONF_SOURCE_SENSOR,
    MAPPING_CONF_UNIT,
    MAPPING_DATA,
    MAPPING_DEWPOINT,
    MAPPING_EVAPOTRANSPIRATION,
    MAPPING_HUMIDITY,
    MAPPING_ID,
    MAPPING_MAPPINGS,
    MAPPING_MAX_TEMP,
    MAPPING_MIN_TEMP,
    MAPPING_NAME,
    MAPPING_PRECIPITATION,
    MAPPING_PRESSURE,
    MAPPING_SOLRAD,
    MAPPING_TEMPERATURE,
    MAPPING_WINDSPEED,
    MODULE_CONFIG,
    MODULE_DIR,
    MODULE_ID,
    MODULE_NAME,
    MODULE_DESCRIPTION,
    MODULE_SCHEMA,
    START_EVENT_FIRED_TODAY,
    ZONE_BUCKET,
    ZONE_ID,
    ZONE_LEAD_TIME,
    ZONE_MAPPING,
    ZONE_MAXIMUM_BUCKET,
    ZONE_MAXIMUM_DURATION,
    ZONE_MODULE,
    ZONE_MULTIPLIER,
    ZONE_NAME,
    ZONE_SIZE,
    ZONE_STATE_AUTOMATIC,
    ZONE_THROUGHPUT,
    ZONE_STATE,
    ZONE_DURATION,
)
from .localize import localize
from .helpers import loadModules

_LOGGER = logging.getLogger(__name__)

DATA_REGISTRY = f"{DOMAIN}_storage"
STORAGE_KEY = f"{DOMAIN}.storage"
STORAGE_VERSION = 3
SAVE_DELAY = 10


@attr.s(slots=True, frozen=True)
class ZoneEntry:
    """Zone storage Entry."""

    id = attr.ib(type=int, default=None)
    name = attr.ib(type=str, default=None)
    size = attr.ib(type=float, default=0.0)
    throughput = attr.ib(type=float, default=0.0)
    state = attr.ib(type=str, default="automatic")
    bucket = attr.ib(type=float, default=0)
    old_bucket = attr.ib(type=float, default=0)
    delta = attr.ib(type=float, default=0)
    duration = attr.ib(type=float, default=0)
    module = attr.ib(type=str,default=None)
    multiplier = attr.ib(type=float,default=1)
    explanation = attr.ib(type=str,default=None)
    mapping = attr.ib(type=str,default=None)
    lead_time = attr.ib(type=float, default=None)
    maximum_duration = attr.ib(type=float, default=CONF_DEFAULT_MAXIMUM_DURATION)
    maximum_bucket = attr.ib(type=float, default=CONF_DEFAULT_MAXIMUM_BUCKET)
    last_calculated = attr.ib(type=datetime, default=None)

@attr.s(slots=True, frozen=True)
class ModuleEntry:
    """Module storage Entry."""

    id = attr.ib(type=int, default=None)
    name = attr.ib(type=str, default=None)
    description = attr.ib(type=str, default=None)
    config = attr.ib(type=str, default=None)
    schema = attr.ib(type=str, default=None)

@attr.s(slots=True, frozen=True)
class MappingEntry:
    """Mapping storage Entry."""

    id = attr.ib(type=int, default=None)
    name = attr.ib(type=str, default=None)
    mappings = attr.ib(type=str,default=None)
    data = attr.ib(type=str,default="[]")
    data_last_updated = attr.ib(type=datetime, default=None)

@attr.s(slots=True, frozen=True)
class Config:
    """(General) Config storage Entry."""

    calctime = attr.ib(type=str, default=CONF_DEFAULT_CALC_TIME)
    units = attr.ib(type=str, default=None)
    use_owm = attr.ib(type=bool, default=False)
    autocalcenabled = attr.ib(type=bool,default=CONF_AUTO_CALC_ENABLED)
    autoupdateenabled = attr.ib(type=bool, default=CONF_AUTO_UPDATE_ENABLED)
    autoupdateschedule = attr.ib(type=str, default=CONF_DEFAULT_AUTO_UPDATE_SCHEDULE)
    autoupdatedelay = attr.ib(type=str, default=CONF_DEFAULT_AUTO_UPDATE_DELAY)
    autoupdateinterval = attr.ib(type=str, default=CONF_DEFAULT_AUTO_UPDATE_INTERVAL)
    autoclearenabled =attr.ib(type=bool,default=CONF_DEFAULT_AUTO_CLEAR_ENABLED)
    cleardatatime = attr.ib(type=str, default=CONF_DEFAULT_CLEAR_TIME)
    starteventfiredtoday = attr.ib(type=bool, default=False)

class MigratableStore(Store):
    async def _async_migrate_func(self, old_version, data: dict):
        return data

class SmartIrrigationStorage:
    """Class to hold Smart Irrigation configuration data."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the storage."""
        self.hass = hass
        self.config: Config = Config()
        self.zones: MutableMapping[ZoneEntry] = {}
        self.modules : MutableMapping[ModuleEntry] = {}
        self.mappings: MutableMapping[MappingEntry] = {}
        self._store = MigratableStore(hass, STORAGE_VERSION, STORAGE_KEY)

    async def async_load(self) -> None:
        """Load the registry of schedule entries."""
        data = await self._store.async_load()
        config: Config = Config(calctime=CONF_DEFAULT_CALC_TIME,
                                units=CONF_METRIC if self.hass.config.units is METRIC_SYSTEM else CONF_IMPERIAL,
                                use_owm = CONF_DEFAULT_USE_OWM,
                                autocalcenabled = CONF_DEFAULT_AUTO_CALC_ENABLED,
                                autoupdateenabled = CONF_DEFAULT_AUTO_UPDATED_ENABLED,
                                autoupdateschedule = CONF_DEFAULT_AUTO_UPDATE_SCHEDULE,
                                autoupdatedelay = CONF_DEFAULT_AUTO_UPDATE_DELAY,
                                autoupdateinterval = CONF_DEFAULT_AUTO_UPDATE_INTERVAL,
                                autoclearenabled = CONF_DEFAULT_AUTO_CLEAR_ENABLED,
                                cleardatatime = CONF_DEFAULT_CLEAR_TIME,
                                starteventfiredtoday = False
                                )
        zones: "OrderedDict[str, ZoneEntry]" = OrderedDict()
        modules: "OrderedDict[str, ModuleEntry]" = OrderedDict()
        mappings: "OrderedDict[str, MappingEntry]" = OrderedDict()


        if data is not None:
            config = Config(calctime=data["config"].get(CONF_CALC_TIME, CONF_DEFAULT_CALC_TIME),
                            units=data["config"].get(CONF_UNITS,CONF_METRIC if self.hass.config.units is METRIC_SYSTEM else CONF_IMPERIAL),
                            use_owm=data["config"].get(CONF_USE_OWM,CONF_DEFAULT_USE_OWM), autocalcenabled=data["config"].get(CONF_AUTO_CALC_ENABLED, CONF_DEFAULT_AUTO_CALC_ENABLED),
                            autoupdateenabled=data["config"].get(CONF_AUTO_UPDATE_ENABLED, CONF_DEFAULT_AUTO_UPDATED_ENABLED),
                            autoupdateschedule=data["config"].get(CONF_AUTO_UPDATE_SCHEDULE, CONF_DEFAULT_AUTO_UPDATE_SCHEDULE),
                            autoupdatedelay=data["config"].get(CONF_AUTO_UPDATE_DELAY, CONF_DEFAULT_AUTO_UPDATE_DELAY),
                            autoupdateinterval=data["config"].get(CONF_AUTO_UPDATE_INTERVAL, CONF_DEFAULT_AUTO_UPDATE_INTERVAL),
                            autoclearenabled=data["config"].get(CONF_AUTO_CLEAR_ENABLED, CONF_DEFAULT_AUTO_CLEAR_ENABLED),
                            cleardatatime=data["config"].get(CONF_CLEAR_TIME, CONF_DEFAULT_CLEAR_TIME),
                            starteventfiredtoday = data["config"].get(START_EVENT_FIRED_TODAY, False)
            )

            if "zones" in data:
                for zone in data["zones"]:
                    zones[zone[ZONE_ID]] = ZoneEntry(
                        id=zone[ZONE_ID],
                        name=zone[ZONE_NAME],
                        size=zone[ZONE_SIZE],
                        throughput=zone[ZONE_THROUGHPUT],
                        state=zone[ZONE_STATE],
                        bucket=zone[ZONE_BUCKET],
                        duration=zone[ZONE_DURATION],
                        module=zone[ZONE_MODULE],
                        multiplier=zone[ZONE_MULTIPLIER],
                        mapping=zone[ZONE_MAPPING],
                        lead_time = zone[ZONE_LEAD_TIME],
                        maximum_duration = zone.get(ZONE_MAXIMUM_DURATION, CONF_DEFAULT_MAXIMUM_DURATION),
                        maximum_bucket = zone.get(ZONE_MAXIMUM_BUCKET, CONF_DEFAULT_MAXIMUM_BUCKET),
                        last_calculated = zone.get(ZONE_LAST_CALCULATED, None)
                    )
            if "modules" in data:
                for module in data["modules"]:
                    schema_from_code = None
                    modconfig = None
                    if MODULE_CONFIG in module:
                        modconfig = module[MODULE_CONFIG]
                    #load the calc modules and set up the schema
                    mods = loadModules(MODULE_DIR)
                    for mod in mods:
                        if mods[mod]["class"] == module[MODULE_NAME]:
                            m = getattr(mods[mod]["module"], mods[mod]["class"])
                            inst = m(self.hass, modconfig)
                            schema_from_code = inst.schema_serialized()
                            break
                    modules[module[MODULE_ID]] = ModuleEntry(
                        id= module[MODULE_ID],
                        name=module[MODULE_NAME],
                        description=module[MODULE_DESCRIPTION],
                        config=modconfig,
                        schema=schema_from_code
                    )
            if "mappings" in data:
                for mapping in data["mappings"]:
                    the_map = mapping.get(MAPPING_MAPPINGS)
                    #remove max and min temp is present in mapping, they should only be there for old versions.
                    if MAPPING_MAX_TEMP in the_map:
                        the_map.pop(MAPPING_MAX_TEMP)
                    if MAPPING_MIN_TEMP in the_map:
                        the_map.pop(MAPPING_MIN_TEMP)
                    mappings[mapping[MAPPING_ID]] = MappingEntry(
                        id= mapping[MAPPING_ID],
                        name=mapping[MAPPING_NAME],
                        mappings=the_map,
                        data=mapping.get(MAPPING_DATA),
                        data_last_updated = mapping.get(MAPPING_DATA_LAST_UPDATED, None)
                    )


        self.config = config
        self.zones = zones
        self.modules = modules
        self.mappings = mappings

    async def set_up_factory_defaults(self):
        if not self.zones:
            await self.async_factory_default_zones()
        if not self.modules:
            await self.async_factory_default_modules()
        if not self.mappings:
            await self.async_factory_default_mappings()

    async def async_factory_default_zones(self):
        new_zone1 = ZoneEntry(
            **{ZONE_ID: 0, ZONE_NAME: localize("defaults.default-zone", self.hass.config.language)+" 1", ZONE_SIZE: 50.5, ZONE_THROUGHPUT: 10.1,ZONE_MODULE:0,ZONE_MAPPING:0,ZONE_LEAD_TIME:0, ZONE_MAXIMUM_DURATION:CONF_DEFAULT_MAXIMUM_DURATION, ZONE_MAXIMUM_BUCKET: CONF_DEFAULT_MAXIMUM_BUCKET}
        )
        new_zone2 = ZoneEntry(
            **{ZONE_ID: 1, ZONE_NAME: localize("defaults.default-zone", self.hass.config.language)+" 2", ZONE_SIZE: 100.1, ZONE_THROUGHPUT: 20.2,ZONE_MODULE:0,ZONE_MAPPING: 0, ZONE_LEAD_TIME:0, ZONE_MAXIMUM_DURATION: CONF_DEFAULT_MAXIMUM_DURATION, ZONE_MAXIMUM_BUCKET: CONF_DEFAULT_MAXIMUM_BUCKET}
        )
        self.zones[0] = new_zone1
        self.zones[1] = new_zone2
        self.async_schedule_save()

    async def async_factory_default_modules(self):

        schema_from_code = None
        module0schema = None
        module1schema = None
        mods = loadModules(MODULE_DIR)
        for mod in mods:
            if mods[mod]["class"] in ["PyETO","Static"]:
                m = getattr(mods[mod]["module"], mods[mod]["class"])
                inst = m(self.hass, {})
                schema_from_code = inst.schema_serialized()
                if mods[mod]["class"] == "PyETO":
                    module0schema = schema_from_code
                elif mods[mod]["class"] == "Static":
                    module1schema = schema_from_code
        module0 = ModuleEntry(
            **{MODULE_ID: 0, MODULE_NAME: "PyETO", MODULE_DESCRIPTION:localize("calcmodules.pyeto.description",self.hass.config.language)+".",
               MODULE_SCHEMA: module0schema
               }
        )
        module1 = ModuleEntry(
            **{MODULE_ID: 1, MODULE_NAME: "Static", MODULE_DESCRIPTION:localize("calcmodules.static.description", self.hass.config.language)+".",
               MODULE_SCHEMA: module1schema
               }
        )
        self.modules[0] = module0
        self.modules[1] = module1
        self.async_schedule_save()

    async def async_factory_default_mappings(self):
        #this should be OWM mapping if OWM is defined...?
        mapping_source = ""
        if self.config.use_owm:
            #we're using owm
            mapping_source = MAPPING_CONF_SOURCE_OWM
        else:
            mapping_source = MAPPING_CONF_SOURCE_SENSOR
        mappings = [MAPPING_DEWPOINT, MAPPING_EVAPOTRANSPIRATION, MAPPING_HUMIDITY, MAPPING_MAX_TEMP, MAPPING_MIN_TEMP, MAPPING_PRECIPITATION,
                  MAPPING_PRESSURE, MAPPING_SOLRAD, MAPPING_TEMPERATURE, MAPPING_WINDSPEED]
        conf = {}
        for map in mappings:
            map_source = mapping_source
            #evapotranspiration and solrad can only come from a sensor or none
            if map in [MAPPING_EVAPOTRANSPIRATION, MAPPING_SOLRAD]:
                if self.config.use_owm:
                    map_source = MAPPING_CONF_SOURCE_NONE
                else:
                    map_source = MAPPING_CONF_SOURCE_SENSOR
            conf[map]={MAPPING_CONF_SOURCE: map_source, MAPPING_CONF_SENSOR:"", MAPPING_CONF_UNIT: ""}
        new_mapping1 = MappingEntry(
            **{MAPPING_ID: 0, MAPPING_NAME: localize("defaults.default-mapping", self.hass.config.language), MAPPING_MAPPINGS:conf
               }
        )
        self.mappings[0] = new_mapping1
        self.async_schedule_save()

    @callback
    def async_schedule_save(self) -> None:
        """Schedule saving the registry of Smart Irrigation."""
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    async def async_save(self) -> None:
        """Save the registry of Smart Irrigation."""
        await self._store.async_save(self._data_to_save())

    @callback
    def _data_to_save(self) -> dict:
        """Return data for the registry for Smart Irrigation to store in a file."""
        store_data = {
            "config": attr.asdict(self.config),
        }

        store_data["zones"] = [attr.asdict(entry) for entry in self.zones.values()]
        store_data["modules"]= [attr.asdict(entry) for entry in self.modules.values()]
        store_data["mappings"]= [attr.asdict(entry) for entry in self.mappings.values()]
        return store_data

    async def async_delete(self):
        """Delete config."""
        _LOGGER.warning("Removing Smart Irrigation configuration data!")
        await self._store.async_remove()
        #self.config = Config()
        #await self.async_factory_default_zones()
        #await self.async_factory_default_modules()

    @callback
    def async_get_config(self):
        return attr.asdict(self.config)

    @callback
    def async_update_config(self, changes: dict):
        """Update existing config."""

        old = self.config
        changes.pop('id', None)
        new = self.config = attr.evolve(old, **changes)
        self.async_schedule_save()
        return attr.asdict(new)

    @callback
    def async_get_zone(self, zone_id: int) -> ZoneEntry:
        """Get an existing ZoneEntry by id."""
        res = self.zones.get(int(zone_id))
        return attr.asdict(res) if res else None
        #res = None
        #for key,val in self.zones.items():
        #    if str(val.id) == str(zone_id):
        #        res = val
        #        break
        #return attr.asdict(res) if res else None

    @callback
    def async_get_zones(self):
        """Get all ZoneEntries"""
        # res = {}
        # for key, val in self.zones.items():
        #    res[key] = attr.asdict(val)
        # return res

        res = []
        for key, val in self.zones.items():
            res.append(attr.asdict(val))
        return res

    @callback
    def async_create_zone(self, data: dict) -> ZoneEntry:
        """Create a new ZoneEntry."""
        #zone_id = str(int(time.time()))
        #new_zone = ZoneEntry(**data, id=zone_id)
        new_zone = ZoneEntry(**data)
        self.zones[int(new_zone.id)] = new_zone
        self.async_schedule_save()
        return attr.asdict(new_zone)

    @callback
    def async_delete_zone(self, zone_id: int) -> None:
        """Delete ZoneEntry."""
        zone_id = int(zone_id)
        if zone_id in self.zones:
            del self.zones[zone_id]
            self.async_schedule_save()
            return True
        return False

    @callback
    def async_update_zone(self, zone_id: int, changes: dict) -> ZoneEntry:
        """Update existing zone."""
        zone_id = int(zone_id)
        old = self.zones[zone_id]
        if changes:
            # handle bucket value change
            if ATTR_NEW_BUCKET_VALUE in changes:
                changes[ZONE_BUCKET] = changes[ATTR_NEW_BUCKET_VALUE]
                changes.pop(ATTR_NEW_BUCKET_VALUE)
            #apply maximum bucket value
            if ZONE_MAXIMUM_BUCKET in changes and changes[ZONE_BUCKET]>changes[ZONE_MAXIMUM_BUCKET]:
                changes[ZONE_BUCKET] = changes[ZONE_MAXIMUM_BUCKET]
            # if bucket on zone is 0, then duration should be 0, but only if zone is automatic
            if ZONE_BUCKET in changes and changes[ZONE_BUCKET] == 0 and old.state == ZONE_STATE_AUTOMATIC:
                changes[ZONE_DURATION] = 0
            changes.pop('id', None)
            new = self.zones[zone_id] = attr.evolve(old, **changes)
        else:
            new = old
        self.async_schedule_save()
        return attr.asdict(new)

    @callback
    def async_get_module(self, module_id: int) -> ModuleEntry:
        """Get an existing ModuleEntry by id."""
        if module_id is not None:
            res = self.modules.get(int(module_id))
            return attr.asdict(res) if res else None
        return None

    @callback
    def async_get_modules(self):
        """Get all ModuleEntries"""
        # res = {}
        # for key, val in self.modules.items():
        #    res[key] = attr.asdict(val)
        # return res

        res = []
        for key, val in self.modules.items():
            res.append(attr.asdict(val))
        return res


    @callback
    def async_create_module(self, data: dict) -> ModuleEntry:
        """Create a new ModuleEntry."""
        #module_id = str(int(time.time()))
        #new_module = moduleEntry(**data, id=module_id)
        new_module = ModuleEntry(**data)
        self.modules[int(new_module.id)] = new_module
        self.async_schedule_save()
        return attr.asdict(new_module)

    @callback
    def async_delete_module(self, module_id: int) -> None:
        """Delete ModuleEntry."""
        if int(module_id) in self.modules:
            del self.modules[int(module_id)]
            self.async_schedule_save()
            return True
        return False

    @callback
    def async_update_module(self, module_id: int, changes: dict) -> ModuleEntry:
        """Update existing module."""
        module_id = int(module_id)
        old = self.modules[module_id]
        changes.pop('id', None)
        new = self.modules[module_id] = attr.evolve(old, **changes)
        self.async_schedule_save()
        return attr.asdict(new)

    @callback
    def async_get_mapping(self, mapping_id: int) -> MappingEntry:
        """Get an existing MappingEntry by id."""
        if mapping_id is not None:
            res = self.mappings.get(int(mapping_id))
            return attr.asdict(res) if res else None
        return None

    @callback
    def async_get_mappings(self):
        """Get all MappingEntries"""
        # res = {}
        # for key, val in self.modules.items():
        #    res[key] = attr.asdict(val)
        # return res

        res = []
        for key, val in self.mappings.items():
            res.append(attr.asdict(val))
        return res

    @callback
    def async_create_mapping(self, data: dict) -> MappingEntry:
        """Create a new MappingEntry."""
        new_mapping = MappingEntry(**data)
        self.mappings[int(new_mapping.id)] = new_mapping
        self.async_schedule_save()
        return attr.asdict(new_mapping)

    @callback
    def async_delete_mapping(self, mapping_id: str) -> None:
        """Delete MappingEntry."""
        mapping_id = int(mapping_id)
        if mapping_id in self.mappings:
            del self.mappings[mapping_id]
            self.async_schedule_save()
            return True
        return False

    @callback
    def async_update_mapping(self, mapping_id: int, changes: dict) -> MappingEntry:
        """Update existing mapping."""
        mapping_id = int(mapping_id)
        old = self.mappings[mapping_id]
        #make sure we don't override the ID
        changes.pop('id', None)
        new = self.mappings[mapping_id] = attr.evolve(old, **changes)
        self.async_schedule_save()
        return attr.asdict(new)

@bind_hass
async def async_get_registry(hass: HomeAssistant) -> SmartIrrigationStorage:
    """Return Smart Irrigation storage instance."""
    task = hass.data.get(DATA_REGISTRY)

    if task is None:

        async def _load_reg() -> SmartIrrigationStorage:
            registry = SmartIrrigationStorage(hass)
            await registry.async_load()
            return registry

        task = hass.data[DATA_REGISTRY] = hass.async_create_task(_load_reg())

    return cast(SmartIrrigationStorage, await task)
