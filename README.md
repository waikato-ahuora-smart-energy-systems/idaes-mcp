
# IDAES MCP Server

## Setup

```bash
uv sync
uv run idaes get-extensions
```

I'm not sure how nicely idaes get-extensions plays with uv. Make sure  the `ipopt` command works. 

If it doesn't, the easiest thing to do is install idaes locally as well:

```bash
pip install idaes-pse
idaes get-extensions
```


# Usage

This MVP starts an MCP-over-HTTP server from the same process that owns the model.

```bash
uv run main.py
```

The demo entrypoint builds a tiny model and starts the server at:

```text
http://127.0.0.1:8000/mcp
```

In your own script, build `m` first and then call:

```python
from idaes_mcp.server import start_mcp_server

start_mcp_server(m, host="127.0.0.1", port=8000)
```

Available tools:

- `idaes.list_models`
- `idaes.model_summary`
- `idaes.list_variables`
- `idaes.list_constraints`
- `idaes.top_constraint_residuals`
- `idaes.run_diagnostics`

# Examples

The example files show working and broken idaes flowsheets. A description file is also provided.
