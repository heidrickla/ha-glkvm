# Changelog

Everything a user of this integration would notice, newest first. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the version
numbers are the ones in `manifest.json`. Changes that only move code around,
or that touch tests and CI, are not listed unless they change what the
integration does.

## [Unreleased] - 2026-09-04

### Added

- **KVMs on your network are discovered.** A unit announcing itself over mDNS
  (`_glinet._tcp.local.`) appears under Devices & Services as a discovered
  device and asks only for its login; the address and port come from the
  announcement. Discovery is filtered on the model, so nothing else on the
  network is offered as a KVM.
- **A KVM that changes address is followed rather than duplicated.** The
  unit's MAC address is stored with the entry, read from the unit at setup and
  whenever the entry is created or reconfigured, and an announcement that
  matches it moves the entry to the new address and reloads it. A unit added
  by hand before this release gets its MAC stored the next time its entry
  loads.
- **Re-authentication checks that it is still your KVM.** Entering new
  credentials for an address that now answers as a different unit is refused
  with "That address answers as a different KVM", instead of handing this
  entry's device, entities and history to the other unit.

### Changed

- **A failed endpoint makes its own entities unavailable.** The integration
  reads seven sections of the unit's state from seven endpoints. One of them
  failing used to leave that section's entities showing the value from the
  last poll that worked; they now report unavailable, and the other six
  sections stay live. Only the unit being unreachable for all seven marks
  everything unavailable, as before.
- **The stream client count sensor is disabled by default**, which is what the
  documentation had always said. It counts viewers of GL.iNet's own web
  interface. Enable it from the entity's settings if you want it back.
- **Changing the virtual media image while it is attached, and attaching with
  no image selected, are refused as input errors** rather than reported as
  failures of the unit. The refusal text is unchanged; what changes is that
  automations see a validation error.
- **Minimum Home Assistant is 2026.3.** That is the release which serves a
  custom integration's brand images from its own folder, which is where this
  integration's icons live.
- **The brand images are transparent and fill their canvas**, as
  home-assistant/brands asks.

### Fixed

- **The health sensors appear on the first poll that carries them.** A health
  read that failed at startup looked the same as firmware without a health
  section, so CPU temperature, CPU usage, memory and the network rates stayed
  missing until the entry was reloaded.
- **Wake buttons for targets deleted while Home Assistant was not running are
  removed.** The cleanup compared the unit's targets against what the running
  platform had added, so a target deleted while the entry was unloaded kept
  its button for good.
- **The password is never sent back to the browser.** After a failed setup
  attempt the form used to carry the typed password back as the field's
  default, which also meant that clearing the field on a retry silently
  resubmitted the old password.
- **Re-adding a unit that is already configured refreshes its port and
  credentials, not only its address.** A unit that moved may also have been
  given a new port or a rotated password.
- **Setup and polling failures are translated.** "Could not reach the KVM" and
  "The KVM rejected the credentials" appeared on the integration card in
  English whatever language Home Assistant was running in.
- **The console-login example in the README is loadable.** It used `!input`
  inside a plain script, a tag that only resolves inside a blueprint, and is
  written as a script blueprint now.

## [0.1.0] - 2026-09-04

First release. Host power and the three front-panel buttons through the ATX
board, the screen as a still-image camera, the virtual USB drive with its
image list, the keyboard and mouse gadget with the jiggler and the mouse
mode, Wake-on-LAN buttons for the unit's stored targets, user-GPIO channels,
the unit's own health, and four actions: type text, send keys, wake, and the
full set of ATX power actions. Built and verified against a GL-RM10 (Comet
Pro) on firmware 1.10.0.
