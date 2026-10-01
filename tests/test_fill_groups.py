"""Pure regression tests for separate fill and drag-merge ownership."""
import importlib.util
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / '_artifacts'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fill_groups',ROOT/'extension'/'fill_groups.py')
fg=importlib.util.module_from_spec(spec);spec.loader.exec_module(fg)


class FillGroupTests(unittest.TestCase):
    def test_separate_clicks_create_separate_fills(self):
        groups=fg.gesture_groups([], [1])
        groups=fg.gesture_groups(groups, [2])
        self.assertEqual(groups,[{1},{2}])

    def test_existing_fill_click_is_noop(self):
        self.assertEqual(fg.gesture_groups([{1,2},{3}], [1]),[{1,2},{3}])

    def test_drag_keeps_previous_joins_but_leaves_untouched_groups(self):
        self.assertEqual(fg.gesture_groups([{1,2},{3},{4,5}], [2,4]),[{1,2,4,5},{3}])

    def test_drag_adds_unfilled_hits_only_to_touched_group(self):
        self.assertEqual(fg.gesture_groups([{1,2},{3},{4}], [2,6]),[{1,2,6},{3},{4}])

    def test_one_unfilled_drag_creates_one_group(self):
        self.assertEqual(fg.gesture_groups([{5}], [1,2,3]),[{5},{1,2,3}])

    def test_erase_removes_only_touched_regions(self):
        self.assertEqual(fg.gesture_groups([{1,2},{3},{4,5}], [2,99],erase=True),[{1},{3},{4,5}])

    def test_erase_bridge_splits_fill_without_merging_untouched_owners(self):
        neighbors={1:{2},2:{1,3},3:{2,4},4:{3}}
        groups=[{1,2,3},{4}]
        self.assertEqual(fg.gesture_groups(groups,[2],erase=True,neighbors=neighbors),[{1},{3},{4}])
        self.assertEqual(groups,[{1,2,3},{4}])

    def test_remove_hover_is_atomic_even_after_merge(self):
        groups=[{1,2},{3}]
        self.assertEqual(fg.group_for_region(groups,2,erase=True),{2})
        self.assertEqual(fg.group_for_region(groups,4,erase=True),set())

    def test_initial_erase_never_populates_regions(self):
        self.assertEqual(fg.gesture_groups([], [1,2],erase=True),[])
        self.assertEqual(fg.gesture_groups([{3}], [1,2],erase=True),[{3}])

    def test_undo_snapshot_is_immutable_and_restores_grouping(self):
        groups=[{1},{2},{3}];snapshot=fg.snapshot_groups(groups)
        merged=fg.gesture_groups(snapshot,[1,2]);merged[0].add(99)
        self.assertEqual(fg.restore_groups(snapshot),[{1},{2},{3}])
        self.assertEqual(groups,[{1},{2},{3}])

    def test_each_preview_uses_gesture_start_and_cumulative_hits(self):
        start=fg.snapshot_groups([{1,2},{3},{4}])
        early=fg.gesture_groups(start,[2]);late=fg.gesture_groups(start,[2,3])
        self.assertEqual(early,[{1,2},{3},{4}])
        self.assertEqual(late,[{1,2,3},{4}])
        self.assertEqual(fg.restore_groups(start),[{1,2},{3},{4}])

    def test_hover_expands_only_owned_group(self):
        groups=[{1,2},{3}]
        self.assertEqual(fg.group_for_region(groups,2),{1,2})
        self.assertEqual(fg.group_for_region(groups,4),{4})
        self.assertEqual(fg.group_for_region(groups,-1),set())

    def test_empty_and_repeated_hits_do_not_mutate_inputs(self):
        groups=[{1},{2}]
        self.assertEqual(fg.gesture_groups(groups,[-1,1,1]),groups)
        copied=fg.gesture_groups(groups,[]);copied[0].add(9)
        self.assertEqual(groups,[{1},{2}])

    def test_overlapping_ownership_is_rejected(self):
        with self.assertRaises(ValueError):fg.gesture_groups([{1,2},{2,3}],[4])


if __name__=='__main__':unittest.main(argv=[__file__], verbosity=2)
