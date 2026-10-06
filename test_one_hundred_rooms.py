# -*- coding: utf-8 -*-
"""Tests for ONE_HUNDRED_ROOMS using fixed input sequences.

Covers the room state machine, battle settlement, inventory state and
abnormal-input recovery.
"""

import builtins
import contextlib
import io
import random
import types
import unittest

import ONE_HUNDRED_ROOMS as g

LEGAL_STATES = {
    'new_game', 'new_room', 'room_choice', 'door_check',
    'in_battle', 'treasure_check', 'game_over',
}


def scripted_inputs(values, eof_after=True):
    it = iter(values)

    def fake_input(prompt=''):
        try:
            return next(it)
        except StopIteration:
            if eof_after:
                raise EOFError
            return ''
    return fake_input


def silent_run(fn, inputs):
    builtins.input = scripted_inputs(inputs)
    g.sleep_speed = 0
    g.infinity = True
    g.eof_streak = 0
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink):
            fn()
    finally:
        builtins.input = input
    return sink.getvalue()


def reset_state():
    g.xp = 10
    g.hp = 30
    g.power = 50
    g.toughness = 50
    g.dodge = 10
    g.exits = [{'exit #': 1, 'danger %': 10},
               {'exit #': 2, 'danger %': 20}]
    g.fight_table = []
    g.room_enemies = []
    g.current_enemy = {}
    g.treasures = []
    g.treasure = 0
    g.inventory = []
    g.equipped = []
    g.potions_bag = []
    g.fighting_all = False
    g.player_choice = 1
    g.treasure_checked = False
    g.treasure_tooltip = True
    g.room_choice_tooltip = True
    g.room_danger = 5
    g.game_state = 'room_choice'
    g.infinity = True
    g.eof_streak = 0
    g.lore_no = -2
    g.lore_index = 0


class RoomStateMachineTests(unittest.TestCase):

    def setUp(self):
        reset_state()

    def test_invalid_door_numbers_rejected(self):
        for bad in ['0', '3', '-1', 'abc', '1.5', '']:
            g.game_state = 'room_choice'
            g.player_choice = bad
            silent_run(g.room_choice, [bad])
            self.assertEqual(g.game_state, 'room_choice', msg=bad)

    def test_valid_door_reaches_door_check(self):
        silent_run(g.room_choice, ['2'])
        self.assertEqual(g.game_state, 'door_check')
        self.assertEqual(g.player_choice, '2')

    def test_door_check_rejects_stale_invalid_choice(self):
        g.player_choice = '0'
        silent_run(g.door_check, [])
        self.assertEqual(g.game_state, 'room_choice')

    def test_empty_room_door_advances_to_new_room(self):
        g.room_no = 1
        g.player_choice = '1'
        g.game_state = 'door_check'
        silent_run(g.door_check, [])
        self.assertEqual(g.game_state, 'new_room')
        silent_run(g.new_room, [])
        self.assertEqual(g.room_no, 2)
        self.assertEqual(g.room_danger, 10)
        self.assertFalse(g.treasure_checked)
        self.assertEqual(g.game_state, 'room_choice')

    def test_new_room_survives_bad_player_choice_index(self):
        g.room_no = 1
        g.player_choice = '0'
        random.seed(0)
        silent_run(g.new_room, [])
        self.assertEqual(g.game_state, 'room_choice')
        self.assertGreaterEqual(g.room_no, 2)


