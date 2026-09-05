"""The models, against bodies recorded from a GL-RM10 on firmware 1.10.0.

These run on a bare interpreter; nothing here needs Home Assistant.
"""

from tests.pure import load, result

models = load("models")


def test_system_info_reads_the_identity():
    info = models.SystemInfo.from_info(result("info.json"))
    assert info.serial == "0123456789ABCDEF"
    assert info.kvmd_version == "4.82"
    assert info.kernel_release == "6.1.141"
    assert info.platform_base == "Rockchip RV1126B-P EVB V14 Board"
    # kvmd's own meta does not know the name the user gave the unit.
    assert info.hostname == "localhost.localdomain"
    assert info.streamer_app == "ustreamer"


def test_firmware_info():
    fw = models.FirmwareInfo.from_result(result("upgrade_version.json"))
    assert fw.model == "RM10"
    assert fw.version == "V1.10.0 beta2"


def test_health_is_read_from_the_info_section():
    health = models.Health.from_info(result("info.json"))
    assert health is not None
    assert health.cpu_temp == 47.03
    assert health.cpu_percent == 14.0
    assert health.mem_percent == 37.8
    assert health.mem_available == 643792896
    assert health.rx_rate == 912


def test_health_is_none_where_the_firmware_has_no_health_section():
    # Firmware 1.8.1 registers no health submanager; the section is absent.
    assert models.Health.from_info(result("info_1_8_1.json")) is None


def test_atx_with_a_board_reads_the_boards_power_state():
    atx = models.AtxState.from_result(result("atx.json"))
    assert atx.enabled is True
    assert atx.power == "on"
    assert atx.power_on is True


def test_atx_without_a_board_is_disabled():
    atx = models.AtxState.from_result(result("atx_no_board.json"))
    assert atx.enabled is False
    assert atx.power_on is False


def test_atx_unknown_power_string_is_unknown_not_off():
    atx = models.AtxState.from_result({"enabled": True, "power": "weird"})
    assert atx.power_on is None


def test_msd_hides_the_windows_directory_and_reads_storage():
    msd = models.MsdState.from_result(result("msd.json"))
    assert msd.enabled and msd.online
    assert msd.connected is False
    assert msd.image is None
    # The only listed file lives under System Volume Information.
    assert msd.images == ()
    assert msd.storage_free == 28797337600
    assert msd.storage_size == 28797599744


def test_msd_with_an_image_selected():
    msd = models.MsdState.from_result(result("msd_with_image.json"))
    assert msd.image == "ubuntu.iso"
    assert msd.cdrom is True
    names = [img.name for img in msd.images]
    assert names == ["rescue.iso", "ubuntu.iso", "upload-in-progress.iso"]
    complete = {img.name: img.complete for img in msd.images}
    assert complete["upload-in-progress.iso"] is False
    assert complete["ubuntu.iso"] is True


def test_msd_offline_as_stock_1_10_0_boots():
    msd = models.MsdState.from_result(result("msd_offline.json"))
    assert msd.enabled is True
    assert msd.online is False


def test_msd_tolerates_a_disabled_module():
    # kvmd sends drive: null and storage: null while the module is disabled.
    msd = models.MsdState.from_result(
        {"enabled": False, "online": False, "drive": None}
    )
    assert msd.connected is None
    assert msd.images == ()


def test_streamer_running():
    streamer = models.StreamerState.from_result(result("streamer.json"))
    assert streamer.running is True
    assert streamer.signal is True
    assert streamer.resolution == "2560x1440"
    assert streamer.captured_fps == 60
    assert streamer.clients == 0
    assert streamer.h264_bitrate_bps == 20000000
    assert streamer.encoder == "RV1126-H264"
    assert streamer.quality == 70


def test_streamer_stopped_is_the_stock_resting_state():
    streamer = models.StreamerState.from_result(result("streamer_stopped.json"))
    assert streamer.running is False
    assert streamer.signal is None
    assert streamer.resolution is None
    # The params block is still there while the streamer is not.
    assert streamer.quality == 70


