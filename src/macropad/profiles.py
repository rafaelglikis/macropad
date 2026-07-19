from dataclasses import dataclass

import yaml
from evdev import ecodes

from .config import (
    BindingConfig,
    KeyboardConfig,
    LayerConfig,
    LayerReference,
    ProfileConfig,
    ProfileValidationError,
    TimingConfig,
)

PROFILE_FIELDS = {'device', 'version', 'timing', 'bindings', 'layers'}
EVENT_NAMES = {'up', 'down', 'hold', 'double_tap', 'triple_tap'}
TIMING_BOUNDS = {
    'multi_tap_ms': (1, 5000),
    'one_shot_timeout_ms': (1, 3_600_000),
}
KEY_NAMES = {
    key_name
    for key_names in ecodes.KEY.values()
    for key_name in (key_names if isinstance(key_names, list) else [key_names])
}


@dataclass(frozen=True)
class PreparedProfile:
    paths: tuple[str, ...]
    config: ProfileConfig

    @property
    def device_name(self) -> str:
        return self.config.device


class StrictSafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        if not isinstance(node, yaml.nodes.MappingNode):
            return super().construct_mapping(node, deep=deep)

        self.flatten_mapping(node)
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                hash(key)
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    'while constructing a mapping',
                    node.start_mark,
                    'found an unhashable key',
                    key_node.start_mark,
                ) from error
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    'while constructing a mapping',
                    node.start_mark,
                    f'found duplicate key {key!r}',
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def load_yml(filename: str) -> ProfileConfig:
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            profile_data = yaml.load(file, Loader=StrictSafeLoader)
    except yaml.YAMLError as error:
        raise ProfileValidationError(str(filename), '', f'invalid YAML: {error}') from error

    return validate_profile_data(profile_data, source=str(filename))


def validate_profile_data(profile_data, source: str = '<profile>') -> ProfileConfig:
    if not isinstance(profile_data, dict):
        raise ProfileValidationError(source, '', 'expected a YAML mapping')

    for field_name in profile_data:
        if not isinstance(field_name, str):
            raise ProfileValidationError(source, '', 'profile field names must be strings')

    unknown_fields = set(profile_data) - PROFILE_FIELDS
    if unknown_fields:
        field_name = sorted(unknown_fields)[0]
        raise ProfileValidationError(source, field_name, 'unsupported profile field')

    device = profile_data.get('device')
    if not isinstance(device, str) or not device.strip():
        raise ProfileValidationError(source, 'device', 'expected a non-empty string')

    version = profile_data.get('version', '1')
    if isinstance(version, bool) or not isinstance(version, (str, int)):
        raise ProfileValidationError(source, 'version', 'expected 1 or "1"')
    version = str(version)
    if version != '1':
        raise ProfileValidationError(source, 'version', f'unsupported profile version {version!r}')

    bindings, inline_layers = _parse_bindings(
        profile_data.get('bindings', {}),
        source,
        'bindings',
    )
    layers = _parse_layers(profile_data.get('layers', {}), source, 'layers')
    layers = _merge_layers(layers, inline_layers, source)
    if 'timing' in profile_data:
        timing, timing_fields = _parse_timing(profile_data['timing'], source)
    else:
        timing, timing_fields = TimingConfig(), frozenset()

    return ProfileConfig(
        device=device,
        version=version,
        keyboard=KeyboardConfig(bindings=bindings, layers=layers, timing=timing),
        source=source,
        layer_references=_collect_layer_references(profile_data),
        timing_fields=timing_fields,
    )


def _parse_timing(timing, source: str) -> tuple[TimingConfig, frozenset[str]]:
    if not isinstance(timing, dict):
        raise ProfileValidationError(source, 'timing', 'expected a timing mapping')

    for field_name in timing:
        if not isinstance(field_name, str):
            raise ProfileValidationError(source, 'timing', 'timing field names must be strings')
    unknown_fields = set(timing) - TIMING_BOUNDS.keys()
    if unknown_fields:
        field_name = sorted(unknown_fields)[0]
        raise ProfileValidationError(source, f'timing.{field_name}', 'unsupported timing field')

    values = {}
    for field_name, (minimum, maximum) in TIMING_BOUNDS.items():
        if field_name not in timing:
            continue
        value = timing[field_name]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ProfileValidationError(
                source,
                f'timing.{field_name}',
                f'expected an integer from {minimum} to {maximum}',
            )
        values[field_name] = value
    return TimingConfig(**values), frozenset(timing)


