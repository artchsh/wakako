"""Machine-readable description of the CLI, for `gsc commands`."""

import typer.main

from gsc_cli import client, output

CHOICES = {
    "--dims": list(client.VALID_DIMS),
    "--type": list(client.VALID_TYPES),
    "--format": list(output.FORMATS),
}


def _param(p) -> dict:
    info = {
        "name": p.name,
        "kind": p.param_type_name,  # "option" | "argument"
        "required": p.required,
        "multiple": p.multiple,
        "help": getattr(p, "help", None) or "",
    }
    if p.param_type_name == "option":
        info["flags"] = list(p.opts)
        info["default"] = None if p.default is None or p.name == "help" else p.default
        for flag in p.opts:
            if flag in CHOICES:
                info["choices"] = CHOICES[flag]
    return info


def describe(app) -> dict:
    root = typer.main.get_command(app)
    commands = []
    for name, cmd in sorted(root.commands.items()):
        if hasattr(cmd, "commands"):
            for sub_name, sub in sorted(cmd.commands.items()):
                commands.append(_command(f"{name} {sub_name}", sub))
        else:
            commands.append(_command(name, cmd))
    return {
        "name": "gsc",
        "commands": commands,
        "filter_operators": list(client.OPERATORS),
        "exit_codes": {
            "0": "ok",
            "1": "other error",
            "2": "usage error (bad argument/filter/date/format)",
            "3": "not logged in or session expired (a human must run `gsc login`)",
            "4": "no permission for that property",
            "5": "API quota exceeded",
        },
    }


def _command(name: str, cmd) -> dict:
    return {
        "name": name,
        "help": (cmd.help or "").strip(),
        "params": [_param(p) for p in cmd.params if p.name != "help"],
    }
