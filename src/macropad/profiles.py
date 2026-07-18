from dataclasses import dataclass

import yaml
from evdev import ecodes

from .config import (
    BindingConfig,
    KeyboardConfig,
    LayerConfig,
    ProfileConfig,
    ProfileValidationError,
)
from .handlers import Handler, KeyboardHandler


PROFILE_FIELDS = {'device', 'version', 'bindings', 'layers'}
EVENT_NAMES = {'up', 'down', 'hold', 'double_tap', 'triple_tap'}
KEY_NAMES = {
    key_name
    for key_names in ecodes.KEY.values()
    for key_name in (key_names if isinstance(key_names, list) else [key_names])
}


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


@dataclass
class Profile:
    config: ProfileConfig
    handler: Handler

    @property
    def device(self) -> str:
        return self.config.device

    @property
    def version(self) -> str:
        return self.config.version

    def dump(self) -> str:
        return yaml.dump(self.config.to_data(), sort_keys=False)


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

    return ProfileConfig(
        device=device,
        version=version,
        keyboard=KeyboardConfig(bindings=bindings, layers=layers),
        source=source,
    )


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
            raise ProfileValidationError(source, f'{layer_path}.{field_name}', 'unsupported layer field')
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
        raise ProfileValidationError(source, path, 'expected a command string or non-empty list of commands')
    return tuple(
        _parse_action(action, source, f'{path}[{index}]')
        for index, action in enumerate(actions)
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


def create_from_data(profile_data: ProfileConfig) -> Profile:
    return Profile(
        config=profile_data,
        handler=KeyboardHandler(profile_data.keyboard),
    )


def merge_data(profile_datas: list[ProfileConfig]) -> ProfileConfig:
    if not profile_datas:
        raise ValueError('No profile data to merge')

    device = profile_datas[0].device
    version = profile_datas[0].version
    merged_bindings = {}
    merged_layers = {}

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

    return ProfileConfig(
        device=device,
        version=version,
        keyboard=KeyboardConfig(bindings=merged_bindings, layers=merged_layers),
        source='<merged profile>',
    )


def create_sample(device):
    config = ProfileConfig(
        device=device.name,
        version='1',
        keyboard=KeyboardConfig(
            bindings={
                'KEY_UP': BindingConfig(actions={
                    'up': ("notify-send Hey! 'Hello from macropad!'",),
                }),
            },
            layers={},
        ),
    )
    return create_from_data(config)