def _parse_bindings(
    bindings,
    source: str,
    path: str,
    allow_inline_layers: bool = True,
) -> tuple[dict[str, BindingConfig], dict[str, LayerConfig]]:
    if not isinstance(bindings, dict):
        raise ProfileValidationError(source, path, 'expected a mapping of key names')

    parsed_bindings = {}
    inline_layer_bindings = {}
    for key_name, binding in bindings.items():
        key_path = f'{path}.{key_name}'
        if not isinstance(key_name, str) or not key_name.strip():
            raise ProfileValidationError(source, path, 'key names must be non-empty strings')
        if key_name not in KEY_NAMES:
            raise ProfileValidationError(source, key_path, 'unknown evdev key name')

        parsed_binding, binding_layers = _parse_binding(
            binding,
            source,
            key_path,
            allow_inline_layers=allow_inline_layers,
        )
        parsed_bindings[key_name] = parsed_binding
        for layer_name, layer_binding in binding_layers.items():
            inline_layer_bindings.setdefault(layer_name, {})[key_name] = layer_binding

    return parsed_bindings, {
        layer_name: LayerConfig(bindings=layer_bindings)
        for layer_name, layer_bindings in inline_layer_bindings.items()
    }


def _parse_binding(
    binding,
    source: str,
    path: str,
    allow_inline_layers: bool,
    allow_shorthand: bool = True,
) -> tuple[BindingConfig, dict[str, BindingConfig]]:
    if isinstance(binding, str):
        if not allow_shorthand:
            raise ProfileValidationError(source, path, 'expected an event mapping')
        return BindingConfig(actions={'up': (_parse_action(binding, source, path),)}), {}

    if not isinstance(binding, dict):
        raise ProfileValidationError(source, path, 'expected a command string or event mapping')
    if not binding:
        raise ProfileValidationError(source, path, 'binding cannot be empty')

    actions = {}
    inline_layers = {}
    for event_name, event_actions in binding.items():
        event_path = f'{path}.{event_name}'
        if not isinstance(event_name, str):
            raise ProfileValidationError(source, path, 'event names must be strings')
        if event_name == 'layers':
            if not allow_inline_layers:
                raise ProfileValidationError(source, event_path, 'nested layers are not supported')
            inline_layers = _parse_inline_layers(event_actions, source, event_path)
            continue
        if event_name not in EVENT_NAMES:
            supported_events = ', '.join(sorted(EVENT_NAMES))
            raise ProfileValidationError(
                source,
                event_path,
                f'unsupported event; expected one of: {supported_events}',
            )
        actions[event_name] = _parse_actions(event_actions, source, event_path)

    return BindingConfig(actions=actions), inline_layers


def _parse_inline_layers(layers, source: str, path: str) -> dict[str, BindingConfig]:
    if not isinstance(layers, dict):
        raise ProfileValidationError(source, path, 'expected a mapping of layer names')

    parsed_layers = {}
    for layer_name, binding in layers.items():
        layer_path = f'{path}.{layer_name}'
        _validate_layer_name(layer_name, source, path)
        parsed_binding, _ = _parse_binding(
            binding,
            source,
            layer_path,
            allow_inline_layers=False,
            allow_shorthand=False,
        )
        parsed_layers[layer_name] = parsed_binding
    return parsed_layers


def _parse_layers(layers, source: str, path: str) -> dict[str, LayerConfig]:
    if not isinstance(layers, dict):
        raise ProfileValidationError(source, path, 'expected a mapping of layer names')

    parsed_layers = {}
    for layer_name, layer in layers.items():
        layer_path = f'{path}.{layer_name}'
        _validate_layer_name(layer_name, source, path)
        if not isinstance(layer, dict):
            raise ProfileValidationError(source, layer_path, 'expected a layer mapping')
        unknown_fields = set(layer) - {'bindings'}
        if unknown_fields:
            field_name = sorted(unknown_fields)[0]
            raise ProfileValidationError(
                source, f'{layer_path}.{field_name}', 'unsupported layer field'
            )
        if 'bindings' not in layer:
            raise ProfileValidationError(source, layer_path, 'missing bindings')
        bindings, _ = _parse_bindings(
            layer['bindings'],
            source,
            f'{layer_path}.bindings',
            allow_inline_layers=False,
        )
        parsed_layers[layer_name] = LayerConfig(bindings=bindings)
    return parsed_layers


