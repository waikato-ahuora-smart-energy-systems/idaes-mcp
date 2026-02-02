
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


```bash
uv run main.py # or whatever file you want to run
```

# Examples

The example files show working and broken idaes flowsheets. A description file is also provided.