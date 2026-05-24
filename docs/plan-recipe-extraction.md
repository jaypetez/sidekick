# Recipe URL Ingredient Extraction

## Context

The user wants to send a recipe URL to the bot and have it extract ingredients and merge them into an existing Google Tasks grocery list. The existing `add_tasks` MCP tool already appends items to a list (creating it if needed), so the main work is fetching/parsing recipe pages.

## Approach

Add a single new MCP tool `fetch_recipe_page(url)` that fetches a recipe URL and returns cleaned content. Claude then extracts ingredients from the result and calls `add_tasks` to add them to the grocery list. No changes needed to `bot.py` — Claude naturally recognizes URLs and handles the two-step tool flow.

**Why this approach:**
- JSON-LD fast path: most popular recipe sites embed structured `recipeIngredient` data — extracted server-side with zero Claude tokens
- HTML fallback: strip boilerplate (scripts, nav, ads), truncate to ~8000 chars, let Claude parse ingredients from cleaned text
- No new dependencies beyond `httpx` + `beautifulsoup4` (both lightweight, pure Python)
- Follows existing MCP tool pattern — no architectural changes

## Files to Modify

| File | Change |
|------|--------|
| `pyproject.toml` | Add `httpx` and `beautifulsoup4` dependencies |
| `src/sidekick/mcp_server.py` | Add `fetch_recipe_page` tool (schema, dispatch, handler) |
| `src/sidekick/agent.py` | Add recipe guidance to system prompt |
| `tests/test_mcp_server.py` | Add tests for recipe fetching (JSON-LD, HTML fallback, errors, truncation) |
| `README.md` | Add recipe extraction to feature examples |

## Step 1 — Add dependencies (`pyproject.toml`)

```python
"httpx>=0.27",
"beautifulsoup4>=4.12",
```

## Step 2 — Add `fetch_recipe_page` tool (`mcp_server.py`)

**Imports:** Add `import httpx` and `from bs4 import BeautifulSoup`

**Tool schema** (add to `handle_list_tools`, tool #14):
```python
types.Tool(
    name="fetch_recipe_page",
    description="Fetch a recipe URL and return cleaned text for ingredient extraction. Returns structured JSON-LD recipe data if available, otherwise cleaned page text.",
    inputSchema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The recipe URL to fetch"},
        },
        "required": ["url"],
    },
),
```

**Dispatch:** `"fetch_recipe_page": self._fetch_recipe_page`

**Handler:** `_fetch_recipe_page(self, args)`:
1. `httpx.get(url, follow_redirects=True, timeout=15, headers={"User-Agent": "..."})`
2. Parse HTML with BeautifulSoup
3. **JSON-LD fast path**: scan `<script type="application/ld+json">` for `@type: "Recipe"` (handle both flat and `@graph` wrapper). Return `{"source": "json-ld", "name": ..., "ingredients": [...], "url": ...}`
4. **HTML fallback**: decompose `script/style/nav/footer/header/aside/iframe/noscript` tags, get text, collapse blank lines, truncate to 8000 chars. Return `{"source": "html-text", "text": ..., "url": ...}`
5. **Error handling**: catch `httpx.HTTPError`, return `{"error": "Failed to fetch URL: ..."}`

## Step 3 — Update system prompt (`agent.py`)

Add after the task list paragraph (after line 70):

```
When a user shares a recipe URL, use the fetch_recipe_page tool to get the recipe \
content. If the result includes a pre-parsed ingredient list (JSON-LD source), use \
those directly. If it returns raw text, read through it and identify the ingredients \
yourself. Then use add_tasks to add the ingredients to the user's grocery list. \
Ask which list to use if it's not obvious from context.
```

## Step 4 — Tests (`tests/test_mcp_server.py`)

Add tests using mocked `httpx.get`:

- `test_fetch_recipe_json_ld` — HTML with JSON-LD `@type: Recipe`, verify returns `source: "json-ld"` with ingredients list
- `test_fetch_recipe_json_ld_graph` — JSON-LD nested in `@graph` array (WordPress/Yoast pattern)
- `test_fetch_recipe_html_fallback` — no JSON-LD, verify returns `source: "html-text"` with scripts/styles stripped
- `test_fetch_recipe_truncation` — very long page text, verify truncated to ~8000 chars
- `test_fetch_recipe_http_error` — mock connection error, verify returns error dict
- Update `test_dispatch_all_tools_registered` to expect 14 tools

## Step 5 — Update README

Add to the examples section:

```
**Recipes**
- "Add ingredients from https://example.com/chicken-soup to my grocery list"
- "I want to make this: https://example.com/pasta — add what I need to Costco"
```

Add to the features table:

```
| **Recipe extraction** | Send a recipe URL and the bot extracts ingredients and adds them to your grocery list |
```

## Verification

1. `pip install -e ".[dev]"` — install new dependencies
2. `pytest tests/ -v` — all tests pass
3. Manual test via Telegram:
   - Send a recipe URL from a popular site (allrecipes, NYT Cooking, etc.)
   - Verify ingredients are extracted and added to a task list
   - Test with a site that has JSON-LD vs one that doesn't
   - Test with an invalid URL — should get a friendly error