def _validate_layer_name(layer_name, source: str, path: str) -> None:
    if not isinstance(layer_name, str) or not layer_name.strip():
        raise ProfileValidationError(source, path, 'layer names must be non-empty strings')


def _parse_actions(actions, source: str, path: str) -> tuple[str, ...]:
    if isinstance(actions, str):
        return (_parse_action(actions, source, path),)
    if not isinstance(actions, list) or not actions:
        raise ProfileValidationError(
            source, path, 'expected a command string or non-empty list of commands'
        )
    return tuple(
        _parse_action(action, source, f'{path}[{index}]') for index, action in enumerate(actions)
    )


def _parse_action(action, source: str, path: str) -> str:
    if not isinstance(action, str) or not action.strip():
        raise ProfileValidationError(source, path, 'commands must be non-empty strings')
    if not action.startswith('^'):
        return action

    command_parts = action[1:].split()
    if command_parts == ['default_layer']:
        return action
    if (
        len(command_parts) in (2, 3)
        and command_parts[0] == 'layer'
        and (len(command_parts) == 2 or command_parts[2] == 'once')
    ):
        return action
    raise ProfileValidationError(source, path, f'invalid handler command {action!r}')


def _collect_layer_references(profile_data: dict) -> tuple[LayerReference, ...]:
    references = []
    _collect_binding_references(profile_data.get('bindings', {}), 'bindings', references)
    for layer_name, layer in profile_data.get('layers', {}).items():
        _collect_binding_references(
            layer['bindings'],
            f'layers.{layer_name}.bindings',
            references,
        )
    return tuple(references)


def _collect_binding_references(
    bindings: dict,
    bindings_path: str,
    references: list[LayerReference],
) -> None:
    for key_name, binding in bindings.items():
        binding_path = f'{bindings_path}.{key_name}'
        if isinstance(binding, str):
            _collect_action_references(binding, binding_path, references)
            continue

        for event_name, actions in binding.items():
            event_path = f'{binding_path}.{event_name}'
            if event_name != 'layers':
                _collect_action_references(actions, event_path, references)
                continue
            for layer_name, layer_binding in actions.items():
                for layer_event_name, layer_actions in layer_binding.items():
                    _collect_action_references(
                        layer_actions,
                        f'{event_path}.{layer_name}.{layer_event_name}',
                        references,
                    )


def _collect_action_references(
    actions,
    path: str,
    references: list[LayerReference],
) -> None:
    commands = [actions] if isinstance(actions, str) else actions
    for index, command in enumerate(commands):
        command_parts = command[1:].split() if command.startswith('^') else []
        if command_parts[:1] != ['layer']:
            continue
        command_path = path if isinstance(actions, str) else f'{path}[{index}]'
        references.append(LayerReference(name=command_parts[1], path=command_path))


def _merge_layers(
    target_layers: dict[str, LayerConfig],
    source_layers: dict[str, LayerConfig],
    source_name: str,
) -> dict[str, LayerConfig]:
    merged_layers = dict(target_layers)
    for layer_name, source_layer in source_layers.items():
        if layer_name not in merged_layers:
            merged_layers[layer_name] = source_layer
            continue

        merged_bindings = dict(merged_layers[layer_name].bindings)
        for key_name, source_binding in source_layer.bindings.items():
            if key_name not in merged_bindings:
                merged_bindings[key_name] = source_binding
                continue
            merged_bindings[key_name] = _merge_binding(
                merged_bindings[key_name],
                source_binding,
                f'layers.{layer_name}.bindings.{key_name}',
                source_name,
            )
        merged_layers[layer_name] = LayerConfig(bindings=merged_bindings)
    return merged_layers


