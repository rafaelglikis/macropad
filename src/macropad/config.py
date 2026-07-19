from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Generic, TypeVar

Key = TypeVar('Key')
Value = TypeVar('Value')


class FrozenDict(Mapping[Key, Value], Generic[Key, Value]):
    __slots__ = ('_items',)

    def __init__(
        self,
        values: Mapping[Key, Value] | Iterable[tuple[Key, Value]] = (),
    ):
        object.__setattr__(self, '_items', tuple(dict(values).items()))

    def __setattr__(self, name, value):
        raise AttributeError('FrozenDict is immutable')

    def __getitem__(self, key: Key) -> Value:
        for item_key, item_value in self._items:
            if item_key == key:
                return item_value
        raise KeyError(key)

    def __iter__(self) -> Iterator[Key]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f'FrozenDict({dict(self._items)!r})'

    def __hash__(self) -> int:
        return hash(frozenset(self._items))

    def __reduce__(self):
        return type(self), (dict(self._items),)


class ProfileValidationError(ValueError):
    def __init__(self, source: str, path: str, message: str):
        self.source = source
        self.path = path
        self.message = message
        location = f'{source}: {path}' if path else source
        super().__init__(f'{location}: {message}')


@dataclass(frozen=True)
class BindingConfig:
    actions: FrozenDict[str, tuple[str, ...]]

    def __post_init__(self):
        object.__setattr__(
            self,
            'actions',
            FrozenDict(
                (event_name, tuple(commands)) for event_name, commands in self.actions.items()
            ),
        )

    def to_data(self) -> dict:
        return {event_name: list(commands) for event_name, commands in self.actions.items()}


@dataclass(frozen=True)
class LayerConfig:
    bindings: FrozenDict[str, BindingConfig]

    def __post_init__(self):
        object.__setattr__(self, 'bindings', FrozenDict(self.bindings))

    def to_data(self) -> dict:
        return {
            'bindings': {
                key_name: binding.to_data() for key_name, binding in self.bindings.items()
            },
        }


@dataclass(frozen=True)
class KeyboardConfig:
    bindings: FrozenDict[str, BindingConfig]
    layers: FrozenDict[str, LayerConfig]

    def __post_init__(self):
        object.__setattr__(self, 'bindings', FrozenDict(self.bindings))
        object.__setattr__(self, 'layers', FrozenDict(self.layers))

    def to_data(self) -> dict:
        data = {
            'bindings': {
                key_name: binding.to_data() for key_name, binding in self.bindings.items()
            },
        }
        if self.layers:
            data['layers'] = {
                layer_name: layer.to_data() for layer_name, layer in self.layers.items()
            }
        return data


@dataclass(frozen=True)
class LayerReference:
    name: str
    path: str


@dataclass(frozen=True)
class ProfileConfig:
    device: str
    version: str
    keyboard: KeyboardConfig
    source: str = field(default='<profile>', repr=False, compare=False)
    layer_references: tuple[LayerReference, ...] = field(default=(), repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, 'layer_references', tuple(self.layer_references))

    def to_data(self) -> dict:
        return {
            'device': self.device,
            'version': self.version,
        } | self.keyboard.to_data()