class EnemyAndBattleTests(unittest.TestCase):

    def setUp(self):
        reset_state()

    def test_enemy_hp_and_toughness_rolled_independently(self):
        seen_different = False
        for seed in range(60):
            reset_state()
            g.room_no = 0
            random.seed(seed)
            silent_run(g.new_room, [])
            for row in g.fight_table:
                if row['hp'] != row['toughness']:
                    seen_different = True
        self.assertTrue(seen_different)

    def test_initiative_tie_is_rerolled(self):
        real_random = g.random
        roll_stream = iter([10, 10, 10, 5])
        g.random = types.SimpleNamespace(
            choice=lambda seq: next(roll_stream),
            shuffle=random.shuffle)
        try:
            g.xp = 5
            sink = io.StringIO()
            with contextlib.redirect_stdout(sink):
                g.initiative_rolls(5)
            self.assertEqual(g.attacker, 'player')
            self.assertIn('TIE', sink.getvalue())
        finally:
            g.random = real_random

    def test_battle_win_settles_and_returns_to_room(self):
        g.fight_table = [
            {'enemy': 'bush rat', 'xp': 2, 'power': 1,
             'toughness': 1, 'hp': 1}]
        g.game_state = 'in_battle'
        random.seed(2)
        xp_before = g.xp
        silent_run(g.in_battle, [])
        self.assertEqual(g.fight_table, [])
        self.assertGreater(g.xp, xp_before)
        self.assertEqual(g.game_state, 'room_choice')

    def test_battle_death_goes_to_game_over(self):
        g.fight_table = [
            {'enemy': 'saltwater crocodile', 'xp': 400, 'power': 100,
             'toughness': 100, 'hp': 200}]
        g.hp = 1
        g.toughness = 1
        g.game_state = 'in_battle'
        for seed in range(20):
            g.fight_table[0]['hp'] = 200
            g.hp = 1
            g.game_state = 'in_battle'
            g.current_enemy = {}
            random.seed(seed)
            silent_run(g.in_battle, [])
            if g.game_state == 'game_over':
                break
        self.assertEqual(g.game_state, 'game_over')

    def test_fight_all_clearing_room_searches_treasure(self):
        g.fight_table = [
            {'enemy': 'bush rat', 'xp': 1, 'power': 1,
             'toughness': 1, 'hp': 1}]
        g.fighting_all = True
        g.treasure = 0
        g.game_state = 'in_battle'
        random.seed(2)
        silent_run(g.in_battle, [])
        self.assertEqual(g.game_state, 'treasure_check')


class InventoryTests(unittest.TestCase):

    def setUp(self):
        reset_state()

    def test_potion_use_decreases_count_by_one(self):
        g.potions_bag = [
            {'name': 'test potion', 'power': 3, 'toughness': 0,
             'xp': 2, 'hp': 4}]
        power_before, xp_before, hp_before = g.power, g.xp, g.hp
        silent_run(g.inventory_use, ['p', 'test potion', 'nothing'])
        self.assertEqual(len(g.potions_bag), 0)
        self.assertEqual(g.power, power_before + 3)
        self.assertEqual(g.xp, xp_before + 2)
        self.assertEqual(g.hp, hp_before + 4)

    def test_bad_potion_name_changes_nothing(self):
        g.potions_bag = [
            {'name': 'test potion', 'power': 3, 'toughness': 0,
             'xp': 2, 'hp': 4}]
        power_before = g.power
        silent_run(g.inventory_use, ['p', 'bogus', 'nothing'])
        self.assertEqual(len(g.potions_bag), 1)
        self.assertEqual(g.power, power_before)

    def test_equip_and_unequip_restores_state(self):
        g.inventory = [{'name': 'baseball bat', 'power': 5, 'toughness': 0}]
        power_before = g.power
        silent_run(g.inventory_use,
                   ['a', 'baseball bat', 'r', 'baseball bat', 'nothing'])
        self.assertEqual(g.equipped, [])
        self.assertEqual(len(g.inventory), 1)
        self.assertEqual(g.power, power_before)

    def test_equip_bad_name_is_safe(self):
        g.inventory = [{'name': 'baseball bat', 'power': 5, 'toughness': 0}]
        silent_run(g.inventory_use, ['a', 'nope', 'nothing'])
        self.assertEqual(g.equipped, [])
        self.assertEqual(len(g.inventory), 1)

    def test_duplicate_same_named_potions_consume_one_per_use(self):
        item = {'name': 'twin potion', 'power': 1, 'toughness': 0,
                'xp': 0, 'hp': 1}
        g.potions_bag = [dict(item), dict(item)]
        silent_run(g.inventory_use, ['p', 'twin potion', 'nothing'])
        self.assertEqual(len(g.potions_bag), 1)


