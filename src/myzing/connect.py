"""Print MCP client configs without changing client settings."""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import shlex
import sys
from urllib.parse import quote, urlencode


@dataclass(frozen=True)
class Client:
    format: str
    location: str
    shape: str = "mcpServers"
    note: str = ""
    guide: str = ""
    mac_location: str = ""
    linux_location: str = ""
    platforms: tuple[str, ...] = ("win32", "darwin")
    sources: tuple[str, ...] = ()
    checked: str = "2026-10-21"
    verified: bool = True
    reason: str = ""


def recipe(format: str, location: str, source: str, shape="mcpServers", **kwargs) -> Client:
    mac = kwargs.pop("mac_location", location)
    linux = kwargs.pop("linux_location", None)
    if linux is None:
        linux = mac if not any(part in mac for part in ("~/Library/", "macOS", "Not available", "%")) else ""
    platforms = kwargs.pop("platforms", ("win32", "darwin", *(["linux"] if linux else [])))
    if "linux" not in platforms:
        linux = ""
    sources = kwargs.pop("sources", ())
    return Client(format, location.replace("~/", "%USERPROFILE%/"), shape,
                  mac_location=mac, linux_location=linux, platforms=platforms,
                  sources=(source, *sources), **kwargs)


UI_FIELDS = ("Name the server zing and choose stdio. Enter the command, args and env\n"
             "in the client's separate fields. Each args element is one argument.\n"
             "Keep paths with spaces together. These are field values to copy.\n<ENTRY>")
HTTP_GUIDE = "Zing has no HTTP endpoint, so this client cannot launch it."
LAUNCHER_GUIDE = ("This app launches commands but has no documented MCP client config.\n"
                  "Run zing connect in a terminal and choose an MCP client.")