def test_hid():
    hid = models.HidState.from_result(result("hid.json"))
    assert hid.enabled and hid.online
    assert hid.keyboard_online is True
    assert hid.mouse_online is True
    assert hid.num_lock is True
    assert hid.caps_lock is False
    assert hid.jiggler_enabled is True
    assert hid.jiggler_active is False
    assert hid.mouse_output == "usb"
    assert hid.mouse_outputs == ("usb", "usb_rel", "usb_hybrid", "usb_touch")


def test_gpio_reads_the_scheme_and_the_state_together():
    gpio = models.GpioState.from_result(result("gpio.json"))
    assert gpio.inputs == ()
    (demo,) = gpio.outputs
    assert demo.channel == "demo_button"
    assert demo.switch is False
    assert demo.pulse_delay == 0.1
    assert demo.online is True
    assert demo.state is False


def test_gpio_distinguishes_inputs_switches_and_pulses():
    gpio = models.GpioState.from_result(result("gpio_rich.json"))
    (door,) = gpio.inputs
    assert door.is_input and door.state is True
    by_name = {ch.channel: ch for ch in gpio.outputs}
    assert by_name["relay"].switch is True
    assert by_name["demo_button"].switch is False


def test_wol_targets_lowercase_the_mac():
    (target,) = models.WolTarget.list_from_result(result("wol_list.json"))
    assert target.mac == "02:00:00:00:00:01"
    assert target.name == "lab-server"
    assert target.ip == "192.0.2.10"


def test_wol_target_without_a_name_falls_back_to_the_mac():
    (target,) = models.WolTarget.list_from_result(
        {"devices": [{"mac": "AA:BB:CC:DD:EE:FF"}]}
    )
    assert target.name == "aa:bb:cc:dd:ee:ff"


def test_everything_tolerates_an_empty_body():
    # A firmware that renames or drops keys must degrade, not raise.
    assert models.SystemInfo.from_info({}).serial is None
    assert models.Health.from_info({}) is None
    assert models.AtxState.from_result({}).enabled is False
    assert models.MsdState.from_result({}).online is False
    assert models.StreamerState.from_result({}).running is False
    assert models.HidState.from_result({}).enabled is False
    assert models.GpioState.from_result({}).outputs == ()
    assert models.WolTarget.list_from_result({}) == ()


def test_dig_stops_at_the_first_non_mapping():
    assert models._dig({"a": {"b": 1}}, "a", "b") == 1
    assert models._dig({"a": 1}, "a", "b") is None
    assert models._dig(None, "a") is None


def test_numeric_helpers_reject_booleans():
    # True is an int in Python; a flag must never read as the number 1.
    assert models._as_int(True) is None
    assert models._as_float(False) is None
    assert models._as_int(3.0) == 3
    assert models._as_int(3.5) is None


def test_network_config_reads_the_units_own_mac():
    net = models.NetworkConfig.from_result(result("network_config.json"))
    assert net.mac == "94:83:c4:00:02:15"
    assert net.ip == "192.0.2.15"
    assert net.interface == "eth0"
    assert net.is_dhcp is True


def test_network_config_tolerates_a_body_without_a_config():
    net = models.NetworkConfig.from_result({})
    assert net.mac is None and net.ip is None and net.is_dhcp is None


def test_keys_that_are_not_names_are_skipped():
    # A firmware that puts a number or an empty key where a name belongs must
    # lose that one entry, not the whole section.
    msd = models.MsdState.from_result(
        {"storage": {"images": {"": {"size": 1}, "real.iso": {"size": 2}}}}
    )
    assert [image.name for image in msd.images] == ["real.iso"]

    gpio = models.GpioState.from_result(
        {"model": {"scheme": {"outputs": {"": {"switch": True}, "relay": {}}}}}
    )
    assert [channel.channel for channel in gpio.outputs] == ["relay"]

    wol = models.WolTarget.list_from_result(
        {"devices": [{"name": "no mac"}, {"mac": "02:00:00:00:00:09"}]}
    )
    assert [target.mac for target in wol] == ["02:00:00:00:00:09"]
