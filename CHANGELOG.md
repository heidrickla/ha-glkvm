# Changelog

Everything a user of this integration would notice, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the version numbers are the ones in `manifest.json`. Changes that only move code around, or that touch tests and CI, are not listed unless they change what the integration does.

## [0.3.0] - 2026-10-30

### Changed

- Setting a unit up by hand asks for its IP address and password. The port, the username and the certificate check sit in a collapsed Advanced section with their defaults: 443, `admin` (the one login stock firmware has) and off.
- Adding a discovered unit asks only for its password; the username and the certificate check sit in Advanced.
- Reconfigure and reauthentication fill an empty username with `admin` too. A unit with authentication disabled accepts any login, so this changes nothing there.
- When the unit cannot be reached or refuses the login, the form opens Advanced and keeps everything typed except the password.
- The setup screen submits with Advanced left collapsed: the section opens holding its defaults, where before the frontend sent it empty and refused Submit with "Not all required fields are filled in."
- The README opens the repository in HACS and starts the setup with My Home Assistant buttons, and no longer asks for a custom repository: GL.iNet KVM is in the HACS default list.

## [0.2.3] - 2026-10-23

### Fixed

- The host power switch, the Power button, Hold power button and Reset, and the `power` action work on firmware 1.10.0 and 1.10.1. Each failed with "The KVM did not carry out the command: Error: HTTP 500", because GL.iNet's ATX plugin answers every request that asks the unit to wait with HTTP 500. ATX commands now go the way the unit's web interface sends them, and waiting (the default, and the `power` action's `wait`) follows the unit's ATX busy flag until the press is over, for up to 40 seconds. ([#2](https://github.com/heidrickla/ha-glkvm/issues/2))

## [0.2.2] - 2026-10-22

### Changed

- The four actions (`type_text`, `send_keys`, `wake`, `power`) are administrator actions. A non-administrator's call is refused with Home Assistant's own unauthorized error; automations and scripts are unaffected.
- The switches, buttons and selects answer administrators only: host power, the ATX and keyboard-reset buttons, virtual media and its image, the mouse jiggler and mouse mode, GPIO outputs and Wake-on-LAN. A press from a non-administrator is refused; automations and scripts are unaffected.
- Each poll checks the credentials once before its concurrent reads. After the unit's password changes, a poll costs one failed login towards GL.iNet's lockout, then polling stops and Home Assistant asks for the new password.
- A KVM announced at a new address is followed only once that address proves it is the same unit. Each setup stores the SHA-256 of the certificate the unit presents; the entry's credentials go to the new address only over a connection presenting that certificate, and the serial it reports must match. The digest is redacted from diagnostics.

## [0.2.1] - 2026-09-15

### Fixed

- Wake-on-LAN target names are redacted from downloadable diagnostics. The name is the label the unit stores for a machine on your LAN, in practice that machine's hostname. Stored image filenames use the same key and stay in clear, so the report still shows what the virtual drive is presenting.
- User-GPIO channel names are redacted from downloadable diagnostics. The channel name is the one you gave it in the unit's GPIO scheme, so it names hardware in your house. Each channel's direction, switch, pulse delay and state stay in clear.

## [0.2.0] - 2026-09-05

### Added

- KVMs on your network are discovered. A unit announcing itself over mDNS (`_glinet._tcp.local.`) appears under Devices & Services as a discovered device and asks only for its login; the address and port come from the announcement. Discovery is filtered on the model, so nothing else on the network is offered as a KVM.
- A KVM that changes address is followed rather than duplicated. The unit's MAC address is stored with the entry, read from the unit at setup and whenever the entry is created or reconfigured, and an announcement that matches it moves the entry to the new address and reloads it. A unit added by hand before this release gets its MAC stored the next time its entry loads.
- Re-authentication checks that it is still your KVM. Entering new credentials for an address that now answers as a different unit is refused with "That address answers as a different KVM", instead of handing this entry's device, entities and history to the other unit.

### Changed

- A failed endpoint makes its own entities unavailable. The integration reads seven sections of the unit's state from seven endpoints. One of them failing used to leave that section's entities showing the value from the last poll that worked; they now report unavailable, and the other six sections stay live. Only the unit being unreachable for all seven marks everything unavailable, as before.
- The stream client count sensor is disabled by default, which is what the documentation had always said. It counts viewers of GL.iNet's own web interface. Enable it from the entity's settings if you want it back.
- Changing the virtual media image while it is attached, and attaching with no image selected, are refused as input errors rather than reported as failures of the unit. The refusal text is unchanged; what changes is that automations see a validation error.
- Minimum Home Assistant is 2026.3. That is the release which serves a custom integration's brand images from its own folder, which is where this integration's icons live.
- The brand images are transparent and fill their canvas, as home-assistant/brands asks.

### Fixed

- The health sensors appear on the first poll that carries them. A health read that failed at startup looked the same as firmware without a health section, so CPU temperature, CPU usage, memory and the network rates stayed missing until the entry was reloaded.
- Wake buttons for targets deleted while Home Assistant was not running are removed. The cleanup compared the unit's targets against what the running platform had added, so a target deleted while the entry was unloaded kept its button for good.
- The password is never sent back to the browser. After a failed setup attempt the form used to carry the typed password back as the field's default, which also meant that clearing the field on a retry silently resubmitted the old password.
- Re-adding a unit that is already configured refreshes its port and credentials, not only its address. A unit that moved may also have been given a new port or a rotated password.
- Setup and polling failures are translated. "Could not reach the KVM" and "The KVM rejected the credentials" appeared on the integration card in English whatever language Home Assistant was running in.
- The console-login example in the README is loadable. It used `!input` inside a plain script, a tag that only resolves inside a blueprint, and is written as a script blueprint now.

## [0.1.0] - 2026-09-04

First release. Host power and the three front-panel buttons through the ATX board, the screen as a still-image camera, the virtual USB drive with its image list, the keyboard and mouse gadget with the jiggler and the mouse mode, Wake-on-LAN buttons for the unit's stored targets, user-GPIO channels, the unit's own health, and four actions: type text, send keys, wake, and the full set of ATX power actions. Built and verified against a GL-RM10 (Comet Pro) on firmware 1.10.0.
