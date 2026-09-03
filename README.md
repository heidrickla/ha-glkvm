# GL.iNet KVM for Home Assistant

Local (no cloud) Home Assistant integration for **GL.iNet Comet KVM-over-IP
units**: the host's power, its screen, the virtual USB drive, the keyboard
and mouse gadget, Wake-on-LAN, and the KVM's own health, all as entities on
one device. Built and verified against a **GL-RM10 (Comet Pro)** on firmware
1.10.0; everything talks to the unit over your LAN through the same API its
own web interface uses.

## What you get

| Entity | Type | What it is |
|---|---|---|
| Host power | switch | On when the ATX board reads the host as powered. On presses the power button; off presses it once, which asks the OS to shut down. |
| Power button, Hold power button, Reset | button | The three front-panel buttons through the ATX board. |
| Screen | camera | The current capture frame as a still image. |
| Video signal | binary sensor | Whether the host is putting out video on HDMI. |
| Capture resolution, Capture frame rate | sensor | What the unit is capturing right now. |
| Virtual media attached | switch | Whether the selected image is plugged into the host as a USB drive. |
| Virtual media image | select | Which stored image the drive presents. |
| Media storage free | sensor | Space left on the unit's media partition. |
| Keyboard connected, Mouse connected | binary sensor | Whether the host is talking to each half of the USB gadget. |
| Mouse jiggler | switch | kvmd's jiggler, which keeps the host awake. On means it is running; unavailable when the unit's configuration disables it. |
| Mouse mode | select | Absolute, relative, hybrid or touch. |
| Reset keyboard and mouse | button | Re-plugs the USB gadget. |
| Wake *name* | button | One per Wake-on-LAN target stored on the unit. |
| CPU temperature, CPU usage, Memory usage | sensor | The KVM's own health (firmware 1.10.0 and later). |
| *channel* | switch, button or binary sensor | One per user-GPIO channel configured on the unit: relays, smart plugs, KVM switch ports. |

Memory available, both network rates, the H.264 bitrate and the stream client
count are there too, disabled by default.

### Actions

All actions take the KVM to talk to (`config_entry_id`), because you may have
more than one.

| Action | Does |
|---|---|
| `glkvm.type_text` | Types text into the host over the USB keyboard. `slow: true` for hosts that drop fast input. |
| `glkvm.send_keys` | Presses a combination together and releases it, e.g. `["ControlLeft", "AltLeft", "Delete"]`. Key names are the ones kvmd uses: `KeyA`, `Digit1`, `Enter`, `Escape`, `MetaLeft`, `F5`. |
| `glkvm.wake` | Sends a Wake-on-LAN packet from the KVM to a MAC address on its network. |
| `glkvm.power` | The full set of ATX actions: `on`, `off` (ACPI), `off_hard`, `reset_hard`, with `wait`. |

## Supported devices

| Device | Firmware | Status |
|---|---|---|
| GL-RM10 Comet Pro | 1.10.0 | Verified: every entity and action was built against recorded answers from this unit. |
| GL-RM10 Comet Pro | 1.8.1 | Expected to work without the health sensors (that firmware has no `health` section). Untested. |
| GL-RM1 Comet | any | Same kvmd fork and API. Untested. |

The unit's kvmd is GL.iNet's fork of PiKVM 4.82. Upstream PiKVM units are not
a target: the integration relies on GL.iNet's additions (`hdmi.signal`, the
ATX board's power reading, the firmware version and hostname endpoints, the
Wake-on-LAN list), and degrades where they are absent rather than guessing.

### Stock firmware or the glkvm-firmware image?

**No custom firmware is needed.** Every call this integration makes goes to
stock kvmd and GL.iNet endpoints over `https://<unit>`, and none of the
modules patched by the [glkvm-firmware](../glkvm-firmware) project is on any
path it uses (no Redfish, no OCR, no VNC, no port 8888, no Prometheus
export). The unit it was verified against runs that project's provisioned
1.10.0 image, and only two of its settings change what you see here — both
are lines in `/etc/kvmd/override.yaml`, not the image:

| Setting | On stock firmware | With the setting |
|---|---|---|
| `kvmd.streamer.forever: true` | the Screen camera has a picture only while GL.iNet's web UI is open, otherwise "no image" | a picture at every refresh |
| `otg.devices.msd.start_cdrom` / `start_flash: true` | virtual media reports offline on 1.10.0 | virtual media online at boot; GL.iNet's own USB-functions toggle in their web UI sets the same thing without a shell |

