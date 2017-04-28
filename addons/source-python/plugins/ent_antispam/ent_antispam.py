# =============================================================================
# >> IMPORTS
# =============================================================================
# Python
from configparser import ConfigParser
import json

# Source.Python
from commands.typed import TypedServerCommand
from core import echo_console
from engines.server import global_vars
from filters.entities import EntityIter
from listeners import OnLevelEnd, OnLevelInit
from listeners.tick import Delay, Repeat

# Ent AntiSpam
from .core.paths import ENT_ANTISPAM_CFG_PATH


# =============================================================================
# >> FUNCTIONS
# =============================================================================
def get_server_file(path):
    server_path = path.dirname() / (path.namebase + "_server" + path.ext)
    if server_path.isfile():
        return server_path
    return path


def reload_configs():
    global config, entity_actions

    config = ConfigParser()
    config.read(get_server_file(ENT_ANTISPAM_CFG_PATH / "config.ini"))

    with open(get_server_file(
            ENT_ANTISPAM_CFG_PATH / "entity_actions.json")) as f:

        entity_actions = json.load(f)


def get_min_frames_per_interval():
    value = config['frame_measurement']['min_frames_per_interval']
    if value.lower() == "auto":
        return int(
            float(config['frame_measurement']['interval']) /
            global_vars.interval_per_tick *
            MIN_TICKS_PER_INTERVAL_AUTO_MULTIPLIER
        )

    return int(value)


def handle_entity(entity):
    classname = entity.classname
    for rule in entity_actions:
        if rule['classname'].endswith('*'):
            if not classname.startswith(rule['classname'][:-1]):
                continue
        else:
            if classname != rule['classname']:
                continue

        if rule['action'] == "remove":
            entity.remove()
            return True

        if rule['action'] == "freeze":
            entity.physics_object.motion_enabled = False
            return True

        break

    return False


def is_static_entity(entity):
    physics_obj = entity.physics_object

    return (physics_obj is None or
            physics_obj.is_static() or
            not physics_obj.collision_enabled or
            physics_obj.asleep or
            not physics_obj.motion_enabled)


def perform_check():
    max_entities_per_pile = int(config['piles']['max_entities_per_pile'])
    pile_radius = int(config['piles']['pile_radius'])

    # Step 1. Collect all networked entities
    ent_pos = []
    for entity in EntityIter():
        ent_pos.append((entity, entity.index, entity.origin))

    # Step 2. Detect piles to clear
    pile_radius_sqr = pile_radius ** 2
    piles_to_clear = []
    for pile_entity, pile_index, pile_origin in ent_pos:
        pile = []
        for entity, index, origin in ent_pos:
            if pile_origin.get_distance_sqr(origin) > pile_radius_sqr:
                continue

            if is_static_entity(entity):
                continue

            pile.append((entity, entity.index))

        if len(pile) > max_entities_per_pile:
            piles_to_clear.append(pile)

    # Step 3. Clear the piles
    handled_indexes = []
    handled_entities_count = 0
    for pile in piles_to_clear:
        for entity, index in pile:
            if index in handled_indexes:
                continue

            if handle_entity(entity):
                handled_entities_count += 1

            handled_indexes.append(index)

    # Step 4. Push some stats
    global total_checks_issued, total_handled_entities_count
    total_checks_issued += 1
    total_handled_entities_count += handled_entities_count


# =============================================================================
# >> GLOBAL VARIABLES
# =============================================================================
MIN_TICKS_PER_INTERVAL_AUTO_MULTIPLIER = 0.95

config = None
entity_actions = None
reload_configs()

total_handled_entities_count = 0
total_checks_issued = 0


# =============================================================================
# >> CLASSES
# =============================================================================
class FrameWatcher:
    def __init__(self):
        self._repeat = Repeat(self._watch)
        self._last_watch_frame = None
        self._last_delta_frame = None
        self._min_frames_per_interval = get_min_frames_per_interval()

    def _watch(self):
        current_frame = global_vars.frame_count
        if self._last_watch_frame is not None:
            self._last_delta_frame = current_frame - self._last_watch_frame
            if self._last_delta_frame <= self._min_frames_per_interval:
                perform_check()

        self._last_watch_frame = current_frame

    def start(self):
        self._repeat.start(float(config['frame_measurement']['interval']))

    def stop(self):
        self._repeat.stop()
        self._last_watch_frame = None

    def reload_config(self):
        self._min_frames_per_interval = get_min_frames_per_interval()

        self.stop()
        self.start()

    @property
    def last_frame_rate(self):
        if self._last_delta_frame is None:
            return -1

        return self._last_delta_frame / float(
            config['frame_measurement']['interval'])

    @property
    def last_frame_count(self):
        if self._last_delta_frame is None:
            return -1

        return self._last_delta_frame

frame_watcher = FrameWatcher()


# =============================================================================
# >> COMMANDS
# =============================================================================
@TypedServerCommand(['ent_antispam', 'stats'])
def typed_server_ent_antispam_stats(command_info):
    min_frames_per_interval = get_min_frames_per_interval()

    echo_console("[Entity AntiSpam Stats]")
    echo_console("Server reference tickrate: {:.2f}".format(
        1.0 / global_vars.interval_per_tick))
    echo_console("Last measured frame rate: {:.2f} ({} frames)".format(
        frame_watcher.last_frame_rate, frame_watcher.last_frame_count))
    echo_console("Lag is detected at: {:.2f} ({} frames)\n".format(
        min_frames_per_interval /
        float(config['frame_measurement']['interval']),
        min_frames_per_interval
    ))
    echo_console("Total checks issued this level: {}".format(
        total_checks_issued))
    echo_console("Total entities handled on this level: {}".format(
        total_handled_entities_count))


@TypedServerCommand(['ent_antispam', 'reload_configs'])
def typed_server_ent_antispam_reload_configs(command_info):
    reload_configs()
    frame_watcher.reload_config()
    echo_console("Reloaded configs, frame watcher was restarted")


# =============================================================================
# >> LISTENERS
# =============================================================================
@OnLevelInit
def listener_on_level_init(map_name):
    global total_checks_issued, total_handled_entities_count
    total_checks_issued = 0
    total_handled_entities_count = 0

    Delay(float(config['frame_measurement']['level_init_delay']),
          frame_watcher.start)


@OnLevelEnd
def listener_on_level_end():
    frame_watcher.stop()
