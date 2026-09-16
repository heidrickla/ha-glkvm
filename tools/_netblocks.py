"""The address space tools/validate_local.py refuses.

Kept out of that file so the file can be scanned like every other published
file: these CIDRs are dotted quads the scan matches, so a file holding them
reports itself. This module is the one published file the scan skips, and the
scan asserts it holds nothing but the three names below.

Pinned rather than delegated to ipaddress.is_private, whose membership has
changed between Python releases and which does not cover 100.64.0.0/10.
"""

from __future__ import annotations

# Refused in the manifest URLs and in the published tree alike: every one of
# these names a machine on somebody's LAN and nothing on the internet.
TREE_CIDRS = (
    "10.0.0.0/8",
    "100.64.0.0/10",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "240.0.0.0/4",
    "fc00::/7",
    "fe80::/10",
)
# Refused in the manifest URLs only. Loopback and the unspecified address name
# no machine on this network, so they disclose nothing and are ordinary in a
# test that binds a socket; as a documentation or issue-tracker URL they are
# still a dead link for every user.
MANIFEST_ONLY_CIDRS = (
    "0.0.0.0/32",
    "127.0.0.0/8",
    "::/128",
    "::1/128",
)
# Suffixes that resolve against one network's resolver and nowhere else.
PRIVATE_SUFFIXES = (
    ".corp",
    ".home",
    ".home.arpa",
    ".intranet",
    ".internal",
    ".lan",
    ".local",
    ".localdomain",
)