Everything else — power state and buttons on the ATX board, keyboard and
mouse, Wake-on-LAN, HDMI signal, host information — behaves identically on
stock. A stock unit needs its login entered; a unit with authentication
disabled accepts anything.

## Requirements

- Home Assistant 2025.4 or newer.
- A GL.iNet KVM reachable from Home Assistant on your LAN, by IP address.
- Its login, unless you have disabled authentication on the unit.

## Installation

HACS (custom repository): add this repository as a custom repository of type
Integration, install, restart Home Assistant.

Manual: copy `custom_components/glkvm/` into your Home Assistant
`config/custom_components/` directory and restart.

Then Settings -> Devices & Services -> Add Integration -> GL.iNet KVM.

### Installation parameters

| Field | Meaning |
|---|---|
| Host | The unit's LAN IP address. Prefer the IP to a `.local` name: with more than one unit, mDNS can answer for the wrong one. |
| Port | 443 unless you have moved the web interface. |
| Username, Password | The unit's login. Leave both empty if authentication is disabled on the unit. |
| Verify the KVM's certificate | Off by default. The unit ships a self-signed certificate for `localhost`; turn this on only if you have installed your own. |

Setup checks the credentials against the unit and reads its serial number
before the entry is created, so a wrong password or a wrong address is caught
on the form. The serial is the entry's unique id: a unit that moves to a new
address is recognised, not added twice.

### Reconfiguring

Settings -> Devices & Services -> GL.iNet KVM -> Reconfigure changes the
address, port, credentials or certificate check. The address must still answer
as the same unit. There are no options beyond these.

When the unit starts refusing the credentials, Home Assistant stops polling
and asks for them again. It stops rather than retrying because GL.iNet's
firmware locks the account after repeated failed logins.

### Removing it

Settings -> Devices & Services -> GL.iNet KVM -> Delete. That removes the entry,
its device and every entity. Nothing is written to the unit.

## How it updates

Every 30 seconds the integration reads the unit's ATX, virtual media, streamer,
HID, GPIO, health and Wake-on-LAN state, each from its own endpoint. A single
endpoint failing keeps that section's last value and leaves the rest live;
only the unit being unreachable marks everything unavailable. The camera
fetches a frame when something asks for one.

Thirty seconds is deliberate. Host power, video signal and attached media
change at human speed, and the unit's CPU belongs to its video encoder. The
same state is available as a push stream over `/api/ws`; polling is the first
implementation, not the last.

## Examples

Power a server on for a backup window and off afterwards:

```yaml
automation:
  - alias: Backup server on at 02:00
    triggers:
      - trigger: time
        at: "02:00:00"
    actions:
      - action: switch.turn_on
        target:
          entity_id: switch.rack_kvm_host_power
  - alias: Backup server off when the backup finishes
    triggers:
      - trigger: state
        entity_id: binary_sensor.backup_running
        to: "off"
    actions:
      - action: switch.turn_off
        target:
          entity_id: switch.rack_kvm_host_power
```

Notify when the host stops putting out video:

```yaml
automation:
  - alias: Rack host lost video
    triggers:
      - trigger: state
        entity_id: binary_sensor.rack_kvm_video_signal
        to: "off"
        for: "00:02:00"
    actions:
      - action: notify.mobile_app_phone
        data:
          message: The rack host has had no video for two minutes.
```

Boot a rescue image: select it, attach it, reset the host:

```yaml
script:
  boot_rescue:
    sequence:
      - action: select.select_option
        target:
          entity_id: select.rack_kvm_virtual_media_image
        data:
          option: rescue.iso
      - action: switch.turn_on
        target:
          entity_id: switch.rack_kvm_virtual_media_attached
      - action: button.press
        target:
          entity_id: button.rack_kvm_reset
```

Log in to a console that has no network yet:

```yaml
script:
  console_login:
    sequence:
      - action: glkvm.type_text
        data:
          config_entry_id: !input kvm
          text: "root\n"
      - delay: "00:00:02"
      - action: glkvm.send_keys
        data:
          config_entry_id: !input kvm
          keys: ["ControlLeft", "KeyL"]
```

