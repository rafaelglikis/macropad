import pickle
import tempfile
import unittest

from macropad import profiles
from macropad.config import FrozenDict


class ProfileTests(unittest.TestCase):
    @staticmethod
    def _profile_data(**overrides):
        profile_data = {
            'device': 'Demo Device',
            'version': 1,
            'bindings': {
                'KEY_A': {
                    'up': 'a-command',
                    'double_tap': ['a-double-command'],
                    'layers': {
                        'mod': {
                            'up': '^default_layer',
                        },
                    },
                },
            },
        }
        profile_data.update(overrides)
        return profile_data

    def test_validation_returns_typed_config_and_normalizes_version(self):
        profile_config = profiles.validate_profile_data(
            self._profile_data(),
            source='demo.yml',
        )

        self.assertIsInstance(profile_config, profiles.ProfileConfig)
        self.assertIsInstance(profile_config.keyboard, profiles.KeyboardConfig)
        self.assertIsInstance(profile_config.keyboard.bindings['KEY_A'], profiles.BindingConfig)
        self.assertEqual('1', profile_config.version)
        self.assertEqual('demo.yml', profile_config.source)
        self.assertEqual(
            ('a-command',),
            profile_config.keyboard.bindings['KEY_A'].actions['up'],
        )

    def test_timing_defaults_preserve_existing_behavior(self):
        profile_config = profiles.validate_profile_data(self._profile_data())

        self.assertEqual(200, profile_config.keyboard.timing.multi_tap_ms)
        self.assertEqual(5000, profile_config.keyboard.timing.one_shot_timeout_ms)
        self.assertNotIn('timing', profile_config.to_data())

    def test_timing_fields_are_validated_and_normalized(self):
        profile_config = profiles.validate_profile_data(
            self._profile_data(
                timing={
                    'multi_tap_ms': 350,
                    'one_shot_timeout_ms': 7000,
                }
            )
        )

        self.assertEqual(350, profile_config.keyboard.timing.multi_tap_ms)
        self.assertEqual(7000, profile_config.keyboard.timing.one_shot_timeout_ms)
        self.assertEqual(
            {'multi_tap_ms': 350, 'one_shot_timeout_ms': 7000},
            profile_config.to_data()['timing'],
        )

    def test_timing_serialization_preserves_omitted_fields(self):
        profile_config = profiles.validate_profile_data(
            self._profile_data(timing={'multi_tap_ms': 350})
        )

        self.assertEqual({'multi_tap_ms': 350}, profile_config.to_data()['timing'])

    def test_timing_rejects_unknown_fields_and_out_of_bounds_values(self):
        invalid_cases = (
            (None, 'timing: expected a timing mapping'),
            ({'unknown': 1}, 'timing.unknown: unsupported timing field'),
            ({'multi_tap_ms': 0}, 'timing.multi_tap_ms: expected an integer from 1 to 5000'),
            (
                {'one_shot_timeout_ms': 3_600_001},
                'timing.one_shot_timeout_ms: expected an integer from 1 to 3600000',
            ),
            (
                {'multi_tap_ms': 200.0},
                'timing.multi_tap_ms: expected an integer from 1 to 5000',
            ),
        )
        for timing, expected_message in invalid_cases:
            with self.subTest(timing=timing):
                with self.assertRaises(profiles.ProfileValidationError) as context:
                    profiles.validate_profile_data(
                        self._profile_data(timing=timing),
                        source='timing.yml',
                    )

                self.assertEqual(f'timing.yml: {expected_message}', str(context.exception))

    def test_inline_layers_are_normalized_into_keyboard_config(self):
        profile_config = profiles.validate_profile_data(self._profile_data())

        self.assertNotIn('layers', profile_config.keyboard.bindings['KEY_A'].actions)
        self.assertEqual(
            ('^default_layer',),
            profile_config.keyboard.layers['mod'].bindings['KEY_A'].actions['up'],
        )

    def test_inline_layer_command_string_is_up_shorthand(self):
        profile_config = profiles.validate_profile_data(
            self._profile_data(
                bindings={
                    'KEY_A': {
                        'up': 'base-command',
                        'layers': {'mod': 'layer-command'},
                    },
                }
            )
        )

        self.assertEqual(
            ('layer-command',),
            profile_config.keyboard.layers['mod'].bindings['KEY_A'].actions['up'],
        )

    def test_layer_fallback_defaults_to_base_and_can_be_disabled(self):
        default_profile = profiles.validate_profile_data(
            self._profile_data(
                layers={
                    'mod': {
                        'bindings': {'KEY_B': 'layer-command'},
                    }
                }
            )
        )
        disabled_profile = profiles.validate_profile_data(
            self._profile_data(
                bindings={
                    'KEY_A': {
                        'up': 'base-command',
                        'layers': {'mod': 'layer-command'},
                    },
                },
                layers={'mod': {'fallback': 'none'}},
            )
        )

        self.assertEqual('base', default_profile.keyboard.layers['mod'].fallback)
        self.assertEqual('none', disabled_profile.keyboard.layers['mod'].fallback)
        self.assertIn('KEY_A', disabled_profile.keyboard.layers['mod'].bindings)
        self.assertEqual(
            {'bindings': {'KEY_A': {'up': ['layer-command']}}, 'fallback': 'none'},
            disabled_profile.keyboard.layers['mod'].to_data(),
        )

    def test_layer_rejects_invalid_fallback(self):
        for fallback in ('parent', True, []):
            with self.subTest(fallback=fallback):
                with self.assertRaises(profiles.ProfileValidationError) as context:
                    profiles.validate_profile_data(
                        self._profile_data(layers={'mod': {'fallback': fallback}}),
                        source='fallback.yml',
                    )

                self.assertEqual(
                    'fallback.yml: layers.mod.fallback: expected "base" or "none"',
                    str(context.exception),
                )

    def test_inline_and_top_level_layers_are_combined(self):
        profile_config = profiles.validate_profile_data(
            self._profile_data(
                layers={
                    'mod': {
                        'bindings': {
                            'KEY_A': {
                                'down': 'layer-down-command',
                            },
                        },
                    },
                }
            )
        )

        self.assertEqual(
            {
                'down': ('layer-down-command',),
                'up': ('^default_layer',),
            },
            profile_config.keyboard.layers['mod'].bindings['KEY_A'].actions,
        )

    def test_validation_rejects_removed_profile_options(self):
        for field_name in ('notifications', 'dry_run'):
            with self.subTest(field_name=field_name):
                with self.assertRaises(profiles.ProfileValidationError) as context:
                    profiles.validate_profile_data(
                        self._profile_data(**{field_name: True}),
                        source='legacy.yml',
                    )

                self.assertEqual(
                    f'legacy.yml: {field_name}: unsupported profile field',
                    str(context.exception),
                )

    def test_validation_reports_source_and_binding_path(self):
        profile_data = self._profile_data(
            bindings={
                'KEY_A': {
                    'tap': 'a-command',
                },
            }
        )

        with self.assertRaises(profiles.ProfileValidationError) as context:
            profiles.validate_profile_data(profile_data, source='broken.yml')

        self.assertIn('broken.yml: bindings.KEY_A.tap: unsupported event', str(context.exception))

    def test_validation_rejects_unknown_key_name(self):
        profile_data = self._profile_data(
            bindings={
                'KEY_NOT_REAL': 'a-command',
            }
        )

        with self.assertRaises(profiles.ProfileValidationError) as context:
            profiles.validate_profile_data(profile_data, source='broken.yml')

        self.assertEqual(
            'broken.yml: bindings.KEY_NOT_REAL: unknown evdev key name',
            str(context.exception),
        )

    def test_validation_rejects_non_string_actions(self):
        profile_data = self._profile_data(
            bindings={
                'KEY_A': {
                    'up': ['a-command', 42],
                },
            }
        )

        with self.assertRaises(profiles.ProfileValidationError) as context:
            profiles.validate_profile_data(profile_data, source='broken.yml')

        self.assertEqual(
            'broken.yml: bindings.KEY_A.up[1]: commands must be non-empty strings',
            str(context.exception),
        )

    def test_validation_rejects_invalid_handler_command(self):
        profile_data = self._profile_data(
            bindings={
                'KEY_A': {
                    'up': '^layer',
                },
            }
        )

        with self.assertRaises(profiles.ProfileValidationError) as context:
            profiles.validate_profile_data(profile_data, source='broken.yml')

        self.assertIn(
            'broken.yml: bindings.KEY_A.up: invalid handler command', str(context.exception)
        )

    def test_layer_modes_are_validated_with_momentary_restricted_to_down(self):
        profile_config = profiles.validate_profile_data(
            self._profile_data(
                bindings={
                    'KEY_A': {'down': '^layer mod momentary'},
                    'KEY_B': {'up': '^layer mod toggle'},
                    'KEY_C': {'up': '^layer mod once'},
                },
                layers={'mod': {'fallback': 'none'}},
            )
        )

        self.assertEqual(
            ('^layer mod momentary',),
            profile_config.keyboard.bindings['KEY_A'].actions['down'],
        )

        with self.assertRaises(profiles.ProfileValidationError) as context:
            profiles.validate_profile_data(
                self._profile_data(
                    bindings={'KEY_A': {'up': '^layer mod momentary'}},
                    layers={'mod': {'fallback': 'none'}},
                ),
                source='momentary.yml',
            )

        self.assertEqual(
            'momentary.yml: bindings.KEY_A.up: momentary layer command requires a down event',
            str(context.exception),
        )

        with self.assertRaises(profiles.ProfileValidationError) as context:
            profiles.validate_profile_data(
                self._profile_data(
                    bindings={
                        'KEY_A': {
                            'down': '^layer mod momentary',
                            'up': 'release-command',
                        }
                    },
                    layers={'mod': {'fallback': 'none'}},
                ),
                source='momentary.yml',
            )

        self.assertEqual(
            'momentary.yml: bindings.KEY_A.down: momentary layer command requires a down-only '
            'binding',
            str(context.exception),
        )

    def test_toggle_mode_is_restricted_to_release_resolved_events(self):
        for event_name in ('down', 'hold'):
            with self.subTest(event_name=event_name):
                with self.assertRaises(profiles.ProfileValidationError) as context:
                    profiles.validate_profile_data(
                        self._profile_data(
                            bindings={'KEY_A': {event_name: '^layer mod toggle'}},
                            layers={'mod': {'fallback': 'none'}},
                        ),
                        source='toggle.yml',
                    )

                self.assertEqual(
                    f'toggle.yml: bindings.KEY_A.{event_name}: toggle layer command requires one '
                    'of: double_tap, triple_tap, up',
                    str(context.exception),
                )

    def test_shell_command_ending_in_momentary_is_not_a_layer_command(self):
        profile_config = profiles.validate_profile_data(
            self._profile_data(
                bindings={
                    'KEY_A': {
                        'down': 'echo foo momentary',
                        'up': 'release-command',
                    }
                }
            )
        )

        self.assertEqual(
            ('echo foo momentary',),
            profile_config.keyboard.bindings['KEY_A'].actions['down'],
        )

    def test_load_yml_reports_filename_for_invalid_yaml(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml') as file:
            file.write('device: [')
            file.flush()

            with self.assertRaises(profiles.ProfileValidationError) as context:
                profiles.load_yml(file.name)

        self.assertIn(f'{file.name}: invalid YAML:', str(context.exception))

    def test_load_yml_rejects_duplicate_keys_with_filename_and_line(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml') as file:
            file.write(
                'device: Demo Device\n'
                'bindings:\n'
                '  KEY_A:\n'
                '    up: first-command\n'
                '    up: second-command\n'
            )
            file.flush()
            filename = file.name

            with self.assertRaises(profiles.ProfileValidationError) as context:
                profiles.load_yml(filename)

        message = str(context.exception)
        self.assertIn(f'{filename}: invalid YAML:', message)
        self.assertIn("found duplicate key 'up'", message)
        self.assertIn('line 5', message)

    def test_profile_config_is_deeply_immutable(self):
        profile_config = profiles.validate_profile_data(self._profile_data())

        self.assertIsInstance(profile_config.keyboard.bindings, FrozenDict)
        self.assertIsInstance(profile_config.keyboard.layers, FrozenDict)
        self.assertIsInstance(profile_config.keyboard.bindings['KEY_A'].actions, FrozenDict)

        with self.assertRaises(TypeError):
            profile_config.keyboard.bindings['KEY_B'] = profile_config.keyboard.bindings['KEY_A']
        with self.assertRaises(TypeError):
            profile_config.keyboard.bindings['KEY_A'].actions['up'] = ('changed-command',)

    def test_profile_config_remains_picklable(self):
        profile_config = profiles.validate_profile_data(
            self._profile_data(timing={'multi_tap_ms': 350})
        )

        restored_config = pickle.loads(pickle.dumps(profile_config))

        self.assertEqual(profile_config, restored_config)
        self.assertEqual(profile_config.timing_fields, restored_config.timing_fields)

    def test_layer_reference_metadata_remains_picklable(self):
        profile_config = profiles.validate_profile_data(
            self._profile_data(
                bindings={'KEY_A': {'up': '^layer navigation'}},
                layers={
                    'navigation': {
                        'bindings': {
                            'KEY_H': 'move-left',
                        },
                    },
                },
            )
        )

        restored_config = pickle.loads(pickle.dumps(profile_config))

        self.assertEqual(profile_config.layer_references, restored_config.layer_references)

    def test_merge_combines_typed_profile_fragments(self):
        first = profiles.validate_profile_data(
            self._profile_data(bindings={'KEY_A': 'a-command'}),
            source='first.yml',
        )
        second = profiles.validate_profile_data(
            self._profile_data(bindings={'KEY_B': 'b-command'}),
            source='second.yml',
        )

        merged = profiles.merge_data([first, second])

        self.assertEqual(
            {
                'KEY_A': {'up': ['a-command']},
                'KEY_B': {'up': ['b-command']},
            },
            merged.keyboard.to_data()['bindings'],
        )

    def test_merge_combines_timing_fields_from_profile_fragments(self):
        first = profiles.validate_profile_data(
            self._profile_data(
                bindings={'KEY_A': 'a-command'},
                timing={'multi_tap_ms': 350},
            ),
            source='first.yml',
        )
        second = profiles.validate_profile_data(
            self._profile_data(
                bindings={'KEY_B': 'b-command'},
                timing={'one_shot_timeout_ms': 7000},
            ),
            source='second.yml',
        )

        merged = profiles.merge_data([first, second])

        self.assertEqual(350, merged.keyboard.timing.multi_tap_ms)
        self.assertEqual(7000, merged.keyboard.timing.one_shot_timeout_ms)

    def test_merge_reports_timing_conflict_from_later_fragment(self):
        first = profiles.validate_profile_data(
            self._profile_data(
                bindings={'KEY_A': 'a-command'},
                timing={'multi_tap_ms': 250},
            ),
            source='first.yml',
        )
        second = profiles.validate_profile_data(
            self._profile_data(
                bindings={'KEY_B': 'b-command'},
                timing={'multi_tap_ms': 300},
            ),
            source='second.yml',
        )

        with self.assertRaises(profiles.ProfileValidationError) as context:
            profiles.merge_data([first, second])

        self.assertEqual(
            'second.yml: timing.multi_tap_ms: conflicts with an earlier profile fragment',
            str(context.exception),
        )

    def test_merge_allows_repeated_identical_timing_values(self):
        first = profiles.validate_profile_data(
            self._profile_data(
                bindings={'KEY_A': 'a-command'},
                timing={'multi_tap_ms': 350},
            ),
            source='first.yml',
        )
        second = profiles.validate_profile_data(
            self._profile_data(
                bindings={'KEY_B': 'b-command'},
                timing={'multi_tap_ms': 350},
            ),
            source='second.yml',
        )

        merged = profiles.merge_data([first, second])

        self.assertEqual(350, merged.keyboard.timing.multi_tap_ms)

    def test_merge_conflict_reports_later_source_and_path(self):
        first = profiles.validate_profile_data(
            self._profile_data(bindings={'KEY_A': 'first-command'}),
            source='first.yml',
        )
        second = profiles.validate_profile_data(
            self._profile_data(bindings={'KEY_A': 'second-command'}),
            source='second.yml',
        )

        with self.assertRaises(profiles.ProfileValidationError) as context:
            profiles.merge_data([first, second])

        self.assertEqual(
            'second.yml: bindings.KEY_A.up: conflicts with an earlier profile fragment',
            str(context.exception),
        )

    def test_merge_reports_layer_fallback_conflict_from_later_fragment(self):
        first = profiles.validate_profile_data(
            self._profile_data(
                bindings={'KEY_A': 'a-command'},
                layers={'mod': {'fallback': 'none'}},
            ),
            source='first.yml',
        )
        second = profiles.validate_profile_data(
            self._profile_data(
                bindings={'KEY_B': 'b-command'},
                layers={'mod': {'fallback': 'base'}},
            ),
            source='second.yml',
        )

        with self.assertRaises(profiles.ProfileValidationError) as context:
            profiles.merge_data([first, second])

        self.assertEqual(
            'second.yml: layers.mod.fallback: conflicts with an earlier profile fragment',
            str(context.exception),
        )

    def test_merge_allows_layer_reference_defined_by_another_fragment(self):
        binding_fragment = profiles.validate_profile_data(
            self._profile_data(bindings={'KEY_A': {'up': '^layer navigation'}}),
            source='bindings.yml',
        )
        layer_fragment = profiles.validate_profile_data(
            self._profile_data(
                bindings={},
                layers={
                    'navigation': {
                        'bindings': {
                            'KEY_H': 'move-left',
                        },
                    },
                },
            ),
            source='layers.yml',
        )

        merged = profiles.merge_data([binding_fragment, layer_fragment])

        self.assertIn('navigation', merged.keyboard.layers)

    def test_merge_rejects_reference_to_unknown_layer(self):
        profile_config = profiles.validate_profile_data(
            self._profile_data(bindings={'KEY_A': {'up': '^layer missing'}}),
            source='broken.yml',
        )

        with self.assertRaises(profiles.ProfileValidationError) as context:
            profiles.merge_data([profile_config])

        self.assertEqual(
            "broken.yml: bindings.KEY_A.up: references unknown layer 'missing'",
            str(context.exception),
        )

    def test_merge_reports_original_path_for_unknown_inline_layer_reference(self):
        profile_config = profiles.validate_profile_data(
            self._profile_data(
                bindings={
                    'KEY_A': {
                        'up': 'base-command',
                        'layers': {
                            'navigation': {
                                'up': '^layer missing',
                            },
                        },
                    },
                }
            ),
            source='inline.yml',
        )

        with self.assertRaises(profiles.ProfileValidationError) as context:
            profiles.merge_data([profile_config])

        self.assertEqual(
            "inline.yml: bindings.KEY_A.layers.navigation.up: references unknown layer 'missing'",
            str(context.exception),
        )

    def test_inline_layer_shorthand_reference_is_validated_after_merge(self):
        profile_config = profiles.validate_profile_data(
            self._profile_data(
                bindings={
                    'KEY_A': {
                        'up': 'base-command',
                        'layers': {'mod': '^layer navigation'},
                    },
                },
                layers={
                    'navigation': {'fallback': 'none'},
                },
            ),
            source='inline.yml',
        )

        merged = profiles.merge_data([profile_config])

        self.assertIn('navigation', merged.keyboard.layers)

    def test_merge_rejects_profile_without_reachable_base_action(self):
        profile_config = profiles.validate_profile_data(
            self._profile_data(bindings={}),
            source='empty.yml',
        )

        with self.assertRaises(profiles.ProfileValidationError) as context:
            profiles.merge_data([profile_config])

        self.assertEqual(
            "device 'Demo Device': bindings: expected at least one reachable base action",
            str(context.exception),
        )


if __name__ == '__main__':
    unittest.main()
