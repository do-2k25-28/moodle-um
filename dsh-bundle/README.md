# DeepSeek Harness bundle

Config-only bundle that registers `moodle-um` as an MCP client in a DSH profile.

- Server name: `um`
- Tool prefix: `mcp__um__`
- Transport: stdio

## Install

1. Edit [`cordis.patch.yml`](cordis.patch.yml): replace `/path/to/moodle-um`
   with the absolute path of your clone, and `/home/you` with your home.
2. Install the bundle:

```bash
dsh plugin --profile web add file:$PWD/dsh-bundle
```

Or, from the DSH plugin-manager tool:

```text
plugin_manager install_bundle target=file:$PWD/dsh-bundle
```

The tools appear as `mcp__um__moodle_status`, `mcp__um__moodle_list_courses`,
etc. Remove the bundle with:

```text
plugin_manager remove_bundle target=@local/dsh-moodle-um
```