## Known limitations

- **The Screen camera is a still-image camera.** kvmd serves the current frame
  as a JPEG; GL.iNet's live path is WebRTC and its raw H.264 stream is not
  something the camera platform can play. Cards refresh the still every two
  seconds.
- **On stock firmware the camera has a picture only while GL.iNet's own web UI
  is watching.** Their firmware starts kvmd's streamer on demand. Setting
  `kvmd: {streamer: {forever: true}}` in `/etc/kvmd/override.yaml` on the unit
  keeps it running; a repair issue says so when the streamer has been stopped
  for three polls.
- **Virtual media is offline on a stock 1.10.0 unit.** That firmware ships the
  mass-storage functions unlinked from the USB gadget. Enabling USB functions
  in GL.iNet's own web UI fixes it without a shell (it writes the same keys to
  the unit's `boot.yaml`); so does setting
  `otg: {devices: {msd: {start_cdrom: true, start_flash: true}}}` in
  `override.yaml` and rebooting. A repair issue says so. Images smaller than
  614,400 bytes are rejected by the unit's kernel.
- **Power control needs GL.iNet's ATX board.** Without it the power switch and
  the three buttons are unavailable, and the `power` action refuses.
- **Keyboard connected and Mouse connected are lazy.** kvmd updates them on
  the next successful write, so a host that has stopped polling the gadget
  still reads connected until something is typed.
- **Authentication is per request.** The unit accepts the credentials as
  headers on every call; if it has authentication disabled, whatever you enter
  works, which is the correct answer.
- Nothing is discovered automatically yet. The unit does advertise over mDNS,
  but its service has not been measured and is not guessed at.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Setup says "Could not reach a KVM at that address" | Home Assistant cannot route to the unit, or the port is wrong. Try the unit's web UI from the Home Assistant host's network. |
| Setup says the credentials were rejected, and they are right | The unit has locked the account after failed logins. Wait it out, or log in through the unit's web UI. |
| Everything is unavailable | The unit is unreachable. The log has one line saying so and one when it recovers. |
| Camera and capture sensors unavailable, the rest fine | The streamer is not running on the unit. See known limitations. |
| Virtual media entities unavailable, the rest fine | The mass-storage gadget is offline. See known limitations. |
| Power entities unavailable, the rest fine | No ATX board is attached to the unit. |
| A Wake button vanished | The target was removed from the unit's Wake-on-LAN list. |
| Typed text arrives garbled or not at all | Try `slow: true`, and check Keyboard connected. `kvmd-otgconf --reset-gadget` on the unit re-plugs a gadget the host has stopped polling. |

```yaml
logger:
  logs:
    custom_components.glkvm: debug
```

Download diagnostics from the device page for a report with the host, serial,
credentials and every MAC and IP address redacted.

## Development

- `custom_components/glkvm/api.py` and `models.py` import nothing from Home
  Assistant. `tests/test_api.py` and `tests/test_models.py` load them by path
  and run on a bare interpreter against `tests/fixtures/`, which are the
  bodies a real GL-RM10 sent, with its serial, hostname and the household's
  MAC and IP addresses replaced.
- `tests/ha/` covers the Home Assistant layer with the client replaced by a
  fake that answers from the same fixtures. It runs in CI on Linux; it skips
  where the Home Assistant test harness is absent.
- `python tools/validate_local.py` is the offline half of the hassfest and
  HACS checks plus every cross-file consistency check.
- `python tools/make_brand.py` regenerates and size-checks the brand images.

```bash
python -m pytest tests/ -q
python -m ruff check . && python -m ruff format --check .
python -m mypy custom_components/glkvm
python tools/validate_local.py
```

The firmware work this was built on, including the provisioning that fixes the
two stock-firmware limitations above, lives in the `glkvm-firmware` repository.

## Quality scale

Built to Home Assistant's Integration Quality Scale, tracked rule by rule in
[`quality_scale.yaml`](custom_components/glkvm/quality_scale.yaml) with a
reason on every exemption. `tools/validate_local.py` checks the file against
the pinned rule list, so a rule that is simply missing fails rather than
reading as complete. The scale is a core-integration concept; a custom
integration builds to the rules and is not scored.

Publication status is in [PUBLISHING.md](PUBLISHING.md).

## Licence

MIT.