def _merge_binding(
    target: BindingConfig,
    source: BindingConfig,
    path: str,
    source_name: str,
) -> BindingConfig:
    actions = dict(target.actions)
    for event_name, commands in source.actions.items():
        if event_name not in actions:
            actions[event_name] = commands
            continue
        if actions[event_name] == commands:
            continue
        raise ProfileValidationError(
            source_name,
            f'{path}.{event_name}',
            'conflicts with an earlier profile fragment',
        )
    return BindingConfig(actions=actions)


def merge_data(profile_datas: list[ProfileConfig]) -> ProfileConfig:
    if not profile_datas:
        raise ValueError('No profile data to merge')

    device = profile_datas[0].device
    version = profile_datas[0].version
    merged_bindings = {}
    merged_layers = {}
    default_timing = TimingConfig()
    merged_timing_values = {
        'multi_tap_ms': default_timing.multi_tap_ms,
        'one_shot_timeout_ms': default_timing.one_shot_timeout_ms,
    }
    merged_timing_fields = set()

    for config in profile_datas:
        if config.device != device:
            raise ProfileValidationError(
                config.source,
                'device',
                f'cannot merge with profile for {device!r}',
            )
        if config.version != version:
            raise ProfileValidationError(
                config.source,
                'version',
                f'cannot merge version {config.version!r} with version {version!r}',
            )

        for field_name in TIMING_BOUNDS:
            if field_name not in config.timing_fields:
                continue
            value = getattr(config.keyboard.timing, field_name)
            if field_name in merged_timing_fields and merged_timing_values[field_name] != value:
                raise ProfileValidationError(
                    config.source,
                    f'timing.{field_name}',
                    'conflicts with an earlier profile fragment',
                )
            merged_timing_values[field_name] = value
            merged_timing_fields.add(field_name)

        for key_name, source_binding in config.keyboard.bindings.items():
            if key_name not in merged_bindings:
                merged_bindings[key_name] = source_binding
                continue
            merged_bindings[key_name] = _merge_binding(
                merged_bindings[key_name],
                source_binding,
                f'bindings.{key_name}',
                config.source,
            )
        merged_layers = _merge_layers(merged_layers, config.keyboard.layers, config.source)

    merged_profile = ProfileConfig(
        device=device,
        version=version,
        keyboard=KeyboardConfig(
            bindings=merged_bindings,
            layers=merged_layers,
            timing=TimingConfig(**merged_timing_values),
        ),
        source='<merged profile>',
        timing_fields=merged_timing_fields,
    )
    _validate_merged_profile(profile_datas, merged_profile)
    return merged_profile


def prepare_profiles(profile_paths: list[str]) -> list[PreparedProfile]:
    loaded_profiles = []
    for profile_path in profile_paths:
        loaded_profiles.append((profile_path, load_yml(profile_path)))

    return prepare_loaded_profiles(loaded_profiles)


def prepare_loaded_profiles(
    loaded_profiles: list[tuple[str, ProfileConfig]],
) -> list[PreparedProfile]:
    profiles_by_device = {}

    for profile_path, profile_data in loaded_profiles:
        profiles_by_device.setdefault(profile_data.device, []).append((profile_path, profile_data))

    prepared_profiles = []
    for profile_fragments in profiles_by_device.values():
        paths = tuple(profile_path for profile_path, _ in profile_fragments)
        config = merge_data([profile_data for _, profile_data in profile_fragments])
        prepared_profiles.append(PreparedProfile(paths, config))

    return prepared_profiles


def _validate_merged_profile(
    profile_fragments: list[ProfileConfig], merged_profile: ProfileConfig
) -> None:
    has_base_action = any(binding.actions for binding in merged_profile.keyboard.bindings.values())
    if not has_base_action:
        raise ProfileValidationError(
            f'device {merged_profile.device!r}',
            'bindings',
            'expected at least one reachable base action',
        )

    layer_names = set(merged_profile.keyboard.layers)
    for profile_fragment in profile_fragments:
        for reference in profile_fragment.layer_references:
            if reference.name in layer_names:
                continue
            raise ProfileValidationError(
                profile_fragment.source,
                reference.path,
                f'references unknown layer {reference.name!r}',
            )