CLIENTS = {
    "claude-code": recipe("shell", "~/.claude.json (managed by claude mcp add)",
                          "https://code.claude.com/docs/en/mcp", "command"),
    "claude-desktop": recipe("json", "%APPDATA%/Claude/claude_desktop_config.json",
                             "https://modelcontextprotocol.io/docs/develop/connect-local-servers",
                             mac_location="~/Library/Application Support/Claude/claude_desktop_config.json"),
    "cursor": recipe("json", "~/.cursor/mcp.json", "https://cursor.com/docs/mcp"),
    "codex": recipe("toml", "~/.codex/config.toml", "https://developers.openai.com/codex/mcp", "mcp_servers",
                    note="Use CODEX_HOME/config.toml if you set CODEX_HOME."),
    "gemini": recipe("json", "~/.gemini/settings.json", "https://geminicli.com/docs/tools/mcp-server/"),
    "vscode": recipe("json", "Project .vscode/mcp.json",
                     "https://code.visualstudio.com/docs/agents/reference/mcp-configuration", "servers"),
    "windsurf": recipe("json", "%APPDATA%/devin/mcp_config.json", "https://docs.devin.ai/desktop/cascade/mcp",
                       mac_location="~/.config/devin/mcp_config.json",
                       note="This is the legacy Cascade setup in Devin Desktop. Older Windsurf uses ~/.codeium/windsurf/mcp_config.json. Devin Local has a different setup."),
    "cline": recipe("json", "Cline > MCP Servers > Configure > Configure MCP Servers (cline_mcp_settings.json)",
                    "https://docs.cline.bot/mcp/mcp-overview",
                    note="Use the IDE's config button. The directory depends on editor and profile. Cline CLI uses ~/.cline/data/settings/cline_mcp_settings.json."),
    "zed": recipe("json", "%APPDATA%/Zed/settings.json", "https://zed.dev/docs/ai/mcp", "context_servers",
                  mac_location="Zed command palette > Open Settings File", linux_location="~/.config/zed/settings.json",
                  sources=("https://github.com/zed-industries/zed/blob/main/docs/.doc-examples/configuration.md",
                           "https://zed.dev/docs/debugger"), verified=False,
                  reason="The official pages disagree on the macOS settings directory. Use Open Settings File.",
                  note="Merge context_servers into the user settings file opened by Zed."),
    "goose": recipe("yaml", "%APPDATA%/Block/goose/config/config.yaml",
                    "https://github.com/aaif-goose/goose/blob/main/documentation/docs/guides/config-files.md",
                    "extensions", mac_location="~/.config/goose/config.yaml"),
    "opencode": recipe("json", "~/.config/opencode/opencode.json", "https://opencode.ai/docs/mcp-servers/", "mcp",
                       sources=("https://opencode.ai/docs/config/",), note="Project opencode.json is also supported."),
    "lm-studio": recipe("json", "~/.lmstudio/mcp.json", "https://lmstudio.ai/blog/lmstudio-v0.3.17",
                        sources=("https://lmstudio.ai/docs/app/mcp",),
                        note="Program tab > Install > Edit mcp.json. Save to reload. Use a model that can call tools."),
    "hermes": recipe("yaml", "%LOCALAPPDATA%/hermes/config.yaml",
                     "https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp", "mcp_servers",
                     mac_location="~/.hermes/config.yaml",
                     sources=("https://hermes-agent.nousresearch.com/docs/getting-started/installation/",),
                     note="Paths are for the source or CLI install. HERMES_HOME overrides the data directory. Desktop packages can use their platform data directory."),
    "warp": recipe("json", "~/.warp/.mcp.json", "https://docs.warp.dev/agents/capabilities/mcp/",
                   note="Project .warp/.mcp.json is also supported."),
    "junie": recipe("json", "~/.junie/mcp/mcp.json", "https://junie.jetbrains.com/docs/junie-cli-mcp-configuration.html",
                    note="For Junie CLI. Project .junie/mcp/mcp.json is also supported. AI Assistant uses a separate setup."),
    "amp": recipe("json", "~/.config/amp/settings.json", "https://ampcode.com/docs/customize/mcp", "amp.mcpServers",
                  sources=("https://ampcode.com/docs/cli/settings",),
                  note="Project .amp/settings.json is also supported. Run Amp locally so it can launch Zing."),
    "roo": recipe("json", "Project .roo/mcp.json", "https://roocodeinc.github.io/Roo-Code/features/mcp/using-mcp-in-roo/",
                  note="Use Roo's MCP settings button for global mcp_settings.json. The directory depends on editor and profile."),
    "kilo": recipe("jsonc", "~/.config/kilo/kilo.jsonc", "https://kilo.ai/docs/automate/mcp/using-in-kilo-code", "mcp",
                   note="Project kilo.jsonc or .kilo/kilo.jsonc is also supported."),
    "kilo-legacy": recipe("text", "Legacy Kilo extension config; no current path confirmed",
                          "https://kilo.ai/docs/automate/mcp/using-in-kilo-code", verified=False,
                          reason="The docs describe kilo.jsonc. The old .kilocode/mcp.json format is unverified.",
                          guide="Use zing connect kilo for current Kilo. Check the docs for your older\nextension version before migrating its settings."),
    "cherry-studio": recipe("text", "Settings > MCP > MCP Servers > Add (manual stdio fields)",
                            "https://docs.cherryai.com.cn/advanced-basic/extensions/mcp", guide=UI_FIELDS),
    "jan": recipe("text", "Settings > MCP Servers > +", "https://docs.jan.ai/desktop/mcp", guide=UI_FIELDS,
                  note="Enable tool use for the selected model, then approve tool calls as needed."),
    "librechat": recipe("yaml", "librechat.yaml in the LibreChat app directory",
                        "https://www.librechat.ai/docs/configuration/librechat_yaml/object_structure/mcp_servers",
                        note="Merge mcpServers into the existing file. The process must have access to Zing's paths. A container cannot use host paths unchanged."),
    "msty": recipe("json", "Toolbox > Tools > Add New Tool > STDIO / JSON > Tool Configuration",
                   "https://docs.msty.ai/studio/toolbox/tools", "entry",
                   note="Paste the bare command/args/env object, then name the tool zing. Omit the mcpServers wrapper."),
    "boltai": recipe("json", "Not available on Windows", "https://docs.boltai.com/docs/plugins/mcp-servers",
                     mac_location="~/.boltai/mcp.json", platforms=("darwin",),
                     note="Settings > Plugins > + opens the MCP editor. Reload Config after an external edit."),
    "continue": recipe("yaml", "Project .continue/mcpServers/zing.yaml",
                       "https://docs.continue.dev/customize/deep-dives/mcp", "list",
                       note="Use IDE Agent mode. For global config.yaml, merge only the mcpServers list. Keep its metadata and models."),
    "raycast": recipe("text", "Install MCP Server command, or Manage MCP Servers > Install New Server",
                      "https://manual.raycast.com/ai/model-context-protocol", guide=UI_FIELDS,
                      platforms=("win32", "darwin"), sources=("https://www.raycast.com/changelog/windows",),
                      note="Requires Raycast Pro. Choose Stdio and paste the args JSON array intact into Arguments."),
    "open-webui": recipe("text", "Settings > Admin > Integrations > External Tool Servers",
                         "https://github.com/open-webui/mcpo", sources=("https://docs.openwebui.com/features/extensibility/mcp/",),
                         guide=HTTP_GUIDE, verified=False,
                         reason="Zing supplies no HTTP endpoint or mcpo bridge recipe."),
    "anythingllm": recipe("json", "%APPDATA%/anythingllm-desktop/storage/plugins/anythingllm_mcp_servers.json",
                          "https://docs.anythingllm.com/mcp-compatibility/desktop",
                          mac_location="~/Library/Application Support/anythingllm-desktop/storage/plugins/anythingllm_mcp_servers.json",
                          sources=("https://docs.anythingllm.com/mcp-compatibility/overview", "https://docs.anythingllm.com/installation-desktop/storage"),
                          note="Desktop only. Click the app version > Open storage to confirm the root. Agent Skills > Refresh reloads servers. Use @agent in chat."),
    "ollama": recipe("text", "No MCP config in Ollama; configure its client instead",
                     "https://docs.ollama.com/capabilities/tool-calling",
                     sources=("https://docs.openwebui.com/features/extensibility/mcp/", "https://docs.continue.dev/guides/ollama-guide"),
                     guide="Ollama is a model runtime. Use zing connect continue for an MCP client.\nConfigure an Ollama model that supports tools in that client."),
    "smithery-local": recipe("text", "MCPB publishing docs; no smithery.yaml recipe",
                             "https://smithery.ai/docs/build/publish", verified=False,
                             reason="A local smithery.yaml command/args schema was not established.",
                             guide="No smithery.yaml recipe is available. Use zing connect with a local\nMCP client. See docs/CONNECT.md for Zing's MCPB bundle."),
    "windows-odr": recipe("text", "An unpacked MCPB bundle's manifest.json",
                          "https://learn.microsoft.com/en-us/windows/ai/mcp/servers/mcp-manual", platforms=("win32",),
                          mac_location="Not available on macOS", verified=False,
                          reason="Zing's uv MCPB bundle has not been checked with Windows ODR.",
                          note="Windows preview, build 26220.7262 or later.",
                          guide="Windows ODR registers unpacked MCPB bundles. See docs/CONNECT.md\nfor Zing's uv bundle. No Zing ODR registration recipe has been checked."),
    "obsidian": recipe("text", "No documented Zing MCP config", "https://help.obsidian.md/uri",
                       verified=False, reason="Uoink's library mirror has no Zing equivalent.",
                       guide="No Obsidian MCP plugin or vault export is supplied by Zing.\nUse zing connect with a local MCP client."),
    "n8n": recipe("text", "Self-hosted n8n workflow UI", "https://docs.n8n.io/integrations/builtin/credentials/httprequest/",
                  sources=("https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.toolmcp/",
                           "https://github.com/n8n-io/n8n/releases/tag/n8n%401.114.0"), guide=HTTP_GUIDE,
                  verified=False, reason="The documented node needs an HTTP endpoint."),
    "make": recipe("text", "No direct localhost route from Make cloud runners", "https://help.make.com/on-premise-agent",
                   guide=HTTP_GUIDE, verified=False, reason="The documented route needs an HTTP endpoint."),
    "zapier": recipe("text", "No direct localhost route from Zapier cloud runners",
                     "https://help.zapier.com/hc/en-us/articles/44391646192397-Ways-to-make-API-requests-in-Zapier",
                     guide=HTTP_GUIDE, verified=False, reason="The documented route needs an HTTP endpoint."),
    "autohotkey": recipe("text", "A user-created .ahk file (AutoHotkey v2)",
                         "https://github.com/AutoHotkey/AutoHotkeyDocs/blob/v2/docs/lib/Run.htm", platforms=("win32",),
                         mac_location="Not available on macOS", guide=LAUNCHER_GUIDE, verified=False,
                         reason="Uoink's search launcher has no Zing MCP equivalent."),
    "powertoys": recipe("text", "PowerToys Command Palette > Run commands",
                        "https://learn.microsoft.com/en-us/windows/powertoys/command-palette/overview", platforms=("win32",),
                        mac_location="Not available on macOS", guide=LAUNCHER_GUIDE, verified=False,
                        reason="Uoink's search launcher has no Zing MCP equivalent."),
    "alfred": recipe("text", "Not available on Windows", "https://www.alfredapp.com/help/workflows/actions/run-script/",
                     mac_location="Workflow > Run Script (/bin/zsh)", platforms=("darwin",),
                     guide=LAUNCHER_GUIDE, verified=False, reason="Uoink's search launcher has no Zing MCP equivalent."),
    "kiro": recipe("json", "~/.kiro/settings/mcp.json", "https://kiro.dev/docs/mcp/configuration/",
                   note="Project .kiro/settings/mcp.json is also supported. Review tool approvals in Kiro."),
    "copilot-cli": recipe("json", "~/.copilot/mcp-config.json",
                          "https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers",
                          note="COPILOT_HOME overrides the directory. This is for GitHub Copilot CLI. VS Code uses the servers format."),
    "auggie": recipe("json", "Not native; WSL uses $HOME/.augment/settings.json inside WSL",
                     "https://docs.augmentcode.com/cli/integrations", mac_location="~/.augment/settings.json",
                     sources=("https://docs.augmentcode.com/cli/setup-auggie/install-auggie-cli",), platforms=("darwin", "linux"),
                     note="For WSL, install and run Zing inside WSL to print Linux paths."),
    "factory-droid": recipe("json", "~/.factory/mcp.json", "https://docs.factory.com/harness/mcp",
                            note="Project .factory/mcp.json is also supported."),
    "qwen-code": recipe("json", "~/.qwen/settings.json",
                        "https://qwenlm.github.io/qwen-code-docs/en/users/"  # Avoid a false home-path match.
                        "features/mcp/",
                        note="Project .qwen/settings.json is also supported."),
    "crush": recipe("crushrc", "~/.config/crush/crushrc", "https://github.com/charmbracelet/crush/blob/main/README.md", "command",
                    note="Paste into crushrc. Crush uses its built-in Bash interpreter on every platform. XDG_CONFIG_HOME overrides .config. Project .crushrc or crushrc is also supported."),
    "antigravity": recipe("json", "~/.gemini/config/mcp_config.json", "https://www.antigravity.google/docs/mcp",
                          note="Shared App/IDE/CLI config. Project .agents/mcp_config.json is also supported. In the IDE use MCP Servers > Manage MCP Servers > View raw config."),
    "chatbox": recipe("text", "Settings > MCP > Add Server > Local (stdio)",
                      "https://api.chatboxai.app/en/guide/work-mode/configuration", guide=UI_FIELDS,
                      note="Desktop only. Test the connection before saving, then enable the server."),
    "dive": recipe("json", "MCP server settings JSON editor", "https://github.com/OpenAgentPlatform/Dive/blob/main/MCP_SETUP.md",
                   note="Merge the zing server into mcpServers and enable it."),
    "perplexity": recipe("text", "Local MCP is not supported on Windows",
                         "https://www.perplexity.ai/help-center/en/articles/11502712-local-and-remote-mcps-for-perplexity",
                         mac_location="Mac app > Plugins > Add custom > Simple (local MCP)", platforms=("darwin",),
                         guide="Install the PerplexityXPC helper from the Mac app's local MCP setup.\nAdd a custom local connector. In Simple, name it zing and enter this command.\n<SHELL_COMMAND>\nSave, wait for Running, then enable it under Sources. Local MCP is Mac-only."),
}


