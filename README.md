# TEST_REMOTE_SERVER

A Python MCP server connected to PostgreSQL for managing expenses and credits.

## Features
- List expenses
- List categories and subcategories
- List credits
- Summarize financial records
- Add expenses
- Search expenses
- Edit expenses
- Delete expenses
- Record credit entries

## Requirements
- Python
- uv
- PostgreSQL
- Claude Desktop or another MCP-compatible client

## Setup
1. Clone this repository.
2. Install dependencies: `uv sync`
3. Create a `.env` file in the project root with your PostgreSQL settings.
4. Start the server:

   `uv run fastmcp run src/test_remote_server/main.py`

## Security
Never commit `.env` or database credentials to GitHub.
