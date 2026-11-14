"""Render the live Typer/Click command tree for ``opal-yolo tree``.

The tree is generated from the application at call time, so it reflects the
current commands and parameters. Required options print as ``--option``;
optional options print as ``[--option]``. Positional arguments use the same
required/optional notation. The default view uses ``rich.tree.Tree`` with
terminal-only styling; ``--ascii`` produces a log-safe variant.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.text import Text
from rich.tree import Tree
from typer.main import get_command

console = Console()


def _param_label(param: object) -> tuple[str, str] | None:
    if getattr(param, "hidden", False) or getattr(param, "expose_value", True) is False:
        return None
    kind = getattr(param, "param_type_name", "")
    required = getattr(param, "required", False)
    style = "yellow" if required else "dim"
    if kind == "argument":
        name = param.name  # type: ignore[attr-defined]
        return (name if required else f"[{name}]", style)
    if kind != "option":
        return None
    opts = [*getattr(param, "opts", ()), *getattr(param, "secondary_opts", ())]
    flag = next(
        (option for option in opts if option.startswith("--")),
        opts[0] if opts else param.name,  # type: ignore[attr-defined]
    )
    if flag == "--help":
        return None
    return (flag if required else f"[{flag}]", style)


def _usage_labels(command: object) -> list[tuple[str, str]]:
    return [
        label
        for parameter in getattr(command, "params", ())
        if (label := _param_label(parameter))
    ]


def _visible_commands(group: object) -> list[tuple[str, object]]:
    return [
        (name, command)
        for name, command in getattr(group, "commands", {}).items()
        if not getattr(command, "hidden", False)
    ]


def _is_group(command: object) -> bool:
    return bool(getattr(command, "commands", None))


def _styled_label(name: str, command: object, name_style: str) -> Text:
    text = Text(name, style=name_style)
    for label, style in _usage_labels(command):
        text.append(f" {label}", style=style)
    return text


def _plain_label(name: str, command: object) -> str:
    return " ".join([name, *(label for label, _ in _usage_labels(command))])


def _add_commands(node: Tree, group: object) -> None:
    for name, command in _visible_commands(group):
        child = node.add(
            _styled_label(name, command, "bold cyan" if _is_group(command) else "cyan"),
            guide_style="blue",
        )
        if _is_group(command):
            _add_commands(child, command)


def render_tree(root: object, label: str) -> Tree:
    """Render a Click command/group as a styled Rich tree rooted at ``label``."""
    tree = Tree(_styled_label(label, root, "bold green"), guide_style="blue")
    _add_commands(tree, root)
    return tree


def _ascii_lines(group: object, prefix: str) -> list[str]:
    lines: list[str] = []
    visible = _visible_commands(group)
    for index, (name, command) in enumerate(visible):
        last = index == len(visible) - 1
        connector = "`-- " if last else "|-- "
        lines.append(f"{prefix}{connector}{_plain_label(name, command)}")
        if _is_group(command):
            lines.extend(_ascii_lines(command, prefix + ("    " if last else "|   ")))
    return lines


def render_ascii_tree(root: object, label: str) -> str:
    """Render a Click command/group as a color-free ASCII tree."""
    lines = [_plain_label(label, root)]
    lines.extend(_ascii_lines(root, ""))
    return "\n".join(lines)


def register(app: typer.Typer, label: str = "opal-yolo") -> None:
    """Attach the ``tree`` command to ``app``."""

    @app.command("tree")
    def tree(
        ascii_guides: bool = typer.Option(
            False,
            "--ascii",
            help="ASCII guides with no color, safe for logs and pipes.",
        ),
    ) -> None:
        """Print the command tree with per-command parameters."""
        root = get_command(app)
        if ascii_guides:
            typer.echo(render_ascii_tree(root, label))
        else:
            console.print(render_tree(root, label))
