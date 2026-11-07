"""Exercise the real capture guard without Windows or image/OCR packages."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class ScreenCaptureTests(unittest.TestCase):
    def setUp(self):
        numpy = types.ModuleType('numpy')
        numpy.array = lambda image: image
        regions = types.ModuleType('Screen_Regions')
        regions.Quad = object
        logger = types.ModuleType('EDlogger')
        logger.logger = Mock()
        modules = {name: types.ModuleType(name) for name in ('cv2', 'win32con', 'win32gui', 'mss')}
        modules.update({'numpy': numpy, 'Screen_Regions': regions, 'EDlogger': logger})
        spec = importlib.util.spec_from_file_location('_screen_capture_test', Path(__file__).resolve().parents[1] / 'Screen.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(module)
        self.screen = module.Screen.__new__(module.Screen)
        self.screen.mon = {'top': 100, 'left': -1920}
        self.screen.monitor_number = 2
        self.screen.mss = Mock()
        self.screen._warn_capture_failure = Mock()

    def test_zero_reversed_and_subpixel_regions_never_reach_mss(self):
        for rect in [(0, 0, 0, 0), (50, 0, 40, 100), (0, 100, 50, 90), (0, 0, .5, .5)]:
            self.assertIsNone(self.screen.get_screen(*rect))
        self.screen.mss.grab.assert_not_called()
        self.assertIn('Screen calibration is missing or invalid', self.screen._warn_capture_failure.call_args.args[0])
        self.assertIn('Save All Calibrations', self.screen._warn_capture_failure.call_args.args[0])

    def test_valid_capture_keeps_monitor_offsets_and_pixel_dimensions(self):
        image = types.SimpleNamespace(size=4, shape=(330, 220, 4))
        self.screen.mss.grab.return_value = image
        self.assertIs(self.screen.get_screen(20, 30, 240, 360, rgb=False), image)
        self.screen.mss.grab.assert_called_once_with({'top': 130, 'left': -1900, 'width': 220, 'height': 330, 'mon': 2})

    def test_missing_monitor_is_reported_without_an_exception(self):
        self.screen.mon = None
        self.assertIsNone(self.screen.get_screen(0, 0, 100, 100))
        self.screen.mss.grab.assert_not_called()
        self.assertIn('No capture monitor', self.screen._warn_capture_failure.call_args.args[0])