class TreasureTests(unittest.TestCase):

    def setUp(self):
        reset_state()

    def test_room_treasure_can_only_be_claimed_once(self):
        item_a = {'name': 'baseball bat', 'power': 5, 'toughness': 0}
        item_b = {'name': 'cricket bat', 'power': 10, 'toughness': 5}
        g.treasure = 2
        g.treasures = [item_a, item_b]
        g.treasure_checked = False
        g.game_state = 'treasure_check'

        real_random = g.random
        g.random = types.SimpleNamespace(
            choice=lambda seq: max(seq), shuffle=random.shuffle)
        try:
            silent_run(g.treasure_check, ['nothing'])
        finally:
            g.random = real_random

        self.assertTrue(g.treasure_checked)
        self.assertEqual(g.treasure, 0)
        self.assertEqual(g.treasures, [])
        claimed = len(g.inventory) + len(g.potions_bag)
        self.assertEqual(claimed, 2)

        silent_run(g.treasure_check, ['nothing'])
        claimed_again = len(g.inventory) + len(g.potions_bag)
        self.assertEqual(claimed_again, 2)
        self.assertEqual(g.game_state, 'room_choice')

    def test_empty_room_still_returns_to_room_choice(self):
        g.treasure = 0
        g.game_state = 'treasure_check'
        silent_run(g.treasure_check, [])
        self.assertEqual(g.game_state, 'room_choice')
        self.assertTrue(g.treasure_checked)


class AbnormalInputTests(unittest.TestCase):

    def setUp(self):
        reset_state()

    def test_garbage_inputs_never_leave_legal_room(self):
        for bad in ['0', '999', 'xyz', '!@#', '  ', '']:
            g.game_state = 'room_choice'
            silent_run(g.room_choice, [bad])
            self.assertIn(g.game_state, LEGAL_STATES)

    def test_eof_returns_to_legal_state_and_ends_safely(self):
        g.game_state = 'room_choice'
        silent_run(g.room_choice, [])
        self.assertEqual(g.game_state, 'room_choice')
        g.eof_streak = 0
        g.infinity = True
        builtins.input = scripted_inputs([])
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                for _ in range(6):
                    g.room_choice()
        finally:
            builtins.input = input
        self.assertFalse(g.infinity)


class IntegrationTests(unittest.TestCase):

    def test_fixed_sequence_main_loop_never_crashes(self):
        reset_state()
        g.test = True
        g.game_state = 'new_game'
        random.seed(3)
        sequence = ['s', '1', 'f', '2', '1', 'o', 'nothing'] * 8
        builtins.input = scripted_inputs(sequence)
        g.sleep_speed = 0
        g.infinity = True
        g.eof_streak = 0
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                g.main()
        finally:
            builtins.input = input
        self.assertFalse(g.infinity)
        self.assertIn(g.game_state, LEGAL_STATES | {'AI SENTIENT - SIMULATION COMPLETE.'})

    def test_restart_resets_room_state(self):
        g.treasure = 3
        g.treasures = [{'junk': True}]
        g.fight_table = [{'enemy': 'x'}]
        g.fighting_all = True
        g.room_no = 42
        g.game_overs = 1
        g.game_state = 'game_over'
        silent_run(g.new_game, [])
        self.assertEqual(g.room_no, 0)
        self.assertEqual(g.fight_table, [])
        self.assertEqual(g.treasures, [])
        self.assertEqual(g.treasure, 0)
        self.assertFalse(g.fighting_all)
        self.assertEqual(g.game_state, 'new_room')


if __name__ == '__main__':
    unittest.main(verbosity=2)
