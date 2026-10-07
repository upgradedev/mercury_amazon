"""Decides the next D-pad key on the way to an app tile, from a uiautomator dump.

scripts/android_tv_footage.sh calls this after every press while it walks the Leanback
home screen to the Mercury tile. It reads one ``uiautomator dump`` XML file and prints
one line, ``ACTION<TAB>DETAIL``:

* ``FOCUSED``: the focused node, or a node inside it, names the target. DETAIL is that
  node's label. The caller presses Center.
* ``KEYCODE_DPAD_UP`` / ``DOWN`` / ``LEFT`` / ``RIGHT``: the key that moves focus towards
  the target tile, or towards the launcher's Apps entry when no tile names the target.
* ``OPEN``: the focused node is the Apps entry. The caller presses Center to open it.
* ``SEARCH``: neither the target nor an Apps entry is on screen. DETAIL is the focused
  node's signature, so the caller can sweep the rows and notice when focus stops moving.
* ``NOFOCUS``: no node is focused yet.

It only reads the dump. It never presses a key, and it never claims focus that the dump
does not show.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

APPS_ENTRY = re.compile(r"^(apps|all apps|see all apps|your apps|app list)$", re.IGNORECASE)
BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
#: A focused node larger than this share of the screen is a container, not a tile.
MAX_TILE_SHARE = 0.25


@dataclass
class Node:
    label: str
    bounds: tuple[int, int, int, int]
    focused: bool
    focusable: bool
    parent: "Node | None" = None
    children: list["Node"] = field(default_factory=list)

    @property
    def area(self) -> int:
        left, top, right, bottom = self.bounds
        return max(0, right - left) * max(0, bottom - top)

    @property
    def centre(self) -> tuple[float, float]:
        left, top, right, bottom = self.bounds
        return (left + right) / 2, (top + bottom) / 2

    def subtree(self):
        yield self
        for child in self.children:
            yield from child.subtree()

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


def parse(path: str) -> list[Node]:
    root = ET.parse(path).getroot()
    nodes: list[Node] = []

    def walk(element: ET.Element, parent: Node | None) -> None:
        for child in element:
            if child.tag != "node":
                continue
            match = BOUNDS.search(child.get("bounds", ""))
            bounds = tuple(int(v) for v in match.groups()) if match else (0, 0, 0, 0)
            label = (child.get("text") or "").strip() or (child.get("content-desc") or "").strip()
            node = Node(
                label=label,
                bounds=bounds,  # type: ignore[arg-type]
                focused=child.get("focused") == "true",
                focusable=child.get("focusable") == "true" or child.get("clickable") == "true",
                parent=parent,
            )
            if parent is not None:
                parent.children.append(node)
            nodes.append(node)
            walk(child, node)

    walk(root, None)
    return nodes


def focus_box(node: Node) -> Node:
    """The node a D-pad press can land on for this label: itself or a focusable ancestor."""
    if node.focusable:
        return node
    for ancestor in node.ancestors():
        if ancestor.focusable:
            return ancestor
    return node


def direction(focused: Node, target: Node) -> str:
    _, f_top, _, f_bottom = focused.bounds
    _, t_top, _, t_bottom = target.bounds
    fx, fy = focused.centre
    tx, ty = target.centre
    same_row = t_top < f_bottom and f_top < t_bottom
    if same_row:
        return "KEYCODE_DPAD_RIGHT" if tx > fx else "KEYCODE_DPAD_LEFT"
    return "KEYCODE_DPAD_DOWN" if ty > fy else "KEYCODE_DPAD_UP"


def contains(container: Node, node: Node) -> bool:
    return container is node or any(a is container for a in node.ancestors())


def decide(nodes: list[Node], target_text: str) -> tuple[str, str]:
    if not nodes:
        return "NOFOCUS", "empty dump"
    screen = max((n.area for n in nodes), default=1) or 1
    focused_nodes = [n for n in nodes if n.focused]
    if not focused_nodes:
        return "NOFOCUS", "no focused node"
    focused = min(focused_nodes, key=lambda n: n.area)
    shown = next((n.label for n in focused.subtree() if n.label), "-")
    signature = "{}@{}".format(shown, ",".join(str(v) for v in focused.bounds))

    wanted = target_text.lower()
    targets = [n for n in nodes if n.label and wanted in n.label.lower()]
    small_focus = focused.area <= MAX_TILE_SHARE * screen
    for target in targets:
        if small_focus and contains(focused, target):
            return "FOCUSED", target.label
    if targets:
        # Keep each target with its own focus box, so the label reported is the one
        # whose box was chosen, never another node that also matched.
        box, target = min(((focus_box(t), t) for t in targets), key=lambda pair: pair[0].area)
        small_box = box.area <= MAX_TILE_SHARE * screen
        if small_focus and small_box and contains(box, focused):
            return "FOCUSED", target.label
        return direction(focused, box), "towards {!r} from {}".format(target.label, signature)

    entries = [n for n in nodes if n.label and APPS_ENTRY.match(n.label)]
    for entry in entries:
        box = focus_box(entry)
        if box.focusable and box.area <= MAX_TILE_SHARE * screen:
            if contains(box, focused) or contains(focused, entry):
                return "OPEN", entry.label
            return direction(focused, box), "towards {!r} from {}".format(entry.label, signature)
    return "SEARCH", signature


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dump", help="a uiautomator dump XML file")
    parser.add_argument("--target", default="Mercury", help="text the tile's label contains")
    args = parser.parse_args(argv)
    try:
        nodes = parse(args.dump)
    except (ET.ParseError, OSError) as error:
        print("NOFOCUS\tunreadable dump: {}".format(error))
        return 0
    action, detail = decide(nodes, args.target)
    print("{}\t{}".format(action, detail.replace("\t", " ").replace("\n", " ")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
