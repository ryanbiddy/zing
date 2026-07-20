# SG-4 scan: MCP client prompt-capability landscape vs CONNECT claims

Scope: CONNECT.md claimed "clients without the prompts capability
(Codex CLI, Gemini CLI)" — written when both lacked it. Verified
against primary sources this cycle (live).

## Findings

- **Gemini CLI: the claim was STALE — prompts are now first-class.**
  gemini-cli serves MCP prompts as slash commands (prompts/get with
  named or positional args; landed via google-gemini/gemini-cli#4828,
  documented in the official MCP docs). Zing's four prompts appear as
  slash commands there, same as Claude clients. CONNECT.md corrected
  this cycle.
- **Codex CLI: the claim holds.** The official MCP docs (learn.chatgpt
  .com/docs/extend/mcp, the developers.openai.com redirect target)
  list STDIO servers, Streamable HTTP, and the `instructions` field —
  no prompts capability. `get_prompt` remains the right path there.
- **Bonus, verified against our server:** Codex reads the MCP
  `instructions` field and its docs advise keeping the first 512
  characters self-contained. Zing's instructions string is 322 chars,
  one self-contained paragraph — within budget, no change needed.

## Sources

- gemini-cli `docs/tools/mcp-server.md` (raw, re-fetched at the
  2026-07-19 citation audit — the prompts-as-slash-commands claim was
  originally taken from a SEARCH SUMMARY; the repo's own doc confirms it
  verbatim, including the `/cmd --arg="value"` and positional forms)
- https://github.com/google-gemini/gemini-cli/pull/4828
- https://learn.chatgpt.com/docs/extend/mcp?surface=cli