def client_spec(client: str) -> Client:
    spec = CLIENTS[client]
    platform = {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}.get(sys.platform, sys.platform)
    location = {"win32": spec.location, "darwin": spec.mac_location, "linux": spec.linux_location}.get(sys.platform, "")
    if sys.platform not in spec.platforms:
        reason = f"No documented recipe for {client} on {platform}."
        return replace(spec, format="text", location=location or reason, guide=reason, verified=False,
                       reason=" ".join(part for part in (spec.reason, reason) if part))
    return replace(spec, location=location)


def server_entry() -> dict:
    env = {}
    home = os.environ.get("ZING_HOME", "").strip()
    if home:
        env["ZING_HOME"] = str(Path(home).expanduser().absolute())
    return {"command": str(Path(sys.executable).absolute()),  # Keep venv symlinks.
            "args": ["-m", "myzing.cli", "serve-mcp"], "env": env}


def deeplink(client: str) -> str:
    entry = server_entry()
    if client == "cursor":
        config = base64.b64encode(json.dumps(entry, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode("ascii")
        return "cursor://anysphere.cursor-deeplink/mcp/install?" + urlencode({"name": "zing", "config": config})
    if client == "vscode":
        return "vscode:mcp/install?" + quote(json.dumps({"name": "zing", "type": "stdio", **entry},
                                                      ensure_ascii=False, separators=(",", ":")), safe="")
    raise ValueError("--deeplink requires cursor or vscode")


def render(client: str) -> str:
    spec = client_spec(client)
    entry = server_entry()
    command, args, env = entry["command"], entry["args"], entry["env"]
    if spec.format == "text":
        shell = shlex.join(["/usr/bin/env", *(f"{k}={v}" for k, v in env.items()), command, *args])
        return spec.guide.replace("<ENTRY>", json.dumps(entry, indent=2, ensure_ascii=False)).replace("<SHELL_COMMAND>", shell)
    if spec.format == "shell":
        parts = ["claude", "mcp", "add", "--scope", "user",
                 *(part for key, value in env.items() for part in ("-e", f"{key}={value}")),
                 "--transport", "stdio", "zing", "--", command, *args]
        if sys.platform == "win32":
            return " ".join("'" + part.replace("'", "''") + "'" if i >= 3 else part for i, part in enumerate(parts))
        return shlex.join(parts)
    if spec.format == "crushrc":
        return shlex.join(["mcp", "add", "zing", "--command", command, "--args", *args,
                           *(part for key, value in env.items() for part in ("--env", key, value))])
    if spec.format == "toml":
        return ("[mcp_servers.zing]\ncommand = " + json.dumps(command, ensure_ascii=False)
                + "\nargs = " + json.dumps(args, ensure_ascii=False) + "\n\n[mcp_servers.zing.env]\n"
                + "\n".join(f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in env.items()))
    if spec.shape == "list":
        return json.dumps({"name": "Zing", "version": "1.0.0", "schema": "v1",
                           "mcpServers": [{"name": "zing", **entry}]}, indent=2, ensure_ascii=False)
    if spec.shape == "entry":
        return json.dumps(entry, indent=2, ensure_ascii=False)
    if spec.shape == "servers" or client in ("librechat", "factory-droid"):
        entry = {"type": "stdio", **entry}
    elif spec.shape == "extensions":
        entry = {"name": "zing", "type": "stdio", "enabled": True,
                 "cmd": command, "args": args, "envs": env, "timeout": 300}
    elif spec.shape == "mcp":
        entry = {"type": "local", "command": [command, *args], "environment": env, "enabled": True}
    elif client == "copilot-cli":
        entry = {"type": "local", **entry, "tools": ["*"]}
    elif client == "dive":
        entry = {**entry, "enabled": True}
    return json.dumps({spec.shape: {"zing": entry}}, indent=2, ensure_ascii=False)


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing connect", description=__doc__)
    parser.add_argument("client", nargs="?", help="client name from zing connect")
    parser.add_argument("--json", action="store_true", help="print the recipe and its source as JSON")
    parser.add_argument("--deeplink", action="store_true", help="print an install link for Cursor or VS Code")
    args = parser.parse_args(argv)
    if args.client is not None and args.client not in CLIENTS:
        print(f"unknown client '{args.client}'. Run zing connect to list them.", file=sys.stderr)
        return 2
    if args.deeplink and args.client not in ("cursor", "vscode"):
        print("--deeplink requires cursor or vscode", file=sys.stderr)
        return 2
    if args.client is None:
        if args.json:
            print("--json requires a client. Run zing connect to list them.", file=sys.stderr)
            return 2
        for client in CLIENTS:
            spec = client_spec(client)
            print(f"{client}\t{spec.format}\t{spec.location}")
        return 0
    spec = client_spec(args.client)
    output = deeplink(args.client) if args.deeplink else render(args.client)
    format = "deeplink" if args.deeplink else spec.format
    note = spec.note
    if spec.format == "yaml":
        note += "\nJSON-form YAML 1.2. Merge the keys into the existing YAML file."
    if spec.format == "shell":
        note += "\nRun in PowerShell." if sys.platform == "win32" else "\nRun in a POSIX shell."
    source = {"urls": list(spec.sources), "checked": spec.checked, "verified": spec.verified, "reason": spec.reason}
    if args.json:
        print(json.dumps({"client": args.client, "format": format, "location": spec.location,
                          "entry": output if format != "text" else None, "note": note.strip(),
                          "guide": output if format == "text" else "", "source": source}, indent=2, ensure_ascii=False))
    else:
        print(f"{args.client} ({format})\n{spec.location}", file=sys.stderr)
        if note.strip():
            print(note.strip(), file=sys.stderr)
        print(f"Client docs checked {spec.checked}. Not yet tested inside the client.", file=sys.stderr)
        if not spec.verified:
            print(spec.reason, file=sys.stderr)
        print("\n".join(spec.sources), file=sys.stderr)
        print(output)
    return 0
